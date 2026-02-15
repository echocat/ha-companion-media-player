"""Media Player entity for Companion Media Player integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SESSION_TIMEOUT,
    CONF_VOLUME_MAX,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_VOLUME_MAX,
    DOMAIN,
    MEDIA_CMD_NEXT,
    MEDIA_CMD_PAUSE,
    MEDIA_CMD_PLAY,
    MEDIA_CMD_PREVIOUS,
    MEDIA_CMD_STOP,
    MEDIA_SESSION_SENSOR_SUFFIX,
    LAST_NOTIFICATION_SENSOR_SUFFIX,
    NOTIFY_COMMAND_MEDIA,
    NOTIFY_COMMAND_UPDATE_SENSORS,
    NOTIFY_COMMAND_VOLUME,
    VOLUME_LEVEL_MUSIC_SENSOR_SUFFIX,
    VOLUME_STREAM_MUSIC,
)
from .artwork import ArtworkResolver
from .coordinator import MediaSessionManager

_LOGGER = logging.getLogger(__name__)

# Cleanup interval for stale sessions
_CLEANUP_INTERVAL = timedelta(minutes=5)

# Mapping from companion app sensor states to HA MediaPlayerState
_STATE_MAP: dict[str, MediaPlayerState] = {
    "Playing": MediaPlayerState.PLAYING,
    "playing": MediaPlayerState.PLAYING,
    "Paused": MediaPlayerState.PAUSED,
    "paused": MediaPlayerState.PAUSED,
    "Stopped": MediaPlayerState.IDLE,
    "stopped": MediaPlayerState.IDLE,
    "Buffering": MediaPlayerState.BUFFERING,
    "buffering": MediaPlayerState.BUFFERING,
    "Error": MediaPlayerState.IDLE,
    "error": MediaPlayerState.IDLE,
    "idle": MediaPlayerState.IDLE,
    "Idle": MediaPlayerState.IDLE,
}


@dataclass
class DiscoveredDevice:
    """A discovered mobile_app device with its media session sensor."""

    device: dr.DeviceEntry
    device_name: str
    media_session_entity_id: str
    volume_entity_id: str | None = None


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
            device_name=device_name,
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


def _cleanup_orphaned_entities(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> None:
    """Remove entities from our integration whose source device/sensor no longer exists."""

    entity_registry = er.async_get(hass)
    discovered = discover_devices(hass)
    valid_device_ids = {disc.device.id for disc in discovered}

    # Find all entities belonging to our config entry
    our_entities = [
        entry
        for entry in entity_registry.entities.values()
        if entry.config_entry_id == config_entry.entry_id
    ]

    for entity_entry in our_entities:
        # Our unique_id format: "{DOMAIN}_{device_id}"
        prefix = f"{DOMAIN}_"
        if not entity_entry.unique_id.startswith(prefix):
            continue

        device_id = entity_entry.unique_id.removeprefix(prefix)
        if device_id not in valid_device_ids:
            _LOGGER.info(
                "Removing orphaned entity %s (device %s no longer has a media session sensor)",
                entity_entry.entity_id,
                device_id,
            )
            entity_registry.async_remove(entity_entry.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Companion Media Player entities for all discovered devices."""

    session_timeout = config_entry.options.get(
        CONF_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT
    )
    volume_max = config_entry.options.get(CONF_VOLUME_MAX, DEFAULT_VOLUME_MAX)

    # Track which device IDs already have an entity
    tracked_device_ids: set[str] = set()

    # Store references for dynamic discovery
    hass.data[DOMAIN][config_entry.entry_id]["async_add_entities"] = async_add_entities
    hass.data[DOMAIN][config_entry.entry_id]["tracked_device_ids"] = tracked_device_ids
    hass.data[DOMAIN][config_entry.entry_id]["config_entry"] = config_entry

    # Remove orphaned entities whose source device/sensor no longer exists
    _cleanup_orphaned_entities(hass, config_entry)

    # Discover all currently available devices
    discovered = discover_devices(hass)

    entities: list[CompanionMediaPlayer] = []
    for disc in discovered:
        entity = _create_entity(
            hass=hass,
            config_entry=config_entry,
            disc=disc,
            session_timeout=session_timeout,
            volume_max=volume_max,
        )
        tracked_device_ids.add(disc.device.id)
        entities.append(entity)
        _LOGGER.info(
            "Discovered device '%s' with media session sensor %s",
            disc.device_name,
            disc.media_session_entity_id,
        )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.info("No compatible devices found yet. Will discover them dynamically.")


