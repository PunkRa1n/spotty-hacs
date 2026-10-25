"""Schalter 'Profil einlernen' je Gerät.

Ein: Aufzeichnung startet, das Gerät jetzt einschalten.
Endet automatisch, wenn das Gerät lange genug unter Standby liegt.
Manuell aus: Aufzeichnung beenden und speichern.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SpottyConfigEntry
from .coordinator import DeviceConfig, SpottyCoordinator
from .entity import SpottyApplianceEntity
from .learner import ProfileLearner


async def async_setup_entry(
    hass: HomeAssistant, entry: SpottyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        LearnSwitch(runtime.coordinator, dev, runtime.learners[key])
        for key, dev in runtime.coordinator.devices.items()
    )


class LearnSwitch(SpottyApplianceEntity, SwitchEntity):
    def __init__(self, coordinator: SpottyCoordinator, device: DeviceConfig, learner: ProfileLearner) -> None:
        super().__init__(coordinator, device, "learn", "switch", f"{device.key}_einlernen")
        self._learner = learner

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._learner.async_add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        return self._learner.active

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._learner.async_start()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._learner.async_finish()
