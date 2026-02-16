"""The Companion Media Player integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, MEDIA_SESSION_SENSOR_SUFFIX

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Companion Media Player from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for entity registry changes (new/removed media session sensors)
    @callback
    def _async_entity_registry_updated(event: Event) -> None:
        """Handle entity registry updates to discover or remove devices."""
        action = event.data.get("action")
        entity_id = event.data.get("entity_id", "")

        if action == "create":
            _handle_entity_created(hass, entry, entity_id)
        elif action == "remove":
            _handle_entity_removed(hass, entry, entity_id)

    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            _async_entity_registry_updated,
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


@callback
def _handle_entity_created(
        hass: HomeAssistant, entry: ConfigEntry, entity_id: str
) -> None:
    """Handle a new entity being registered — check if it's a media session sensor."""
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(entity_id)

    if entity_entry is None:
        return
    if entity_entry.domain != "sensor":
        return
    if not entity_entry.unique_id.endswith(MEDIA_SESSION_SENSOR_SUFFIX):
        return

    _LOGGER.info(
        "New media session sensor discovered: %s. Checking for new devices...",
        entity_id,
    )

    from .media_player import async_discover_new_devices

    async_discover_new_devices(hass, entry)


@callback
def _handle_entity_removed(
        hass: HomeAssistant, entry: ConfigEntry, entity_id: str
) -> None:
    """Handle an entity being removed — clean up our entity if its sensor is gone."""
    # We can't look up the removed entity in the registry (it's already gone),
    # so we run a full cleanup to remove any of our entities whose source
    # device/sensor no longer exists.
    from .media_player import async_cleanup_removed_devices

    async_cleanup_removed_devices(hass, entry)


async def _async_update_listener(
        hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
