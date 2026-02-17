# Development

This project uses [VS Code DevContainers](https://code.visualstudio.com/docs/devcontainers/containers) for development.

## Prerequisites

- [Docker](https://www.docker.com/) installed and running
- [VS Code](https://code.visualstudio.com/) with the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

## Getting Started

1. Open this repository in VS Code
2. When prompted, click **"Reopen in Container"** (or run `Dev Containers: Reopen in Container` from the command palette)
3. Wait for the container to build (first time takes a few minutes to install HA)
4. Home Assistant starts automatically on port **8123**
5. Open http://localhost:8123 to access the HA instance

## Dev Workflow

- **Code changes**: Edit files in `custom_components/companion_media_player/` — they're symlinked into HA's config
- **Restart HA**: Run `pkill -f hass; .devcontainer/post-start.sh` in the terminal
- **View logs**: `tail -f /tmp/hass.log`
- **Debug logs**: Already enabled for `custom_components.companion_media_player` via `/config/configuration.yaml`
