"""Constants for the Companion Media Player integration."""

DOMAIN = "companion_media_player"

ENTITY_ATTR_PREFIX_ALBUM = "album_"
ENTITY_ATTR_PREFIX_ARTIST = "artist_"
ENTITY_ATTR_PREFIX_DURATION = "duration_"
ENTITY_ATTR_PREFIX_MEDIA_ID = "media_id_"
ENTITY_ATTR_PREFIX_PLAYBACK_POSITION = "playback_position_"
ENTITY_ATTR_PREFIX_PLAYBACK_STATE = "playback_state_"
ENTITY_ATTR_PREFIX_TITLE = "title_"

# Options keys
CONF_SESSION_TIMEOUT = "session_timeout"
CONF_VOLUME_MAX = "volume_max"

# Defaults
DEFAULT_SESSION_TIMEOUT = 30  # minutes
DEFAULT_VOLUME_MAX = 15  # typical Android max volume level

# Sensor patterns
MEDIA_SESSION_SENSOR_SUFFIX = "_media_session"
VOLUME_LEVEL_MUSIC_SENSOR_SUFFIX = "_volume_music"

# Notification command messages
NOTIFY_COMMAND_MEDIA = "command_media"
NOTIFY_COMMAND_VOLUME = "command_volume_level"
NOTIFY_COMMAND_UPDATE_SENSORS = "command_update_sensors"

# Media commands
MEDIA_CMD_PLAY = "play"
MEDIA_CMD_PAUSE = "pause"
MEDIA_CMD_STOP = "stop"
MEDIA_CMD_NEXT = "next"
MEDIA_CMD_PREVIOUS = "previous"
MEDIA_CMD_PLAY_PAUSE = "play_pause"

# Volume stream
VOLUME_STREAM_MUSIC = "music_stream"

# Well-known Android package names for friendly display
KNOWN_APPS: dict[str, str] = {
    "com.spotify.music": "Spotify",
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
