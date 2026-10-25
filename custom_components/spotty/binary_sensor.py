"""Binärsensoren."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SpottyConfigEntry
from .entity import SpottyHubEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: SpottyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = entry.runtime_data.coordinator
    async_add_entities(
        [
            CheapestIntervalSensor(coord, "cheapest_interval", "binary_sensor", "guenstigstes_stromintervall"),
            CheapBlockActiveSensor(coord, "cheap_block_active", "binary_sensor", "guenstiger_zeitraum_aktiv"),
        ]
    )


class CheapestIntervalSensor(SpottyHubEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return self.coordinator.data.cheapest_now


class CheapBlockActiveSensor(SpottyHubEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return self.coordinator.data.cheap_block_active
