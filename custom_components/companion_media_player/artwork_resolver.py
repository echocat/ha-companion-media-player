"""Artwork resolution for media sessions.

Resolves album art / cover images from media IDs using provider-specific
APIs. Currently, supports Spotify track URIs via the public oEmbed endpoint
(no authentication required).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Spotify oEmbed endpoint — public, no auth needed
_SPOTIFY_OEMBED_URL = "https://open.spotify.com/oembed"

# How long to cache a resolved image URL (seconds)
_CACHE_TTL = 3600  # 1 hour

# How long to cache a failed lookup to avoid hammering the API (seconds)
_NEGATIVE_CACHE_TTL = 300  # 5 minutes

# Timeout for HTTP requests (seconds)
_REQUEST_TIMEOUT = 10


class ArtworkResolver:
    """Resolves and caches artwork URLs for media sessions.

    Uses the Spotify oEmbed API to fetch thumbnail URLs for Spotify track URIs.
    Results are cached to avoid redundant network requests.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the artwork resolver."""
        self._hass = hass
        # Cache: media_id -> (image_url | None, expiry_monotonic_time)
        self._cache: dict[str, tuple[str | None, float]] = {}

    async def resolve(self, media_id: str | None, package_name: str) -> str | None:
        """Resolve an artwork URL for the given media ID and package.

        Returns an image URL string, or None if no artwork could be resolved.
        """
        if not media_id:
            return None

        # Check cache first
        cached = self._get_cached(media_id)
        if cached is not _SENTINEL:
            return cached

        # Attempt provider-specific resolution
        image_url: str | None = None

        if package_name == "com.spotify.music" and self._is_spotify_uri(media_id):
            image_url = await self._resolve_spotify(media_id)

        # Cache the result (even None to avoid repeated failed lookups)
        self._put_cache(media_id, image_url)
        return image_url

    def _get_cached(self, media_id: str) -> str | None | object:
        """Return cached value or _SENTINEL if not cached / expired."""
        entry = self._cache.get(media_id)
        if entry is None:
            return _SENTINEL

        image_url, expiry = entry
        now = asyncio.get_event_loop().time()
        if now >= expiry:
            del self._cache[media_id]
            return _SENTINEL

        return image_url

    def _put_cache(self, media_id: str, image_url: str | None) -> None:
        """Store a result in the cache."""
        now = asyncio.get_event_loop().time()
        ttl = _CACHE_TTL if image_url else _NEGATIVE_CACHE_TTL
        self._cache[media_id] = (image_url, now + ttl)

        # Prune obviously stale entries if cache grows large
        if len(self._cache) > 500:
            self._prune_cache(now)

    def _prune_cache(self, now: float) -> None:
        """Remove expired entries from the cache."""
        expired = [k for k, (_, exp) in self._cache.items() if now >= exp]
        for k in expired:
            del self._cache[k]

    @staticmethod
    def _is_spotify_uri(media_id: str) -> bool:
        """Check if a media ID looks like a Spotify URI."""
        return media_id.startswith("spotify:track:")

    async def _resolve_spotify(self, media_id: str) -> str | None:
        """Resolve artwork for a Spotify track via the oEmbed API.

        The oEmbed endpoint is public and does not require authentication.
        It returns JSON including a ``thumbnail_url`` field (300x300 album art).
        """
        session = async_get_clientsession(self._hass)
        try:
            async with asyncio.timeout(_REQUEST_TIMEOUT):
                resp = await session.get(
                    _SPOTIFY_OEMBED_URL,
                    params={"url": media_id},
                )
                if resp.status != 200:
                    _LOGGER.debug(
                        "Spotify oEmbed returned status %s for %s",
                        resp.status,
                        media_id,
                    )
                    return None

                data = await resp.json()
                thumbnail_url = data.get("thumbnail_url")
                if thumbnail_url:
                    _LOGGER.debug(
                        "Resolved artwork for %s: %s", media_id, thumbnail_url
                    )
                return thumbnail_url
        except TimeoutError:
            _LOGGER.debug("Timeout resolving artwork for %s", media_id)
            return None
        except Exception:
            _LOGGER.debug("Failed to resolve artwork for %s", media_id, exc_info=True)
            return None


# Sentinel object for cache misses (distinguishes "cached None" from "not cached")
_SENTINEL = object()
