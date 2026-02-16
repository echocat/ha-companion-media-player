"""Media Session Manager for tracking companion app media sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.util import dt as dt_util

from .const import (
    ENTITY_ATTR_PREFIX_ALBUM,
    ENTITY_ATTR_PREFIX_ARTIST,
    ENTITY_ATTR_PREFIX_DURATION,
    ENTITY_ATTR_PREFIX_MEDIA_ID,
    ENTITY_ATTR_PREFIX_PLAYBACK_POSITION,
    ENTITY_ATTR_PREFIX_PLAYBACK_STATE,
    ENTITY_ATTR_PREFIX_TITLE,
    DEFAULT_SESSION_TIMEOUT,
    KNOWN_APPS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class MediaSession:
    """Represents a single media session from an Android app."""

    package_name: str
    media_id: str | None = None
    state: str = "idle"
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: int | None = None
    position: int | None = None
    media_image_url: str | None = None
    last_updated: datetime = field(default_factory=dt_util.utcnow)

    @property
    def friendly_name(self) -> str:
        """Return a human-readable name for this session."""
        return KNOWN_APPS.get(self.package_name, self.package_name)

    def is_active(self, timeout_minutes: int = DEFAULT_SESSION_TIMEOUT) -> bool:
        """Check if this session is still considered active."""
        cutoff = dt_util.utcnow() - timedelta(minutes=timeout_minutes)
        return self.last_updated >= cutoff


class MediaSessionManager:
    """Manages media session state for a single Android device.

    This class caches the state of all known media sessions for a device,
    since the companion app sensor only reports state changes — we cannot
    query current state on demand.
    """

    def __init__(
            self,
            hass: HomeAssistant,
            device_name: str,
            session_timeout: int = DEFAULT_SESSION_TIMEOUT,
    ) -> None:
        """Initialize the session manager."""
        self.hass = hass
        self.device_name = device_name
        self.session_timeout = session_timeout
        self._sessions: dict[str, MediaSession] = {}
        self._active_source: str | None = None

    @property
    def sessions(self) -> dict[str, MediaSession]:
        """Return all known sessions."""
        return self._sessions

    @property
    def active_sessions(self) -> dict[str, MediaSession]:
        """Return only sessions that are still within the timeout window."""
        return {
            pkg: session
            for pkg, session in self._sessions.items()
            if session.is_active(self.session_timeout)
        }

    @property
    def active_source(self) -> str | None:
        """Return the currently selected source (package name)."""
        active = self.active_sessions
        if not active:
            return None

        # If current selection is still active, keep it
        if self._active_source and self._active_source in active:
            return self._active_source

        # Otherwise, pick the most recently updated session
        most_recent = max(active.values(), key=lambda s: s.last_updated)
        self._active_source = most_recent.package_name
        return self._active_source

    @property
    def active_session(self) -> MediaSession | None:
        """Return the currently active media session."""
        source = self.active_source
        if source is None:
            return None
        return self.active_sessions.get(source)

    @property
    def source_list(self) -> list[str]:
        """Return list of friendly names of active sessions."""
        return [
            session.friendly_name
            for session in self.active_sessions.values()
        ]

    def select_source(self, source_name: str) -> bool:
        """Select a source by friendly name or package name.

        Returns True if the active source changed.
        """
        normalized = source_name.strip().casefold()

        for pkg, session in self.active_sessions.items():
            friendly = session.friendly_name.strip().casefold()
            if friendly == normalized or pkg.strip().casefold() == normalized:
                changed = self._active_source != pkg
                self._active_source = pkg
                return changed

        available_sources = ", ".join(self.source_list)
        _LOGGER.warning(
            "Source '%s' not found in active sessions for %s. Available: %s",
            source_name,
            self.device_name,
            available_sources or "none",
        )
        return False

    @callback
    def update_from_sensor(self, new_state: State) -> None:
        """Update session data from a media session sensor state change."""

        if new_state is None or new_state.state in ("unavailable", "unknown"):
            return

        attrs = new_state.attributes
        now = dt_util.utcnow()

        known_package_names: list[str] = []
        for key, media_id in attrs.items():
            if key.startswith(ENTITY_ATTR_PREFIX_MEDIA_ID):
                package_name = key.removeprefix(ENTITY_ATTR_PREFIX_MEDIA_ID)
                state = attrs[f"{ENTITY_ATTR_PREFIX_PLAYBACK_STATE}{package_name}"]
                if state is None:
                    _LOGGER.warning("Media session of device %s is lacking required attribute %s%s; ignoring session.",
                                    self.device_name, ENTITY_ATTR_PREFIX_PLAYBACK_STATE, package_name)
                    continue
                title = attrs[f"{ENTITY_ATTR_PREFIX_TITLE}{package_name}"]
                if title is None:
                    _LOGGER.warning("Media session of device %s is lacking required attribute %s%s; ignoring session.",
                                    self.device_name, ENTITY_ATTR_PREFIX_TITLE, package_name)
                    continue
                artist = attrs[f"{ENTITY_ATTR_PREFIX_ARTIST}{package_name}"]
                album = attrs[f"{ENTITY_ATTR_PREFIX_ALBUM}{package_name}"]
                duration = _parse_int(attrs[f"{ENTITY_ATTR_PREFIX_DURATION}{package_name}"])
                position = _parse_int(attrs[f"{ENTITY_ATTR_PREFIX_PLAYBACK_POSITION}{package_name}"])
                self._add_or_update_session(
                    package_name=package_name,
                    media_id=media_id,
                    state=state,
                    title=title,
                    artist=artist,
                    album=album,
                    duration=duration,
                    position=position,
                    now=now
                )
                known_package_names.append(package_name)

        self._remove_orphan_sessions(known_package_names)

    @callback
    def update_from_notification(self, new_state: State) -> bool:
        """Update session data from a last_notification sensor state change.

        The last notification sensor fires near-instantly when a media app
        updates its notification (e.g. track change). Attributes include:
        - android.title: track name
        - android.text: artist name
        - package: app package name
        - post_time: timestamp

        Returns True if the notification was from a known media app and
        the session was updated.
        """
        if new_state is None or new_state.state in ("unavailable", "unknown"):
            return False

        attrs = new_state.attributes
        # package_name = attrs.get("package")
        #
        # if not package_name:
        #     return False
        #
        # # Only process notifications from known media apps or apps
        # # that already have an active session with us
        # is_known_media_app = package_name in KNOWN_APPS
        # has_existing_session = package_name in self._sessions
        #
        # if not is_known_media_app and not has_existing_session:
        #     return False
        #
        # title = attrs.get("android.title")
        # artist = attrs.get("android.text")
        # now = dt_util.utcnow()
        #
        # # We get title and artist from the notification, but not full
        # # playback state. If we have an existing session, keep its state;
        # # otherwise assume "Playing" since the notification just fired.
        # existing = self._sessions.get(package_name)
        # current_state = existing.state if existing else "Playing"
        #
        # self._update_session(
        #     package_name=package_name,
        #     state=current_state,
        #     title=title,
        #     artist=artist,
        #     album=None,  # not available from notification
        #     duration=None,
        #     position=None,
        #     now=now,
        # )
        #
        # _LOGGER.debug(
        #     "Updated session from notification for %s on %s: title=%s, artist=%s",
        #     package_name,
        #     self.device_name,
        #     title,
        #     artist,
        # )
        _LOGGER.debug("Received a notification with attributes: %s", attrs)

        return True

    def _add_or_update_session(
            self,
            package_name: str,
            media_id: str | None,
            state: str,
            title: str,
            artist: str | None,
            album: str | None,
            duration: int | None,
            position: int | None,
            now: datetime,
    ) -> None:
        session: MediaSession
        if package_name in self._sessions:
            session = self._sessions[package_name]
            session.media_id = media_id
            session.state = state
            session.title = title
            session.artist = artist
            session.album = album
            session.duration = duration
            session.position = position
            session.last_updated = now
            _LOGGER.debug("Updated %s on %s", session, self.device_name)
        else:
            session = MediaSession(
                package_name=package_name,
                media_id=media_id,
                state=state,
                title=title,
                artist=artist,
                album=album,
                duration=duration,
                position=position,
                last_updated=now,
            )
            self._sessions[package_name] = session
            _LOGGER.debug("Added %s on %s", session, self.device_name)

    def _remove_orphan_sessions(self, known_package_names: list[str]) -> None:
        to_remove = [
            key for key in self._sessions
            if key not in known_package_names
        ]
        for key in to_remove:
            del self._sessions[key]

    def cleanup_stale_sessions(self) -> list[str]:
        """Remove sessions that have exceeded the timeout.

        Returns a list of package names that were removed.
        """
        stale = [
            pkg
            for pkg, session in self._sessions.items()
            if not session.is_active(self.session_timeout)
        ]
        for pkg in stale:
            del self._sessions[pkg]
            _LOGGER.debug(
                "Removed stale session %s from %s", pkg, self.device_name
            )

        # Reset active source if it was removed
        if self._active_source and self._active_source not in self._sessions:
            self._active_source = None

        return stale

    @property
    def notify_service_target(self) -> str:
        """Derive the notify service name from the device name.

        sensor.pixel_7_media_session -> notify.mobile_app_pixel_7
        """
        return f"notify.mobile_app_{self.device_name}"

    @property
    def notify_service_name(self) -> str:
        """Derive the notify service name (without domain) from the device name.

        sensor.pixel_7_media_session -> mobile_app_pixel_7
        """
        return f"mobile_app_{self.device_name}"


def _looks_like_session_data(data: dict) -> bool:
    """Heuristic to check if a dict contains media session data."""
    session_keys = {"title", "artist", "album", "state", "duration", "position"}
    return bool(session_keys & set(data.keys()))


def _parse_int(value: Any) -> int | None:
    """Safely parse an integer from a value that might be str, int, or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