def _create_entity(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    disc: DiscoveredDevice,
    session_timeout: int,
    volume_max: int,
) -> CompanionMediaPlayer:
    """Create a CompanionMediaPlayer entity for a discovered device."""

    manager = MediaSessionManager(
        hass=hass,
        device_name=disc.device_name,
        session_timeout=session_timeout,
    )

    return CompanionMediaPlayer(
        hass=hass,
        config_entry=config_entry,
        sensor_entity_id=disc.media_session_entity_id,
        manager=manager,
        volume_max=volume_max,
        source_device=disc.device,
        volume_entity_id=disc.volume_entity_id,
    )


@callback
def async_discover_new_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> None:
    """Check for new devices and add entities for them."""

    entry_data = hass.data[DOMAIN].get(config_entry.entry_id)
    if entry_data is None:
        return

    async_add_entities = entry_data.get("async_add_entities")
    tracked_device_ids: set[str] = entry_data.get("tracked_device_ids", set())

    if async_add_entities is None:
        return

    session_timeout = config_entry.options.get(
        CONF_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT
    )
    volume_max = config_entry.options.get(CONF_VOLUME_MAX, DEFAULT_VOLUME_MAX)

    discovered = discover_devices(hass)
    new_entities: list[CompanionMediaPlayer] = []

    for disc in discovered:
        if disc.device.id in tracked_device_ids:
            continue

        entity = _create_entity(
            hass=hass,
            config_entry=config_entry,
            disc=disc,
            session_timeout=session_timeout,
            volume_max=volume_max,
        )
        tracked_device_ids.add(disc.device.id)
        new_entities.append(entity)
        _LOGGER.info(
            "Dynamically discovered new device '%s' with media session sensor %s",
            disc.device_name,
            disc.media_session_entity_id,
        )

    if new_entities:
        async_add_entities(new_entities)


@callback
def async_cleanup_removed_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> None:
    """Remove entities whose source device/sensor was removed at runtime."""

    entry_data = hass.data[DOMAIN].get(config_entry.entry_id)
    if entry_data is None:
        return

    tracked_device_ids: set[str] = entry_data.get("tracked_device_ids", set())

    entity_registry = er.async_get(hass)
    discovered = discover_devices(hass)
    valid_device_ids = {disc.device.id for disc in discovered}

    # Find our entities that no longer have a valid source device/sensor
    our_entities = [
        entry
        for entry in entity_registry.entities.values()
        if entry.config_entry_id == config_entry.entry_id
    ]

    for entity_entry in our_entities:
        prefix = f"{DOMAIN}_"
        if not entity_entry.unique_id.startswith(prefix):
            continue

        device_id = entity_entry.unique_id.removeprefix(prefix)
        if device_id not in valid_device_ids:
            _LOGGER.info(
                "Removing entity %s (device %s no longer has a media session sensor)",
                entity_entry.entity_id,
                device_id,
            )
            entity_registry.async_remove(entity_entry.entity_id)
            tracked_device_ids.discard(device_id)


