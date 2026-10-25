"""Schwelle in Prozent – ersetzt den Helfer input_number.spotty_strompreis_schwelle_prozent."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SpottyConfigEntry
from .entity import SpottyHubEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: SpottyConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ThresholdNumber(entry.runtime_data.coordinator, "threshold_percent", "number", "strompreis_schwelle_prozent")])


class ThresholdNumber(SpottyHubEntity, RestoreNumber):
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            if last.native_value != self.coordinator.threshold_pct:
                self.coordinator.threshold_pct = float(last.native_value)
                await self.coordinator.async_recompute()

    @property
    def native_value(self) -> float:
        return self.coordinator.threshold_pct

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.threshold_pct = value
        await self.coordinator.async_recompute()
