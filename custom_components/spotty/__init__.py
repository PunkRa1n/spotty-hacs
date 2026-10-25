"""Spotty Strompreis-Optimierer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import CONF_DEVICES, DOMAIN
from .coordinator import DeviceConfig, SpottyCoordinator
from .learner import ProfileLearner
from .price_source import PriceSource
from .profile_store import ProfileStore
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class SpottyRuntime:
    coordinator: SpottyCoordinator
    learners: dict[str, ProfileLearner]


type SpottyConfigEntry = ConfigEntry[SpottyRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SpottyConfigEntry) -> bool:
    devices = {
        key: DeviceConfig.from_options(key, raw)
        for key, raw in entry.options.get(CONF_DEVICES, {}).items()
    }

    store = ProfileStore(hass, entry.entry_id)
    await store.async_load()
    await store.async_prune(set(devices))
    _prune_devices(hass, entry, set(devices))

    coordinator = SpottyCoordinator(hass, entry, PriceSource(hass, dict(entry.data)), store, devices)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SpottyRuntime(
        coordinator=coordinator,
        learners={key: ProfileLearner(hass, coordinator, dev) for key, dev in devices.items()},
    )

    async def _tick(_now: datetime) -> None:
        await coordinator.async_refresh()

    # Viertelstündlich, 5 s nach dem Intervallwechsel – wie bisher in AppDaemon
    entry.async_on_unload(async_track_time_change(hass, _tick, minute=[0, 15, 30, 45], second=5))
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SpottyConfigEntry) -> bool:
    for learner in entry.runtime_data.learners.values():
        learner.async_cancel()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await ProfileStore(hass, entry.entry_id).async_remove()


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def device_identifier(entry_id: str, key: str) -> str:
    return f"{entry_id}__{key}"


def _prune_devices(hass: HomeAssistant, entry: ConfigEntry, keys: set[str]) -> None:
    """Geräte entfernen, die in den Optionen gelöscht wurden."""
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        for domain, ident in device.identifiers:
            if domain == DOMAIN and "__" in ident and ident.split("__", 1)[1] not in keys:
                registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
