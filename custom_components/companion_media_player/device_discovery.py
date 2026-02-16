from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    MEDIA_SESSION_SENSOR_SUFFIX,
    VOLUME_LEVEL_MUSIC_SENSOR_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DiscoveredDevice:
    """A discovered mobile_app device with its media session sensor."""

    device: dr.DeviceEntry
    media_session_entity_id: str
    volume_entity_id: str | None = None

    @property
    def device_name(self) -> str:
        return self.device.name or self.device.id


def discover_devices(hass: HomeAssistant) -> list[DiscoveredDevice]:
    """Discover all mobile_app devices that have a media_session sensor."""

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    result: list[DiscoveredDevice] = []
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
            _LOGGER.warning(
                "Found entity %s with device_id %s, but device does not exist.",
                entity.entity_id,
                entity.device_id,
            )
            continue

        # Look for a volume_level_music sensor on the same device
        volume_entity_id = _find_volume_sensor(entity_registry, entity.device_id)

        device_name = device.name_by_user or device.name or device.id
        result.append(DiscoveredDevice(
            device=device,
            media_session_entity_id=entity.entity_id,
            volume_entity_id=volume_entity_id,
        ))

    return result


def _find_volume_sensor(
        entity_registry: er.EntityRegistry,
        device_id: str,
) -> str | None:
    """Find the volume_level_music sensor entity on the given device."""
    for entity in entity_registry.entities.values():
        if entity.device_id != device_id:
            continue
        if entity.domain != "sensor":
            continue
        if entity.unique_id.endswith(VOLUME_LEVEL_MUSIC_SENSOR_SUFFIX):
            return entity.entity_id
    return None
