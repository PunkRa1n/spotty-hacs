"""Diagnose-Download – enthält die gelernten Profile (= Export/Backup)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from . import SpottyConfigEntry

TO_REDACT = {CONF_URL, CONF_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SpottyConfigEntry) -> dict[str, Any]:
    coord = entry.runtime_data.coordinator
    snap = coord.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "threshold_pct": coord.threshold_pct,
        "slots": len(snap.slots) if snap else 0,
        "prices_known_until": snap.slots[-1].end.isoformat() if snap and snap.slots else None,
        "profiles": coord.store.as_dict(),
    }
