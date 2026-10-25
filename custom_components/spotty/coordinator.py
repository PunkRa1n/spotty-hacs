"""Coordinator: holt Preise viertelstündlich und rechnet alles neu."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FINISH_BY,
    CONF_POWER_ENTITY,
    CONF_STANDBY_W,
    CONF_TAIL_MIN,
    DEFAULT_STANDBY_W,
    DEFAULT_TAIL_MIN,
    DEFAULT_THRESHOLD_PCT,
    DOMAIN,
)
from .price_source import PriceSource, PriceSourceError
from .pricing import Slot, Snapshot, analyse, merge_slots
from .profile_store import ProfileStore

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DeviceConfig:
    key: str
    name: str
    power_entity: str
    standby_w: float
    finish_by: time | None
    tail_min: int

    @classmethod
    def from_options(cls, key: str, raw: dict[str, Any]) -> DeviceConfig:
        finish = raw.get(CONF_FINISH_BY)
        return cls(
            key=key,
            name=raw[CONF_NAME],
            power_entity=raw[CONF_POWER_ENTITY],
            standby_w=float(raw.get(CONF_STANDBY_W, DEFAULT_STANDBY_W)),
            finish_by=time.fromisoformat(finish) if finish else None,
            tail_min=int(raw.get(CONF_TAIL_MIN, DEFAULT_TAIL_MIN)),
        )


class SpottyCoordinator(DataUpdateCoordinator[Snapshot]):
    """Kein eigenes Intervall – wird zu :00/:15/:30/:45 angestoßen (siehe __init__)."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source: PriceSource,
        store: ProfileStore,
        devices: dict[str, DeviceConfig],
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}", update_interval=None
        )
        self.source = source
        self.store = store
        self.devices = devices
        self.threshold_pct = DEFAULT_THRESHOLD_PCT
        self._slots: list[Slot] = []

    async def _async_update_data(self) -> Snapshot:
        now = dt_util.utcnow()
        try:
            fresh = await self.source.async_fetch()
        except PriceSourceError as err:
            if not any(s.end > now for s in self._slots):
                raise UpdateFailed(f"Preisabruf fehlgeschlagen: {err}") from err
            # Ein Aussetzer der API soll nicht alle Sensoren killen
            _LOGGER.warning("Preisabruf fehlgeschlagen (%s) – rechne mit gespeicherten Preisen", err)
        else:
            self._slots = merge_slots(self._slots, fresh, keep_after=now - timedelta(days=1))
        return await self._async_compute(now)

    async def _async_compute(self, now: datetime | None = None) -> Snapshot:
        inputs = {
            key: (self.store.watts(key), dev.finish_by) for key, dev in self.devices.items()
        }
        return await self.hass.async_add_executor_job(
            analyse,
            list(self._slots),
            now or dt_util.utcnow(),
            dt_util.get_default_time_zone(),
            self.threshold_pct,
            inputs,
        )

    async def async_recompute(self) -> None:
        """Neu rechnen ohne neuen Abruf (Schwelle geändert, Profil gelernt)."""
        if self._slots:
            self.async_set_updated_data(await self._async_compute())
