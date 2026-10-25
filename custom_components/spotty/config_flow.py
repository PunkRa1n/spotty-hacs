"""Einrichtung über die Oberfläche."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_DATA_KEY,
    CONF_DEVICES,
    CONF_FINISH_BY,
    CONF_POWER_ENTITY,
    CONF_PRICE_FACTOR,
    CONF_PRICE_FIELD,
    CONF_SOURCE_TYPE,
    CONF_STANDBY_W,
    CONF_TAIL_MIN,
    CONF_TIME_FIELD,
    CONF_TOKEN_HEADER,
    DEFAULT_NAME,
    DEFAULT_STANDBY_W,
    DEFAULT_TAIL_MIN,
    DEFAULT_TOKEN_HEADER,
    DOMAIN,
    SOURCE_CUSTOM,
    SOURCE_SPOTTY,
)
from .price_source import PriceSource, PriceSourceError

_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_TEXT = TextSelector()


def _suggest(defaults: dict[str, Any], key: str) -> dict[str, Any]:
    return {"suggested_value": defaults.get(key)} if defaults.get(key) not in (None, "") else {}


def _spotty_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, DEFAULT_NAME)): _TEXT,
            vol.Required(CONF_URL, default=d.get(CONF_URL, vol.UNDEFINED)): _URL,
        }
    )


def _custom_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Strompreis")): _TEXT,
            vol.Required(CONF_URL, default=d.get(CONF_URL, vol.UNDEFINED)): _URL,
            vol.Optional(CONF_TOKEN, description=_suggest(d, CONF_TOKEN)): _PASSWORD,
            vol.Optional(CONF_TOKEN_HEADER, default=d.get(CONF_TOKEN_HEADER, DEFAULT_TOKEN_HEADER)): _TEXT,
            vol.Optional(CONF_DATA_KEY, description=_suggest(d, CONF_DATA_KEY)): _TEXT,
            vol.Optional(CONF_TIME_FIELD, description=_suggest(d, CONF_TIME_FIELD)): _TEXT,
            vol.Optional(CONF_PRICE_FIELD, description=_suggest(d, CONF_PRICE_FIELD)): _TEXT,
            vol.Required(CONF_PRICE_FACTOR, default=d.get(CONF_PRICE_FACTOR, 1.0)): NumberSelector(
                NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
        }
    )


def _build_data(source_type: str, user_input: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in user_input.items() if k != CONF_NAME and v not in (None, "")}
    data[CONF_SOURCE_TYPE] = source_type
    if source_type == SOURCE_SPOTTY:
        data.update({CONF_TIME_FIELD: "from", CONF_PRICE_FIELD: "price", CONF_PRICE_FACTOR: 1.0})
    return data


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    try:
        slots = await PriceSource(hass, data).async_fetch()
    except PriceSourceError as err:
        return {"base": "cannot_connect" if err.kind == "connect" else "invalid_format"}
    return {} if slots else {"base": "no_data"}


def _unique_id(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


class SpottyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[SOURCE_SPOTTY, SOURCE_CUSTOM])

    async def async_step_spotty(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source_step(SOURCE_SPOTTY, user_input)

    async def async_step_custom(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source_step(SOURCE_CUSTOM, user_input)

    async def _async_source_step(self, source: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        schema = _spotty_schema if source == SOURCE_SPOTTY else _custom_schema
        if user_input is not None:
            data = _build_data(source, user_input)
            await self.async_set_unique_id(_unique_id(data[CONF_URL]))
            self._abort_if_unique_id_configured()
            errors = await _validate(self.hass, data)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        return self.async_show_form(step_id=source, data_schema=schema(user_input or {}), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """URL/Token ändern, ohne Geräte und gelernte Profile zu verlieren."""
        entry = self._get_reconfigure_entry()
        source = entry.data.get(CONF_SOURCE_TYPE, SOURCE_SPOTTY)
        schema = _spotty_schema if source == SOURCE_SPOTTY else _custom_schema
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _build_data(source, user_input)
            errors = await _validate(self.hass, data)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, unique_id=_unique_id(data[CONF_URL]), title=user_input[CONF_NAME], data=data
                )
        defaults = user_input or {**entry.data, CONF_NAME: entry.title}
        return self.async_show_form(step_id="reconfigure", data_schema=schema(defaults), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> SpottyOptionsFlow:
        return SpottyOptionsFlow()


def _device_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, vol.UNDEFINED)): _TEXT,
            vol.Required(CONF_POWER_ENTITY, default=d.get(CONF_POWER_ENTITY, vol.UNDEFINED)): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.POWER)
            ),
            vol.Required(CONF_STANDBY_W, default=d.get(CONF_STANDBY_W, DEFAULT_STANDBY_W)): NumberSelector(
                NumberSelectorConfig(min=0, max=500, step=0.5, unit_of_measurement="W", mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_TAIL_MIN, default=d.get(CONF_TAIL_MIN, DEFAULT_TAIL_MIN)): NumberSelector(
                NumberSelectorConfig(min=1, max=240, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_FINISH_BY, description=_suggest(d, CONF_FINISH_BY)): TimeSelector(),
        }
    )


class SpottyOptionsFlow(OptionsFlow):
    """Geräte hinzufügen, bearbeiten, entfernen."""

    def __init__(self) -> None:
        self._devices: dict[str, dict[str, Any]] | None = None
        self._edit_key: str | None = None

    @property
    def devices(self) -> dict[str, dict[str, Any]]:
        if self._devices is None:
            self._devices = {k: dict(v) for k, v in self.config_entry.options.get(CONF_DEVICES, {}).items()}
        return self._devices

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, CONF_DEVICES: self.devices})

    def _choices(self) -> list[SelectOptionDict]:
        return [SelectOptionDict(value=k, label=v[CONF_NAME]) for k, v in self.devices.items()]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = ["add_device"]
        if self.devices:
            options += ["edit_device", "remove_device"]
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_add_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = slugify(user_input[CONF_NAME])
            if not key:
                errors[CONF_NAME] = "invalid_name"
            elif key in self.devices:
                errors[CONF_NAME] = "name_exists"
            else:
                self.devices[key] = _clean(user_input)
                return self._save()
        return self.async_show_form(step_id="add_device", data_schema=_device_schema(user_input or {}), errors=errors)

    async def async_step_edit_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_key = user_input["device"]
            return await self.async_step_device_form()
        schema = vol.Schema({vol.Required("device"): SelectSelector(SelectSelectorConfig(options=self._choices()))})
        return self.async_show_form(step_id="edit_device", data_schema=schema)

    async def async_step_device_form(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._edit_key is not None
        if user_input is not None:
            # Der Schlüssel bleibt gleich, damit Profil und entity_ids erhalten bleiben
            self.devices[self._edit_key] = _clean(user_input)
            return self._save()
        return self.async_show_form(
            step_id="device_form",
            data_schema=_device_schema(self.devices[self._edit_key]),
            description_placeholders={"name": self.devices[self._edit_key][CONF_NAME]},
        )

    async def async_step_remove_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            for key in user_input["devices"]:
                self.devices.pop(key, None)
            return self._save()
        schema = vol.Schema(
            {vol.Required("devices"): SelectSelector(SelectSelectorConfig(options=self._choices(), multiple=True))}
        )
        return self.async_show_form(step_id="remove_device", data_schema=schema)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in user_input.items() if v not in (None, "")}
    data[CONF_TAIL_MIN] = int(data.get(CONF_TAIL_MIN, DEFAULT_TAIL_MIN))
    return data