class CompanionMediaPlayer(MediaPlayerEntity):
    """A media player entity backed by Android Companion App media sessions."""

    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_should_poll = False

    _BASE_FEATURES = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        sensor_entity_id: str,
        manager: MediaSessionManager,
        volume_max: int,
        source_device: dr.DeviceEntry,
        volume_entity_id: str | None = None,
    ) -> None:
        """Initialize the media player."""
        self.hass = hass
        self._config_entry = config_entry
        self._sensor_entity_id = sensor_entity_id
        self._manager = manager
        self._volume_max = volume_max
        self._volume_level: float | None = None
        self._source_device = source_device
        self._volume_entity_id = volume_entity_id

        self._artwork_resolver = ArtworkResolver(hass)

        # Entity attributes
        self._attr_unique_id = f"{DOMAIN}_{source_device.id}"
        self._attr_name = manager.device_name

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features, including VOLUME_SET only if a volume sensor exists."""
        features = self._BASE_FEATURES
        if self._volume_entity_id is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET
        return features

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the media player."""
        session = self._manager.active_session
        if session is None:
            return MediaPlayerState.IDLE

        return _STATE_MAP.get(session.state, MediaPlayerState.IDLE)

    @property
    def media_title(self) -> str | None:
        """Return the title of current media."""
        session = self._manager.active_session
        return session.title if session else None

    @property
    def media_artist(self) -> str | None:
        """Return the artist of current media."""
        session = self._manager.active_session
        return session.artist if session else None

    @property
    def media_album_name(self) -> str | None:
        """Return the album name of current media."""
        session = self._manager.active_session
        return session.album if session else None

    @property
    def media_duration(self) -> int | None:
        """Return the duration of current media in seconds."""
        session = self._manager.active_session
        return session.duration / 1000 if session else None

    @property
    def media_position(self) -> int | None:
        """Return the position of current media in seconds."""
        session = self._manager.active_session
        return session.position / 1000 if session else None

    @property
    def media_position_updated_at(self) -> Any:
        """Return when media position was last updated."""
        session = self._manager.active_session
        if session and session.position is not None:
            return session.last_updated
        return None

    @property
    def app_name(self) -> str | None:
        """Return the name of the app playing media."""
        session = self._manager.active_session
        return session.friendly_name if session else None

    @property
    def app_id(self) -> str | None:
        """Return the package name of the app playing media."""
        session = self._manager.active_session
        return session.package_name if session else None

    @property
    def source(self) -> str | None:
        """Return the current source (active session friendly name)."""
        session = self._manager.active_session
        return session.friendly_name if session else None

    @property
    def source_list(self) -> list[str] | None:
        """Return the list of available sources (active sessions)."""
        sources = self._manager.source_list
        return sources if sources else None

    @property
    def volume_level(self) -> float | None:
        """Return the volume level (0..1)."""
        return self._volume_level

    @property
    def media_image_url(self) -> str | None:
        """Return the URL of the current media image (album art)."""
        session = self._manager.active_session
        return session.media_image_url if session else None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Indicate that the image URL is directly accessible from the internet."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with session details."""
        session = self._manager.active_session
        attrs: dict[str, Any] = {
            "media_id": session.media_id if session else None,
            "sensor_entity_id": self._sensor_entity_id,
            "volume_entity_id": self._volume_entity_id,
            "device_name": self._manager.device_name,
            "notify_service": self._manager.notify_service_target,
            "volume_max": self._volume_max,
        }

        # Add info about all active sessions
        active = self._manager.active_sessions
        attrs["active_sessions_count"] = len(active)
        for pkg, session in active.items():
            prefix = f"session_{session.package_name}"
            attrs[f"{prefix}_media_id"] = session.media_id
            attrs[f"{prefix}_state"] = session.state
            attrs[f"{prefix}_title"] = session.title
            attrs[f"{prefix}_artist"] = session.artist
            attrs[f"{prefix}_album"] = session.album

        return attrs

    # --- Lifecycle ---

    async def async_added_to_hass(self) -> None:
        """Subscribe to sensor state changes when added to HA."""
        await super().async_added_to_hass()

        # Link this entity to the source device without registering our
        # config entry on it (which would create a duplicate device entry).
        if self._source_device is not None and self.registry_entry is not None:
            entity_registry = er.async_get(self.hass)
            entity_registry.async_update_entity(
                self.entity_id,
                device_id=self._source_device.id,
            )

        # Read initial sensor state if available
        current_state = self.hass.states.get(self._sensor_entity_id)
        if current_state is not None:
            self._manager.update_from_sensor(current_state)
            # Resolve artwork for initially discovered sessions
            await self._async_resolve_artwork()

        # Subscribe to state changes on the media session sensor
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._sensor_entity_id],
                self._async_sensor_state_changed,
            )
        )

        # Subscribe to volume sensor if available
        if self._volume_entity_id is not None:
            volume_state = self.hass.states.get(self._volume_entity_id)
            if volume_state is not None:
                self._update_volume_from_state(volume_state)

            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._volume_entity_id],
                    self._async_volume_state_changed,
                )
            )
            _LOGGER.debug(
                "Tracking volume sensor %s for %s",
                self._volume_entity_id,
                self._manager.device_name,
            )

        # Periodic cleanup of stale sessions
        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._async_cleanup_stale_sessions,
                _CLEANUP_INTERVAL,
            )
        )

        _LOGGER.info(
            "Companion Media Player for %s initialized, tracking %s (volume sensor: %s)",
            self._manager.device_name,
            self._sensor_entity_id,
            self._volume_entity_id or "none",
        )

    @callback
    def _async_sensor_state_changed(self, event: Event) -> None:
        """Handle state changes from the media session sensor."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        _LOGGER.debug(
            "Sensor state changed for %s: %s (attrs: %s)",
            self._sensor_entity_id,
            new_state.state,
            new_state.attributes,
        )

        self._manager.update_from_sensor(new_state)
        self.async_write_ha_state()

        # Resolve artwork asynchronously (non-blocking)
        self.hass.async_create_task(self._async_resolve_artwork())

    @callback
    def _async_volume_state_changed(self, event: Event) -> None:
        """Handle state changes from the volume level sensor."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        _LOGGER.debug(
            "Volume sensor state changed for %s: %s",
            self._volume_entity_id,
            new_state.state,
        )

        self._update_volume_from_state(new_state)
        self.async_write_ha_state()

    def _update_volume_from_state(self, state: Any) -> None:
        """Parse the volume sensor state and update internal volume level."""
        if state is None or state.state in ("unavailable", "unknown"):
            self._volume_level = None
            return

        try:
            android_volume = int(state.state)
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Could not parse volume state '%s' from %s",
                state.state,
                self._volume_entity_id,
            )
            self._volume_level = None
            return

        if self._volume_max > 0:
            self._volume_level = android_volume / self._volume_max
        else:
            self._volume_level = None

    @callback
    def _async_cleanup_stale_sessions(self, _now: Any = None) -> None:
        """Periodically clean up stale sessions."""
        removed = self._manager.cleanup_stale_sessions()
        if removed:
            _LOGGER.debug(
                "Cleaned up stale sessions for %s: %s",
                self._manager.device_name,
                removed,
            )
            self.async_write_ha_state()

    # --- Artwork Resolution ---

    async def _async_resolve_artwork(self) -> None:
        """Resolve artwork for all active sessions and update state if changed."""
        changed = False
        for session in self._manager.active_sessions.values():
            image_url = await self._artwork_resolver.resolve(
                session.media_id, session.package_name
            )
            if session.media_image_url != image_url:
                session.media_image_url = image_url
                changed = True

        if changed:
            self.async_write_ha_state()

    # --- Media Controls ---

    async def async_media_play(self) -> None:
        """Send play command."""
        await self._async_send_media_command(MEDIA_CMD_PLAY)

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self._async_send_media_command(MEDIA_CMD_PAUSE)

    async def async_media_stop(self) -> None:
        """Send stop command."""
        await self._async_send_media_command(MEDIA_CMD_STOP)

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        await self._async_send_media_command(MEDIA_CMD_NEXT)

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        await self._async_send_media_command(MEDIA_CMD_PREVIOUS)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0..1 mapped to 0..volume_max)."""
        if self._volume_entity_id is None:
            _LOGGER.warning(
                "Cannot set volume: no volume sensor available for %s",
                self._manager.device_name,
            )
            return

        android_volume = round(volume * self._volume_max)
        android_volume = max(0, min(android_volume, self._volume_max))

        service_name = self._manager.notify_service_name
        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {
                    "message": NOTIFY_COMMAND_VOLUME,
                    "data": {
                        "media_stream": VOLUME_STREAM_MUSIC,
                        "command": android_volume,
                    },
                },
                blocking=True,
            )
            # Optimistic update; the volume sensor callback will correct this
            self._volume_level = volume
            self.async_write_ha_state()
            _LOGGER.debug(
                "Set volume to %s (android: %d) on %s",
                volume,
                android_volume,
                self._manager.device_name,
            )
        except Exception:
            _LOGGER.exception(
                "Failed to set volume on %s", self._manager.device_name
            )

        # Trigger sensor update for faster feedback
        await self._async_trigger_sensor_update()

    async def async_select_source(self, source: str) -> None:
        """Select a media session as the active source."""
        self._manager.select_source(source)
        self.async_write_ha_state()

    # --- Internal Helpers ---

    async def _async_send_media_command(self, command: str) -> None:
        """Send a media command to the device via notification."""
        session = self._manager.active_session
        if session is None:
            _LOGGER.warning(
                "Cannot send command '%s': no active session on %s",
                command,
                self._manager.device_name,
            )
            return

        service_name = self._manager.notify_service_name
        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {
                    "message": NOTIFY_COMMAND_MEDIA,
                    "data": {
                        "media_command": command,
                        "media_package_name": session.package_name,
                    },
                },
                blocking=True,
            )
            _LOGGER.debug(
                "Sent media command '%s' to %s (package: %s)",
                command,
                self._manager.device_name,
                session.package_name,
            )
        except Exception:
            _LOGGER.exception(
                "Failed to send media command '%s' to %s",
                command,
                self._manager.device_name,
            )

        # Trigger sensor update for faster feedback
        await self._async_trigger_sensor_update()

    async def _async_trigger_sensor_update(self) -> None:
        """Send command_update_sensors to get faster state feedback."""
        service_name = self._manager.notify_service_name
        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {
                    "message": NOTIFY_COMMAND_UPDATE_SENSORS,
                },
                blocking=False,
            )
            _LOGGER.debug(
                "Triggered sensor update on %s", self._manager.device_name
            )
        except Exception:
            _LOGGER.debug(
                "Failed to trigger sensor update on %s (non-critical)",
                self._manager.device_name,
            )
