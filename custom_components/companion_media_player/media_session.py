"""Media Session Manager for tracking companion app media sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components.media_player import MediaPlayerState
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
from .utils import parse_int

_LOGGER = logging.getLogger(__name__)


@dataclass
class MediaSession:
    """Represents a single media session from an Android app."""

    def __init__(
            self,
            device_name: str,
            package_name: str,
            media_id: str | None = None,
            state: str = "idle",
            title: str | None = None,
            artist: str | None = None,
            album: str | None = None,
            duration: int | None = None,
            position: int | None = None,
            media_image_url: str | None = None,
            last_updated: datetime = field(default_factory=dt_util.utcnow),
    ) -> None:
        self._device_name = device_name
        self.package_name = package_name
        self.media_id = media_id
        self._state = state.lower()
        self.title = title
        self.artist = artist
        self.album = album
        self.duration = duration
        self.position = position
        self.media_image_url = media_image_url
        self.last_updated = last_updated

    @property
    def state(self) -> MediaPlayerState:
        match self._state:
            case "playing":
                return MediaPlayerState.PLAYING
            case "paused":
                return MediaPlayerState.PAUSED
            case "buffering":
                return MediaPlayerState.BUFFERING
            case "idle" | "stopped" | "error":
                return MediaPlayerState.IDLE
            case _:
                _LOGGER.debug("Media session %s on %s is in an illegal state: %s; treat it idle instead.",
                              self.package_name, self._device_name, self._state)
                return MediaPlayerState.IDLE

    def get_clean_state(self, timeout_minutes: int) -> MediaPlayerState:
        state = self.state
        match state:
            case MediaPlayerState.PLAYING | MediaPlayerState.PAUSED | MediaPlayerState.BUFFERING:
                cutoff = dt_util.utcnow() - timedelta(minutes=timeout_minutes)
                return state if self.last_updated >= cutoff else MediaPlayerState.IDLE
            case _:
                return state

    @property
    def friendly_name(self) -> str:
        """Return a human-readable name for this session."""
        return _known_apps.get(self.package_name, self.package_name)

class MediaSessions:

    def __init__(
            self,
            device_name: str,
    ) -> None:
        self._device_name = device_name
        self._values: dict[str, MediaSession] = {}
        self._selected: MediaSession | None = None

    @property
    def values(self) -> list[MediaSession]:
        return sorted(self._values.values(), key=lambda s: s.package_name)

    def by_package_name(self, package_name: str) -> MediaSession | None:
        return self._values[package_name]

    def get_selected(self, session_timeout: int = DEFAULT_SESSION_TIMEOUT) -> MediaSession | None:
        if self._selected and self._selected.package_name not in self._values:
            self._selected = None

        if self._selected:
            state = self._selected.get_clean_state(session_timeout)
            match state:
                # Simply select the existing one as long it is somehow in a meaningful state...
                case MediaPlayerState.PLAYING | MediaPlayerState.PAUSED | MediaPlayerState.BUFFERING:
                    return self._selected

        first: MediaSession | None = self._selected
        # Nothing already selected... simply pick the next one which is playing/buffering...
        for candidate in self._values.values():
            if not first:
                first = candidate
            state = candidate.get_clean_state(session_timeout)
            match state:
                case MediaPlayerState.PLAYING | MediaPlayerState.BUFFERING:
                    self._selected = candidate
                    _LOGGER.debug("Switched to selected session %s (state=%s) on %s",
                                  candidate.package_name, state, self._device_name)

        # Use if existing one (if already there)...
        if self._selected:
            return self._selected

        # Ok, just use the first one...
        if first:
            self._selected = first
            _LOGGER.debug("Switched to selected session %s (state=%s) on %s",
                          first.package_name, first.get_clean_state(session_timeout), self._device_name)
            return self._selected

        self._selected = None
        _LOGGER.debug("Switched to selected session NONE on %s", self._device_name)
        return None

    def set_selected(self, v: MediaSession) -> None:
        if isinstance(v, MediaSession):
            if not v.package_name:
                _LOGGER.debug("Switched to selected session NONE on %s", self._device_name)
                self._selected = None
            elif self._values[v.package_name]:
                _LOGGER.debug("Switched to selected session %s (state=%s) on %s",
                              v.package_name, v.state, self._device_name)
                self._selected = v
            else:
                raise ValueError(f"Value {v.package_name} is not in the actual stored sessions.")
        elif isinstance(v, str):
            if not v:
                self._selected = None
                _LOGGER.debug("Switched to selected session NONE on %s", self._device_name)
            else:
                vv = self._values[v]
                if vv:
                    _LOGGER.debug("Switched to selected session %s (state=%s) on %s",
                                  vv.package_name, vv.state, self._device_name)
                    self._selected = vv
                else:
                    raise ValueError(f"Value {v} is not in the actual stored sessions.")
        else:
            raise TypeError(f"Unsupported type: {type(v).__name__}")

    @callback
    def update_from_sensor(self, state: State) -> None:
        """Update session data from a media session sensor state change."""

        if state is None or state.state in ("unavailable", "unknown"):
            self._values = {}
            self._selected = None
            return

        attrs = state.attributes
        now = dt_util.utcnow()

        buf: dict[str, MediaSession] = {}
        for key, media_id in attrs.items():
            if key.startswith(ENTITY_ATTR_PREFIX_MEDIA_ID):
                package_name = key.removeprefix(ENTITY_ATTR_PREFIX_MEDIA_ID)
                state = attrs[f"{ENTITY_ATTR_PREFIX_PLAYBACK_STATE}{package_name}"]
                if state is None:
                    _LOGGER.warning("Media session of device %s is lacking required attribute %s%s; ignoring session.",
                                    self._device_name, ENTITY_ATTR_PREFIX_PLAYBACK_STATE, package_name)
                    continue
                title = attrs[f"{ENTITY_ATTR_PREFIX_TITLE}{package_name}"]
                if title is None:
                    _LOGGER.warning("Media session of device %s is lacking required attribute %s%s; ignoring session.",
                                    self._device_name, ENTITY_ATTR_PREFIX_TITLE, package_name)
                    continue
                buf[package_name] = MediaSession(
                    device_name=self._device_name,
                    package_name=package_name,
                    media_id=media_id,
                    state=state,
                    title=title,
                    artist=attrs[f"{ENTITY_ATTR_PREFIX_ARTIST}{package_name}"],
                    album=attrs[f"{ENTITY_ATTR_PREFIX_ALBUM}{package_name}"],
                    duration=parse_int(attrs[f"{ENTITY_ATTR_PREFIX_DURATION}{package_name}"]),
                    position=parse_int(attrs[f"{ENTITY_ATTR_PREFIX_PLAYBACK_POSITION}{package_name}"]),
                    last_updated=now,
                )

        self._values = buf


_known_apps: dict[str, str] = {
    "com.spotify.music": "Spotify",
    "com.spotify.kids": "Spotify Kids",
    "com.google.android.apps.youtube.music": "YouTube Music",
    "com.google.android.youtube": "YouTube",
    "com.google.android.apps.podcasts": "Google Podcasts",
    "org.videolan.vlc": "VLC",
    "com.plexapp.android": "Plex",
    "com.aspiro.tidal": "Tidal",
    "com.amazon.mp3": "Amazon Music",
    "com.apple.android.music": "Apple Music",
    "com.pandora.android": "Pandora",
    "com.soundcloud.android": "SoundCloud",
    "fm.castbox.audiobook.radio.podcast": "Castbox",
    "com.google.android.apps.youtube.creator": "YouTube Studio",
    "com.netflix.mediaclient": "Netflix",
    "com.disney.disneyplus": "Disney+",
    "tv.twitch.android.app": "Twitch",
    "tunein.player": "TuneIn",
}
