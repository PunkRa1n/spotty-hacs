"""Live-Einlernen: zeichnet einen Gerätelauf direkt mit, ganz ohne Recorder."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.components import persistent_notification
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfPower
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LEARN_MAX_DURATION, LEARN_WAIT_MAX
from .coordinator import DeviceConfig, SpottyCoordinator
from .profile import build_profile, energy_kwh

_LOGGER = logging.getLogger(__name__)
_CHECK_INTERVAL = timedelta(seconds=30)


def state_to_watts(state: State | None) -> float | None:
    """Zustand in W umrechnen; kW-Sensoren werden erkannt."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    if state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfPower.KILO_WATT:
        value *= 1000
    return value


class ProfileLearner:
    def __init__(self, hass: HomeAssistant, coordinator: SpottyCoordinator, device: DeviceConfig) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.device = device
        self.active = False
        self._samples: list[tuple[datetime, float]] = []
        self._started_at: datetime | None = None
        self._running_since: datetime | None = None
        self._below_since: datetime | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []

    # --- Beobachter (Switch, Status-Sensor) ---
    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def async_notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # --- Ablauf ---
    @callback
    def async_start(self) -> None:
        if self.active:
            return
        self.active = True
        self._samples = []
        self._started_at = dt_util.utcnow()
        self._running_since = self._below_since = None
        self._record(self._started_at, state_to_watts(self.hass.states.get(self.device.power_entity)))
        self._unsubs = [
            async_track_state_change_event(self.hass, [self.device.power_entity], self._on_change),
            async_track_time_interval(self.hass, self._check, _CHECK_INTERVAL),
        ]
        self._notify_user(f"Einlernen läuft. Starte jetzt **{self.device.name}**.")
        self.async_notify()

    @callback
    def async_cancel(self) -> None:
        """Abbrechen ohne Speichern (z. B. beim Entladen der Integration)."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        if self.active:
            self.active = False
            self.async_notify()

    async def async_finish(self) -> None:
        """Aufzeichnung beenden und Profil speichern, falls ein Lauf erkannt wurde."""
        if not self.active:
            return
        end = dt_util.utcnow()
        samples = list(self._samples)
        self.async_cancel()

        watts = build_profile(samples, self.device.standby_w, end=end)
        if not watts:
            self._notify_user(
                f"Kein Lauf über {self.device.standby_w:g} W erkannt – bisheriges Profil bleibt."
            )
            return
        await self.coordinator.store.async_set(self.device.key, watts, "live", self.device.standby_w)
        self._notify_user(
            f"Profil gespeichert: {len(watts)} min, {energy_kwh(watts):.3f} kWh, "
            f"Spitze {max(watts):.0f} W."
        )
        self.async_notify()
        await self.coordinator.async_recompute()

    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is not None:
            self._record(new.last_updated, state_to_watts(new))

    def _record(self, moment: datetime, watts: float | None) -> None:
        if watts is None:
            return
        self._samples.append((moment, watts))
        if watts > self.device.standby_w:
            self._running_since = self._running_since or moment
            self._below_since = None
        elif self._running_since and self._below_since is None:
            self._below_since = moment

    @callback
    def _check(self, now: datetime) -> None:
        assert self._started_at is not None
        if self._running_since is None:
            if now - self._started_at > LEARN_WAIT_MAX:
                self._notify_user("Gerät wurde nicht gestartet – Einlernen abgebrochen.")
                self.async_cancel()
            return
        tail = timedelta(minutes=self.device.tail_min)
        if (self._below_since and now - self._below_since >= tail) or (
            now - self._started_at > LEARN_MAX_DURATION
        ):
            self.hass.async_create_task(self.async_finish())

    def _notify_user(self, message: str) -> None:
        persistent_notification.async_create(
            self.hass,
            message,
            title=f"Lastprofil {self.device.name}",
            notification_id=f"{DOMAIN}_{self.coordinator.config_entry.entry_id}_{self.device.key}",
        )
