"""Config flow for Companion Media Player integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import (
    CONF_SESSION_TIMEOUT,
    CONF_VOLUME_MAX,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_VOLUME_MAX,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CompanionMediaPlayerConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Companion Media Player."""

    VERSION = 2
    MINOR_VERSION = 1

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step – just activate the integration."""

        # Only allow a single config entry for this integration
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(
                title="Companion Media Player",
                data={},
            )

        return self.async_show_form(step_id="user")

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
