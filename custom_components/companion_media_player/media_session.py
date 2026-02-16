"""Media Session Manager for tracking companion app media sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.core import callback, State
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
)
from .const import (
    KNOWN_APPS,
)
from .utils import parse_int

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


class MediaSessions:

    def __init__(
            self,
            values: dict[str, MediaSession] | None = None,
            selected: MediaSession | None = None,
    ) -> None:
        self._values = values or {}
        self._selected = selected

    @property
    def values(self) -> list[MediaSession]:
        return sorted(self._values.values(), key=lambda s: s.package_name)

    def by_package_name(self, package_name: str) -> MediaSession | None:
        return self._values[package_name]

    @property
    def selected(self) -> MediaSession | None:
        return self._selected

    def by_is_active(self, session_timeout: int = DEFAULT_SESSION_TIMEOUT) -> list[MediaSession]:
        return sorted(
            (
                session
                for session in self._values.values()
                if session.is_active(session_timeout)
            ),
            key=lambda s: s.package_name,
        )

    @selected.setter
    def selected(self, v: MediaSession) -> None:
        if isinstance(v, MediaSession):
            if not v.package_name:
                self._selected = None
            elif self._values[v.package_name]:
                self._selected = v
            else:
                raise ValueError(f"Value {v.package_name} is not in the actual stored sessions.")
        elif isinstance(v, str):
            if not v:
                self._selected = None
            elif self._values[v]:
                self._selected = v
            else:
                raise ValueError(f"Value {v} is not in the actual stored sessions.")
        else:
            raise TypeError(f"Unsupported type: {type(v).__name__}")

    @callback
    def update_from_sensor(self, device_name: str, new_state: State) -> None:
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
                                    device_name, ENTITY_ATTR_PREFIX_PLAYBACK_STATE, package_name)
                    continue
                title = attrs[f"{ENTITY_ATTR_PREFIX_TITLE}{package_name}"]
                if title is None:
                    _LOGGER.warning("Media session of device %s is lacking required attribute %s%s; ignoring session.",
                                    device_name, ENTITY_ATTR_PREFIX_TITLE, package_name)
                    continue
                artist = attrs[f"{ENTITY_ATTR_PREFIX_ARTIST}{package_name}"]
                album = attrs[f"{ENTITY_ATTR_PREFIX_ALBUM}{package_name}"]
                duration = parse_int(attrs[f"{ENTITY_ATTR_PREFIX_DURATION}{package_name}"])
                position = parse_int(attrs[f"{ENTITY_ATTR_PREFIX_PLAYBACK_POSITION}{package_name}"])
                self._ensure(
                    device_name=device_name,
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

        self._remove_orphan(device_name, known_package_names)

    def _ensure(
            self,
            device_name: str,
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
        if package_name in self._values:
            session = self.by_package_name(package_name)
            session.media_id = media_id
            session.state = state
            session.title = title
            session.artist = artist
            session.album = album
            session.duration = duration
            session.position = position
            session.last_updated = now
            _LOGGER.debug("Updated %s on %s", session, device_name)
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
            self._values[package_name] = session
            _LOGGER.debug("Added %s on %s", session, device_name)

    def _remove_orphan(self, device_name: str, known_package_names: list[str]) -> None:
        to_remove = [
            key for key in self._values
            if key not in known_package_names
        ]
        for key in to_remove:
            del self._values[key]
            _LOGGER.debug("Orphan session %s of %s removed.", key, device_name)

    def cleanup_stale(self, device_name: str, session_timeout: int) -> list[str]:
        """Remove sessions that have exceeded the timeout.

        Returns a list of package names that were removed.
        """
        stale = [
            pkg
            for pkg, session in self._values.items()
            if not session.is_active(session_timeout)
        ]
        for pkg in stale:
            del self._values[pkg]
            _LOGGER.debug(
                "Removed stale session %s from %s", pkg, device_name
            )

        # Reset active source if it was removed
        if self._selected and self._selected not in self._values:
            self._selected = None

        return stale
