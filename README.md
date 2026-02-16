# Companion Media Player

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration that creates **Media Player entities** from the **Android Companion App's Media Session sensors**.

## ⚠️⚠️⚠️ STILL WORK IN PROGRESS ⚠️⚠️⚠️

## Features

- **Auto-Discovery**: Automatically detects all Android devices with the Companion App that have a Media Session sensor enabled.
- **Full Media Player Controls**: Play, Pause, Stop, Next Track, Previous Track, and Volume control — all sent via the Companion App's notification commands.
- **Multi-Session Support**: Each Android device can have multiple active media sessions (e.g., Spotify, YouTube). Sessions are exposed as selectable sources.
- **State Caching**: Since the Media Session sensor only reports state changes (not current state on demand), this integration maintains a persistent cache of all session states.
- **Session Timeout**: Sessions that haven't reported activity within a configurable timeout (default: 30 minutes) are automatically marked as inactive.
- **Sensor Update Trigger**: After every control command, a sensor update is triggered on the device to get faster state feedback.

## Requirements

- Home Assistant 2024.1.0 or newer
- Android device(s) with the [Home Assistant Companion App](https://companion.home-assistant.io/) installed
- **Media Session sensor** enabled in the Companion App (Manage Sensors → Media Session)
- **Notification Listener permission** granted to the Companion App

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on **Integrations**
3. Click the three dots in the top right and select **Custom repositories**
4. Add `https://github.com/echocat/ha-companion-media-player` as an **Integration**
5. Click **Install**
6. Restart Home Assistant

### Manual

1. Copy the `custom_components/companion_media_player` folder into your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Companion Media Player**
3. The integration will automatically find all devices with a Media Session sensor
4. Select the device(s) you want to create Media Player entities for
5. Configure options (session timeout, volume range) as needed

## Options

| Option | Default | Description |
|--------|---------|-------------|
| Session Timeout | 30 minutes | Time after which an inactive media session is considered stale |
| Volume Max | 15 | Maximum volume level of the Android device (used for 0.0–1.0 mapping) |

## How It Works

### State Tracking

The Android Companion App provides a `sensor.<device>_media_session` entity that reports the current media playback state and metadata. This integration listens for state changes on that sensor and caches the state of each individual media session (identified by package name).

### Media Control

Control commands are sent via Home Assistant's notification service (`notify.mobile_app_<device>`), using the Companion App's `command_media` and `command_volume_level` notification commands. After each command, a `command_update_sensors` notification is sent to trigger a faster state update.

### Source Selection

Each active media session on a device (e.g., Spotify, YouTube Music) is represented as a **source**. You can switch between sources to control different apps. The most recently active session is selected by default.

## Development

This project uses [VS Code DevContainers](https://code.visualstudio.com/docs/devcontainers/containers) for development.

### Prerequisites

- [Docker](https://www.docker.com/) installed and running
- [VS Code](https://code.visualstudio.com/) with the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

### Getting Started

1. Open this repository in VS Code
2. When prompted, click **"Reopen in Container"** (or run `Dev Containers: Reopen in Container` from the command palette)
3. Wait for the container to build (first time takes a few minutes to install HA)
4. Home Assistant starts automatically on port **8123**
5. Open http://localhost:8123 to access the HA instance

### Dev Workflow

- **Code changes**: Edit files in `custom_components/companion_media_player/` — they're symlinked into HA's config
- **Restart HA**: Run `pkill -f hass; .devcontainer/post-start.sh` in the terminal
- **View logs**: `tail -f /tmp/hass.log`
- **Debug logs**: Already enabled for `custom_components.companion_media_player` via `/config/configuration.yaml`

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.
