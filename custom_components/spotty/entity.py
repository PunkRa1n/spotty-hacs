"""Basisklassen für Entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import DeviceConfig, SpottyCoordinator


class SpottyHubEntity(CoordinatorEntity[SpottyCoordinator]):
    """Preis-Entities am Gerät 'Spotty'.

    Die entity_id wird vorgegeben (sensor.spotty_aktueller_strompreis …), damit
    bestehende Dashboards und Automationen aus der AppDaemon-Zeit weiterlaufen.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SpottyCoordinator, key: str, platform: str, object_id: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
        self.entity_id = f"{platform}.{slugify(entry.title)}_{object_id}"


class SpottyApplianceEntity(CoordinatorEntity[SpottyCoordinator]):
    """Entities eines Haushaltsgeräts (eigenes Gerät, hängt am Hub)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SpottyCoordinator, device: DeviceConfig, key: str, platform: str, object_id: str
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.device = device
        self._attr_unique_id = f"{entry.entry_id}_{device.key}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}__{device.key}")},
            name=device.name,
            via_device=(DOMAIN, entry.entry_id),
        )
        self.entity_id = f"{platform}.{slugify(entry.title)}_{object_id}"
