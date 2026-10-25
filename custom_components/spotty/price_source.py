"""Preise per HTTP abrufen (Spotty oder beliebige JSON/CSV-URL)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DATA_KEY,
    CONF_PRICE_FACTOR,
    CONF_PRICE_FIELD,
    CONF_SOURCE_TYPE,
    CONF_TIME_FIELD,
    CONF_TOKEN_HEADER,
    DEFAULT_TOKEN_HEADER,
    DOMAIN,
    SOURCE_SPOTTY,
    SPOTTY_USER_AGENT,
)
from .pricing import PriceParseError, Slot, parse_payload


class PriceSourceError(Exception):
    """Abruf oder Parsen fehlgeschlagen. kind: 'connect' oder 'format'."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class PriceSource:
    """Holt Preise von einer URL. Die URL (mit Token!) wird nie geloggt."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._hass = hass
        self._cfg = config

    @property
    def is_spotty(self) -> bool:
        return self._cfg.get(CONF_SOURCE_TYPE) == SOURCE_SPOTTY

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": SPOTTY_USER_AGENT if self.is_spotty else f"HomeAssistant-{DOMAIN}",
            "Accept": "application/json, text/csv;q=0.9, */*;q=0.5",
        }
        token = (self._cfg.get(CONF_TOKEN) or "").strip()
        if token:
            header = (self._cfg.get(CONF_TOKEN_HEADER) or DEFAULT_TOKEN_HEADER).strip()
            if header.lower() == "authorization" and " " not in token:
                token = f"Bearer {token}"
            headers[header] = token
        return headers

    async def async_fetch(self) -> list[Slot]:
        session = async_get_clientsession(self._hass)
        try:
            async with asyncio.timeout(20):
                resp = await session.get(self._cfg[CONF_URL], headers=self._headers())
                if resp.status >= 400:
                    # Bewusst ohne URL: die enthält bei Spotty den Zugangsschlüssel
                    raise PriceSourceError("connect", f"HTTP {resp.status}")
                text = await resp.text()
        except PriceSourceError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PriceSourceError("connect", type(err).__name__) from err

        try:
            return parse_payload(
                text,
                data_key=self._cfg.get(CONF_DATA_KEY) or None,
                time_field=self._cfg.get(CONF_TIME_FIELD) or None,
                price_field=self._cfg.get(CONF_PRICE_FIELD) or None,
                factor=float(self._cfg.get(CONF_PRICE_FACTOR) or 1.0),
                default_tz=dt_util.get_default_time_zone(),
            )
        except PriceParseError as err:
            raise PriceSourceError("format", str(err)) from err
