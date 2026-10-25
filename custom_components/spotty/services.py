"""Aktionen: Profil aus CSV importieren oder aus dem Recorder-Verlauf lernen."""

from __future__ import annotations

import os
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .learner import state_to_watts
from .profile import build_profile, clamp_start, parse_history_csv

if TYPE_CHECKING:
    from . import SpottyRuntime
    from .coordinator import DeviceConfig

ATTR_DEVICE_ID = "device_id"
ATTR_PATH = "path"
ATTR_START = "start"
ATTR_END = "end"

IMPORT_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string, vol.Required(ATTR_PATH): cv.string})
HISTORY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_START): cv.datetime,
        vol.Required(ATTR_END): cv.datetime,
    }
)


def _resolve(hass: HomeAssistant, device_id: str) -> tuple[SpottyRuntime, DeviceConfig]:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for domain, ident in device.identifiers:
            if domain != DOMAIN or "__" not in ident:
                continue
            entry_id, key = ident.split("__", 1)
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.state is not ConfigEntryState.LOADED:
                break
            runtime: SpottyRuntime = entry.runtime_data
            if key in runtime.coordinator.devices:
                return runtime, runtime.coordinator.devices[key]
    raise ServiceValidationError("Kein Spotty-Gerät (Waschmaschine o. ä.) ausgewählt")


async def _save(runtime: SpottyRuntime, dev: DeviceConfig, watts: list[float] | None, source: str) -> None:
    if not watts:
        raise ServiceValidationError(f"Kein Lauf über {dev.standby_w:g} W in den Daten gefunden")
    await runtime.coordinator.store.async_set(dev.key, watts, source, dev.standby_w)
    runtime.learners[dev.key].async_notify()
    await runtime.coordinator.async_recompute()


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(moment)


def async_setup_services(hass: HomeAssistant) -> None:
    async def import_profile(call: ServiceCall) -> None:
        runtime, dev = _resolve(hass, call.data[ATTR_DEVICE_ID])
        config_dir = os.path.realpath(hass.config.config_dir)
        raw = call.data[ATTR_PATH]
        path = os.path.realpath(raw if os.path.isabs(raw) else hass.config.path(raw))
        if os.path.commonpath([path, config_dir]) != config_dir:
            raise ServiceValidationError("Die Datei muss innerhalb von /config liegen")
        try:
            text = await hass.async_add_executor_job(_read_file, path)
            samples = parse_history_csv(text)
        except FileNotFoundError as err:
            raise ServiceValidationError(f"Datei nicht gefunden: {raw}") from err
        except (OSError, ValueError) as err:
            raise ServiceValidationError(f"CSV nicht lesbar: {err}") from err
        await _save(runtime, dev, build_profile(samples, dev.standby_w), "csv")

    async def learn_from_history(call: ServiceCall) -> None:
        runtime, dev = _resolve(hass, call.data[ATTR_DEVICE_ID])
        start, end = _local(call.data[ATTR_START]), _local(call.data[ATTR_END])
        if end <= start:
            raise ServiceValidationError("Ende muss nach dem Start liegen")
        if "recorder" not in hass.config.components:
            raise ServiceValidationError("Der Recorder ist nicht aktiv")

        from homeassistant.components.recorder import get_instance, history

        result = await get_instance(hass).async_add_executor_job(
            partial(
                history.state_changes_during_period,
                hass,
                start,
                end,
                entity_id=dev.power_entity,
                include_start_time_state=True,
            )
        )
        states = result.get(dev.power_entity.lower(), [])
        samples = [(s.last_changed, w) for s in states if (w := state_to_watts(s)) is not None]
        if not samples:
            raise ServiceValidationError(
                "Keine Verlaufsdaten im Zeitraum – evtl. schon vom Recorder gelöscht "
                "oder der Sensor ist vom Recorder ausgeschlossen. Nutze dann 'Profil einlernen'."
            )
        await _save(runtime, dev, build_profile(clamp_start(samples, start), dev.standby_w, end=end), "history")

    async_register_admin_service(hass, DOMAIN, "import_profile", import_profile, IMPORT_SCHEMA)
    async_register_admin_service(hass, DOMAIN, "learn_from_history", learn_from_history, HISTORY_SCHEMA)


