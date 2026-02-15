"""Media Player entity for Companion Media Player integration."""

from __future__ import annotations

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
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_ID,
    CONF_MEDIA_SESSION_ENTITY,
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
    VOLUME_STREAM_MUSIC,
)
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

from homeassistant.helpers import device_registry as dr, entity_registry as er

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Companion Media Player from a config entry."""

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    device_id = config_entry.data.get(CONF_DEVICE_ID)
    device = device_registry.async_get(device_id)
    if device is None:
        _LOGGER.warning("Device with ID %s was configured but does not exist. Maybe, it was removed?", device_id)
        return None

    media_session_entity: RegistryEntry | None = None
    last_notification_entity: RegistryEntry | None = None
    for entity in entity_registry.entities.values():
        if entity.domain != "sensor":
            continue
        if entity.entity_id is None:
            continue
        if entity.device_id is None or entity.device_id != device_id:
            continue

        if entity.unique_id.endswith(MEDIA_SESSION_SENSOR_SUFFIX):
            media_session_entity = entity
            continue
        if entity.unique_id.endswith(LAST_NOTIFICATION_SENSOR_SUFFIX):
            last_notification_entity = entity
            continue

    if media_session_entity is None:
        _LOGGER.info("Device with ID %s has currently no active media session sensor. Ignoring...", device_id)

    session_timeout = config_entry.options.get(
        CONF_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT
    )
    volume_max = config_entry.options.get(CONF_VOLUME_MAX, DEFAULT_VOLUME_MAX)

    manager = MediaSessionManager(
        hass=hass,
        device_name=device.name_by_user or device.name or device.id,
        session_timeout=session_timeout,
    )

    entity = CompanionMediaPlayer(
        hass=hass,
        config_entry=config_entry,
        sensor_entity_id=media_session_entity.entity_id,
        manager=manager,
        volume_max=volume_max,
        source_device=device,
    )

    # Store manager reference for potential access from other parts
    hass.data[DOMAIN][config_entry.entry_id]["manager"] = manager
    hass.data[DOMAIN][config_entry.entry_id]["entity"] = entity

    async_add_entities([entity])


class CompanionMediaPlayer(MediaPlayerEntity):
    """A media player entity backed by Android Companion App media sessions."""

    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        sensor_entity_id: str,
        manager: MediaSessionManager,
        volume_max: int,
        source_device: dr.DeviceEntry | None = None,
    ) -> None:
        """Initialize the media player."""
        self.hass = hass
        self._config_entry = config_entry
        self._sensor_entity_id = sensor_entity_id
        self._manager = manager
        self._volume_max = volume_max
        self._volume_level: float | None = None
        self._source_device = source_device

        # Entity attributes
        self._attr_unique_id = f"{DOMAIN}_{source_device.id}"
        self._attr_name = manager.device_name

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info to link this entity to the source device."""
        if self._source_device is None:
            return None
        return DeviceInfo(
            identifiers=self._source_device.identifiers,
        )

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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with session details."""
        attrs: dict[str, Any] = {
            "sensor_entity_id": self._sensor_entity_id,
            "device_name": self._manager.device_name,
            "notify_service": self._manager.notify_service_target,
            "volume_max": self._volume_max,
        }

        # Add info about all active sessions
        active = self._manager.active_sessions
        attrs["active_sessions_count"] = len(active)
        for pkg, session in active.items():
            prefix = f"session_{session.friendly_name}"
            attrs[f"{prefix}_package"] = pkg
            attrs[f"{prefix}_state"] = session.state
            attrs[f"{prefix}_title"] = session.title
            attrs[f"{prefix}_artist"] = session.artist

        return attrs

    # --- Lifecycle ---

    async def async_added_to_hass(self) -> None:
        """Subscribe to sensor state changes when added to HA."""
        await super().async_added_to_hass()

        # Read initial sensor state if available
        current_state = self.hass.states.get(self._sensor_entity_id)
        if current_state is not None:
            self._manager.update_from_sensor(current_state)

        # Subscribe to state changes on the media session sensor
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._sensor_entity_id],
                self._async_sensor_state_changed,
            )
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
            "Companion Media Player for %s initialized, tracking %s",
            self._manager.device_name,
            self._sensor_entity_id,
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
