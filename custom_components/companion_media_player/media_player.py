"""Media Player entity for Companion Media Player integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from sqlalchemy import Boolean

from .artwork_resolver import ArtworkResolver
from .const import (
    CONF_SESSION_TIMEOUT,
    CONF_VOLUME_MAX,
    DEFAULT_VOLUME_MAX,
    DOMAIN,
    MEDIA_CMD_NEXT,
    MEDIA_CMD_PAUSE,
    MEDIA_CMD_PLAY,
    MEDIA_CMD_PREVIOUS,
    MEDIA_CMD_STOP,
    NOTIFY_COMMAND_MEDIA,
    NOTIFY_COMMAND_VOLUME,
    VOLUME_STREAM_MUSIC,
    NOTIFY_COMMAND_UPDATE_SENSORS,
    DEFAULT_SESSION_TIMEOUT,
)
from .device_discovery import discover_devices
from .media_session import MediaSession, MediaSessions

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
    new_entities: list[MediaPlayer] = []

    for disc in discovered:
        if disc.device.id in tracked_device_ids:
            continue

        tracked_device_ids.add(disc.device.id)
        new_entities.append(MediaPlayer(
            hass=hass,
            config_entry=config_entry,
            device=disc.device,
            media_session_entity_id=disc.media_session_entity_id,
            volume_max=volume_max,
            volume_entity_id=disc.volume_entity_id,
            session_timeout=session_timeout,
        ))
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

    entities: list[MediaPlayer] = []
    for disc in discovered:
        tracked_device_ids.add(disc.device.id)
        entities.append(MediaPlayer(
            hass=hass,
            config_entry=config_entry,
            device=disc.device,
            media_session_entity_id=disc.media_session_entity_id,
            volume_max=volume_max,
            volume_entity_id=disc.volume_entity_id,
            session_timeout=session_timeout,
        ))
        _LOGGER.info(
            "Discovered device '%s' with media session sensor %s",
            disc.device_name,
            disc.media_session_entity_id,
        )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.info("No compatible devices found yet. Will discover them dynamically.")


class MediaPlayer(MediaPlayerEntity):
    """A media player entity backed by Android Companion App media sessions."""

    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_should_poll = False

    def __init__(
            self,
            hass: HomeAssistant,
            config_entry: ConfigEntry,
            device: dr.DeviceEntry,
            media_session_entity_id: str,
            volume_max: int,
            volume_entity_id: str | None = None,
            session_timeout: int = DEFAULT_SESSION_TIMEOUT,
    ) -> None:
        """Initialize the media player."""
        self._hass = hass
        self._config_entry = config_entry
        self._sensor_entity_id = media_session_entity_id
        self._volume_max = volume_max
        self._volume_level: float | None = None
        self._volume_entity_id = volume_entity_id
        self._device = device
        self._session_timeout = session_timeout
        self._sessions: MediaSessions = MediaSessions()
        self._artwork_resolver = ArtworkResolver(hass)

        # Entity attributes
        self._attr_unique_id = f"{DOMAIN}_{device.id}"
        self._attr_name = self.device_name

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features, including VOLUME_SET only if a volume sensor exists."""
        features = (
                MediaPlayerEntityFeature.PLAY
                | MediaPlayerEntityFeature.PAUSE
                | MediaPlayerEntityFeature.STOP
                | MediaPlayerEntityFeature.NEXT_TRACK
                | MediaPlayerEntityFeature.PREVIOUS_TRACK
                | MediaPlayerEntityFeature.SELECT_SOURCE
        )
        if self._volume_entity_id is not None:
            features |= MediaPlayerEntityFeature.VOLUME_SET
        return features

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the media player."""
        session = self.selected_session
        if session is None:
            return MediaPlayerState.IDLE

        return _STATE_MAP.get(session.state, MediaPlayerState.IDLE)

    @property
    def media_title(self) -> str | None:
        """Return the title of current media."""
        session = self.selected_session
        return session.title if session else None

    @property
    def media_artist(self) -> str | None:
        """Return the artist of current media."""
        session = self.selected_session
        return session.artist if session else None

    @property
    def media_album_name(self) -> str | None:
        """Return the album name of current media."""
        session = self.selected_session
        return session.album if session else None

    @property
    def media_duration(self) -> int | None:
        """Return the duration of current media in seconds."""
        session = self.selected_session
        return session.duration / 1000 if session else None

    @property
    def media_position(self) -> int | None:
        """Return the position of current media in seconds."""
        session = self.selected_session
        return session.position / 1000 if session else None

    @property
    def media_position_updated_at(self) -> Any:
        """Return when media position was last updated."""
        session = self.selected_session
        if session and session.position is not None:
            return session.last_updated
        return None

    @property
    def app_name(self) -> str | None:
        """Return the name of the app playing media."""
        session = self.selected_session
        return session.friendly_name if session else None

    @property
    def app_id(self) -> str | None:
        """Return the package name of the app playing media."""
        session = self.selected_session
        return session.package_name if session else None

    @property
    def source(self) -> str | None:
        """Return the current source (active session friendly name)."""
        session = self.selected_session
        return session.friendly_name if session else None

    @property
    def source_list(self) -> list[str] | None:
        """Return list of friendly names of active sessions."""
        result = [session.friendly_name for session in self.active_sessions]
        return result if result else None

    @property
    def volume_level(self) -> float | None:
        """Return the volume level (0..1)."""
        return self._volume_level

    @property
    def media_content_id(self) -> str:
        """Return the media content ID."""
        session = self.selected_session
        return session.media_id if session else None

    @property
    def media_image_url(self) -> str | None:
        """Return the URL of the current media image (album art)."""
        session = self.selected_session
        return session.media_image_url if session else None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Indicate that the image URL is directly accessible from the internet."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with session details."""
        attrs: dict[str, Any] = {
            "sensor_entity_id": self._sensor_entity_id,
            "volume_entity_id": self._volume_entity_id,
            "device_name": self.device_name,
            "volume_max": self._volume_max,
        }

        # Add info about all active sessions
        active = self.active_sessions
        attrs["active_sessions_count"] = len(active)
        for session in active:
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
        if self._device is not None and self.registry_entry is not None:
            entity_registry = er.async_get(self._hass)
            entity_registry.async_update_entity(
                self.entity_id,
                device_id=self._device.id,
            )

        # Read initial sensor state if available
        current_state = self._hass.states.get(self._sensor_entity_id)
        if current_state is not None:
            self._sessions.update_from_sensor(self.device_name, current_state)
            # Resolve artwork for initially discovered sessions
            await self._async_resolve_artwork()

        # Subscribe to state changes on the media session sensor
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                [self._sensor_entity_id],
                self._async_sensor_state_changed,
            )
        )

        # Subscribe to volume sensor if available
        if self._volume_entity_id is not None:
            volume_state = self._hass.states.get(self._volume_entity_id)
            if volume_state is not None:
                self._update_volume_from_state(volume_state)

            self.async_on_remove(
                async_track_state_change_event(
                    self._hass,
                    [self._volume_entity_id],
                    self._async_volume_state_changed,
                )
            )
            _LOGGER.debug(
                "Tracking volume sensor %s for %s",
                self._volume_entity_id,
                self.device_name,
            )

        # Periodic cleanup of stale sessions
        self.async_on_remove(
            async_track_time_interval(
                self._hass,
                self._async_cleanup_stale_sessions,
                _CLEANUP_INTERVAL,
            )
        )

        _LOGGER.info(
            "Companion Media Player for %s initialized, tracking %s (volume sensor: %s)",
            self.device_name,
            self._sensor_entity_id,
            self._volume_entity_id or "none",
        )

    @callback
    def _async_sensor_state_changed(self, event: Event[EventStateChangedData]) -> Any:
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

        self._sessions.update_from_sensor(self.device_name, new_state)
        self.async_write_ha_state()

        # Resolve artwork asynchronously (non-blocking)
        self._hass.async_create_task(self._async_resolve_artwork())

    @callback
    def _async_volume_state_changed(self, event: Event[EventStateChangedData]) -> Any:
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
        removed = self._sessions.cleanup_stale(self.device_name, self.session_timeout)
        if removed:
            _LOGGER.debug(
                "Cleaned up stale sessions for %s: %s",
                self.device_name,
                removed,
            )
            self.async_write_ha_state()

    # --- Artwork Resolution ---

    async def _async_resolve_artwork(self) -> None:
        """Resolve artwork for all active sessions and update state if changed."""
        changed = False
        for session in self.active_sessions:
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
        """Set volume level (0...1 mapped to 0...volume_max)."""
        if self._volume_entity_id is None:
            _LOGGER.warning(
                "Cannot set volume: no volume sensor available for %s",
                self.device_name,
            )
            return

        android_volume = round(volume * self._volume_max)
        android_volume = max(0, min(android_volume, self._volume_max))

        try:
            await self._async_send_notify_command(NOTIFY_COMMAND_VOLUME, {
                "media_stream": VOLUME_STREAM_MUSIC,
                "command": android_volume,
            })
            # Optimistic update; the volume sensor callback will correct this
            self._volume_level = volume
            self.async_write_ha_state()
            _LOGGER.debug(
                "Set volume to %s (android: %d) on %s",
                volume,
                android_volume,
                self.device_name,
            )
        except Exception as err:
            _LOGGER.error("Failed to set volume on %s: %s", self.device_name, err, exc_info=True)

        # Trigger sensor update for faster feedback
        await self._async_trigger_sensor_update()

    def select_source(self, source_name: str) -> bool:
        """Select a source by friendly name or package name.

        Returns True if the active source changed.
        """
        normalized = source_name.strip().casefold()

        selected = self._sessions.selected
        for session in self.active_sessions:
            friendly = session.friendly_name.strip().casefold()
            if friendly == normalized or session.package_name.strip().casefold() == normalized:
                if not selected or selected.package_name != session.package_name:
                    self._sessions.selected = session
                    return True
                return False

        available_sources = ", ".join(self.source_list)
        _LOGGER.warning(
            "Source '%s' not found in active sessions for %s. Available: %s",
            source_name,
            self.device_name,
            available_sources or "none",
        )
        return False

    async def async_select_source(self, source: str) -> None:
        """Select a media session as the active source (async path)."""
        _LOGGER.debug("async_select_source called for %s: %s", self.entity_id, source)
        changed = self.select_source(source)
        if not changed:
            return

        await self._async_resolve_artwork()
        self.async_write_ha_state()

    @property
    def device(self) -> dr.DeviceEntry:
        return self._device

    @property
    def device_name(self) -> str:
        return self.device.name

    @property
    def session_timeout(self) -> int:
        return self._session_timeout

    @property
    def sessions(self) -> list[MediaSession]:
        """Return all known sessions."""
        return self._sessions.values

    @property
    def active_sessions(self) -> list[MediaSession]:
        """Return only sessions that are still within the timeout window."""
        return self._sessions.by_is_active(self.session_timeout)

    @property
    def selected_session(self) -> MediaSession | None:
        """Return the currently selected source (package name)."""
        return self._sessions.selected

    @property
    def notify_service_name(self) -> str:
        return f"mobile_app_{self.device_name}"

    # --- Internal Helpers ---

    async def _async_send_media_command(self, command: str) -> None:
        """Send a media command to the device via notification."""
        session = self.selected_session
        if session is None:
            _LOGGER.debug(
                "Cannot send command '%s': no active session on %s. Ignoring...",
                command,
                self.device_name,
            )
            return

        try:
            await self._async_send_notify_command(NOTIFY_COMMAND_MEDIA, {
                "media_command": command,
                "media_package_name": session.package_name,
            })
            _LOGGER.debug("Sent media command '%s' to %s (package: %s)",
                          command,
                          self.device_name,
                          session.package_name,
                          )
        except Exception as err:
            _LOGGER.error("Failed to send media command '%s' to %s: %s", command, self.device_name, err, exc_info=True)

        # Trigger sensor update for faster feedback
        await self._async_trigger_sensor_update()

    async def _async_send_notify_command(
            self,
            command: str,
            data: dict | None = None,
            blocking: Boolean = True,
    ) -> None:
        payload: dict = {
            "message": command,
        }
        if data is not None:
            payload["data"] = data
        await self._hass.services.async_call("notify", self.notify_service_name, payload, blocking=blocking)

    async def _async_trigger_sensor_update(self) -> None:
        """Send command_update_sensors to get faster state feedback."""
        try:
            await self._async_send_notify_command(NOTIFY_COMMAND_UPDATE_SENSORS)
            _LOGGER.debug("Sensor update on %s successfully triggered.", self.device_name)
        except Exception as err:
            _LOGGER.debug("Failed to trigger sensor update on %s. This is not critical; ignoring... %s", self.device_name,
                          err, exc_info=True)
