"""Sensoren."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SpottyConfigEntry
from .coordinator import DeviceConfig, SpottyCoordinator
from .entity import SpottyApplianceEntity, SpottyHubEntity
from .learner import ProfileLearner
from .profile import energy_kwh
from .pricing import Snapshot

CT_KWH = "ct/kWh"


@dataclass(frozen=True, kw_only=True)
class SpottySensorDescription(SensorEntityDescription):
    object_id: str
    value_fn: Callable[[Snapshot], Any]
    attr_fn: Callable[[Snapshot], dict[str, Any]] | None = None


def _price(**kw: Any) -> dict[str, Any]:
    return {
        "native_unit_of_measurement": CT_KWH,
        "state_class": SensorStateClass.MEASUREMENT,
        "suggested_display_precision": 2,
        **kw,
    }


def _ts(**kw: Any) -> dict[str, Any]:
    return {"device_class": SensorDeviceClass.TIMESTAMP, **kw}


HUB_SENSORS: tuple[SpottySensorDescription, ...] = (
    SpottySensorDescription(
        key="current_price", object_id="aktueller_strompreis",
        value_fn=lambda s: s.current.price if s.current else None, **_price(),
    ),
    SpottySensorDescription(
        key="current_price_eur", object_id="aktueller_strompreis_eur",
        native_unit_of_measurement="EUR/kWh", state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        value_fn=lambda s: s.current.price / 100 if s.current else None,
    ),
    SpottySensorDescription(
        key="next_price", object_id="naechster_strompreis",
        value_fn=lambda s: s.next.price if s.next else None, **_price(),
    ),
    SpottySensorDescription(
        key="today_min_price", object_id="niedrigster_strompreis_wert",
        value_fn=lambda s: s.today_min.price if s.today_min else None, **_price(),
    ),
    SpottySensorDescription(
        key="today_min_time", object_id="niedrigster_strompreis_zeit",
        value_fn=lambda s: s.today_min.start if s.today_min else None, **_ts(),
    ),
    SpottySensorDescription(
        key="today_max_price", object_id="hoechster_strompreis_wert",
        value_fn=lambda s: s.today_max.price if s.today_max else None, **_price(),
    ),
    SpottySensorDescription(
        key="today_max_time", object_id="hoechster_strompreis_zeit",
        value_fn=lambda s: s.today_max.start if s.today_max else None, **_ts(),
    ),
    SpottySensorDescription(
        key="threshold", object_id="schwelle", value_fn=lambda s: s.threshold, **_price(),
    ),
    SpottySensorDescription(
        key="cheap_block_start", object_id="laengster_guenstiger_zeitraum_start",
        value_fn=lambda s: s.cheap_block.start if s.cheap_block else None, **_ts(),
    ),
    SpottySensorDescription(
        key="cheap_block_end", object_id="laengster_guenstiger_zeitraum_ende",
        value_fn=lambda s: s.cheap_block.end if s.cheap_block else None, **_ts(),
    ),
    SpottySensorDescription(
        key="cheap_block_duration", object_id="laengster_guenstiger_zeitraum_dauer",
        device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda s: s.cheap_block.duration_min if s.cheap_block else None,
    ),
    SpottySensorDescription(
        key="cheap_block_avg_price", object_id="guenstigster_durchschnittspreis",
        value_fn=lambda s: s.cheap_block.avg_price if s.cheap_block else None, **_price(),
    ),
    SpottySensorDescription(
        key="forecast", object_id="forecast",
        value_fn=lambda s: s.forecast[0]["price"] if s.forecast else None,
        attr_fn=lambda s: {"forecast": s.forecast},
        **_price(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SpottyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    coord = runtime.coordinator
    entities: list[SensorEntity] = [HubSensor(coord, d) for d in HUB_SENSORS]
    for key, dev in coord.devices.items():
        entities.append(OptimalStartSensor(coord, dev))
        entities.append(ProfileStatusSensor(coord, dev, runtime.learners[key]))
    async_add_entities(entities)


class HubSensor(SpottyHubEntity, SensorEntity):
    entity_description: SpottySensorDescription
    # Die Prognose-Liste nicht in die Datenbank schreiben – die bläht sie nur auf
    _unrecorded_attributes = frozenset({"forecast"})

    def __init__(self, coordinator: SpottyCoordinator, description: SpottySensorDescription) -> None:
        super().__init__(coordinator, description.key, "sensor", description.object_id)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attr_fn
        return fn(self.coordinator.data) if fn else None


class OptimalStartSensor(SpottyApplianceEntity, SensorEntity):
    """Nächster optimaler Start – über alle bekannten Preise, auch über Mitternacht."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SpottyCoordinator, device: DeviceConfig) -> None:
        super().__init__(coordinator, device, "optimal_start", "sensor", f"optimaler_{device.key}_start")

    @property
    def native_value(self) -> Any:
        res = self.coordinator.data.devices.get(self.device.key)
        return res.start if res else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        res = self.coordinator.data.devices.get(self.device.key)
        watts = self.coordinator.store.watts(self.device.key)
        attrs: dict[str, Any] = {"fertig_bis": self.device.finish_by.isoformat() if self.device.finish_by else None}
        if watts:
            attrs.update(dauer_min=len(watts), energie_kwh=round(energy_kwh(watts), 3))
        if res:
            attrs.update(
                ende=res.end.isoformat(),
                kosten_ct=round(res.cost_ct, 2),
                kosten_bei_start_jetzt_ct=round(res.cost_now_ct, 2) if res.cost_now_ct is not None else None,
                ersparnis_ct=round(res.saving_ct, 2) if res.saving_ct is not None else None,
                preise_bekannt_bis=res.horizon_end.isoformat(),
            )
        return attrs


class ProfileStatusSensor(SpottyApplianceEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["no_profile", "learning", "ready"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SpottyCoordinator, device: DeviceConfig, learner: ProfileLearner) -> None:
        super().__init__(coordinator, device, "profile_status", "sensor", f"{device.key}_lastprofil")
        self._learner = learner

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._learner.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        if self._learner.active:
            return "learning"
        return "ready" if self.coordinator.store.watts(self.device.key) else "no_profile"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        prof = self.coordinator.store.get(self.device.key)
        if not prof:
            return None
        watts = prof["watts"]
        return {
            "dauer_min": len(watts),
            "energie_kwh": round(energy_kwh(watts), 3),
            "spitzenleistung_w": round(max(watts)),
            "gelernt_am": prof["learned_at"],
            "quelle": prof["source"],
        }
