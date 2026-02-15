"""Config flow for Companion Media Player integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_DEVICE_ID,
    CONF_SESSION_TIMEOUT,
    CONF_VOLUME_MAX,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_VOLUME_MAX,
    DOMAIN,
    MEDIA_SESSION_SENSOR_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class Device:
    device_id: str
    device_name: str
    media_session_entity_id: str
    media_session_entity_name: str


def _find_possible_devices(hass) -> dict[str, str]:
    """Find devices that can be possibly be used."""

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    result: dict[str, str] = {}
    for entity in entity_registry.entities.values():
        if entity.domain != "sensor":
            continue
        if not entity.unique_id.endswith(MEDIA_SESSION_SENSOR_SUFFIX):
            continue
        if entity.entity_id is None:
            continue
        if entity.device_id is None:
            continue
        device = device_registry.async_get(entity.device_id)
        if device is None:
            _LOGGER.warning("Found entity %s that has a registered device with ID %s, but this device does not exist.",
                            entity.entity_id, entity.device_id)
            continue
        result[device.id] = device.name_by_user or device.name or device.id

    return result


class CompanionMediaPlayerConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Companion Media Player."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step where user selects a device."""
        errors: dict[str, str] = {}

        # Find all media session sensors
        all_devices = _find_possible_devices(self.hass)

        if not all_devices:
            return self.async_abort(reason="no_sensors_found")

        # Filter out already-configured sensors
        already_configured_device_ids: set[str] = set()
        for entry in self._async_current_entries():
            already_configured_device_ids.add(entry.data.get(CONF_DEVICE_ID, ""))

        unconfigured_devices = {
            eid: name
            for eid, name in all_devices.items()
            if eid not in already_configured_device_ids
        }

        if not unconfigured_devices:
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=unconfigured_devices[device_id],
                data={
                    CONF_DEVICE_ID: device_id,
                },
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): vol.In(
                    unconfigured_devices
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
            config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow handler."""
        return CompanionMediaPlayerOptionsFlow(config_entry)


class CompanionMediaPlayerOptionsFlow(OptionsFlow):
    """Handle options flow for Companion Media Player."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_timeout = self.config_entry.options.get(
            CONF_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT
        )
        current_volume_max = self.config_entry.options.get(
            CONF_VOLUME_MAX, DEFAULT_VOLUME_MAX
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SESSION_TIMEOUT,
                        default=current_timeout,
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                    vol.Optional(
                        CONF_VOLUME_MAX,
                        default=current_volume_max,
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                }
            ),
        )
