"""Gelernte Lastprofile dauerhaft speichern – unabhängig vom Recorder.

Liegt in .storage/spotty.<entry_id> und ist damit in jedem HA-Backup.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_VERSION


class ProfileStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self._profiles: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._profiles = data.get("profiles", {})

    def get(self, key: str) -> dict[str, Any] | None:
        return self._profiles.get(key)

    def watts(self, key: str) -> list[float] | None:
        prof = self._profiles.get(key)
        return prof["watts"] if prof else None

    def as_dict(self) -> dict[str, Any]:
        return {"profiles": self._profiles}

    async def async_set(self, key: str, watts: list[float], source: str, standby_w: float) -> None:
        self._profiles[key] = {
            "watts": watts,
            "source": source,
            "standby_w": standby_w,
            "learned_at": dt_util.utcnow().isoformat(),
        }
        await self._store.async_save(self.as_dict())

    async def async_prune(self, valid_keys: set[str]) -> None:
        stale = set(self._profiles) - valid_keys
        if stale:
            for key in stale:
                del self._profiles[key]
            await self._store.async_save(self.as_dict())

    async def async_remove(self) -> None:
        await self._store.async_remove()
