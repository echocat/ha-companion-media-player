# Companion Media Player

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/echocat/ha-companion-media-player)](https://github.com/echocat/ha-companion-media-player/releases)
[![GitHub license](https://img.shields.io/github/license/echocat/ha-companion-media-player)](https://github.com/echocat/ha-companion-media-player/blob/main/LICENSE)

A Home Assistant custom integration that creates **Media Player entities** from the **Android Companion App's Media Session sensors**.

## Features

- **Auto-Discovery**: Automatically detects all Android devices with the Companion App that have a Media Session sensor enabled.
- **Full Media Player Controls**: Play, Pause, Stop, Next Track, Previous Track, and Volume control — all sent via the Companion App's notification commands.
- **Multi-Session Support**: Each Android device can have multiple active media sessions (e.g., Spotify, YouTube). Sessions are exposed as selectable sources.
- **State Caching**: Since the Media Session sensor only reports state changes (not current state on demand), this integration maintains a persistent cache of all session states.
- **Session Timeout**: Sessions that haven't reported activity within a configurable timeout (default: 30 minutes) are automatically marked as inactive.
- **Sensor Update Trigger**: After every control command, a sensor update is triggered on the device to get faster state feedback.

## Requirements

- Home Assistant 2026.1.0 or newer
- Android device(s) with the [Home Assistant Companion App](https://companion.home-assistant.io/) installed
- **Media Session sensor** enabled in the Companion App (Manage Sensors → Media Session)
- **Notification Listener permission** granted to the Companion App

## Installation

### Quick Add to HACS

[![Open your Home Assistant instance and add this repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=echocat&repository=ha-companion-media-player&category=integration)

### HACS *(recommended)*
1. Open HACS in your Home Assistant instance
2. Click on **Integrations**
3. Click the three dots in the top right and select **Custom repositories**
4. Add `https://github.com/echocat/ha-companion-media-player` as an **Integration**
5. Click **Install**
6. Restart Home Assistant

<details>
<summary><h3>Manual</h3></summary>

You probably **do not** want to do this! Use the HACS method above unless you know what you are doing and have a good reason as to why you are installing manually

1. Download the latest release
2. Copy the `custom_components/companion_media_player` folder into your Home Assistant's `custom_components` directory
3. Restart Home Assistant
</details>

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Companion Media Player**
3. The integration will automatically find all devices with a Media Session sensor
4. Select the device(s) you want to create Media Player entities for
5. Configure options (session timeout, volume range) as needed

## Options

| Option | Default | Description |
|--------|---------|-------------|
| Session Timeout | 30 minutes | Time after which an inactive media session is considered idle (regardless if it is playing or not). |
| Volume Max | 15 | Maximum volume level of the Android device (used for 0.0–1.0 mapping) |

## Development

To see more details how to develop with this project - see the [DEVELOPMENT.md](DEVELOPMENT.md) file.

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.
