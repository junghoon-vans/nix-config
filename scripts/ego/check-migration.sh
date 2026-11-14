#!/usr/bin/env bash
set -euo pipefail

home="$1"
applications="$2"
helper='Contents/Frameworks/ego Framework.framework/Versions/Current/Helpers/ego-browser'
external_app_ready() {
  [[ -x "$1/$helper" && ! "$1" -ef "$applications/Nix Apps/ego lite.app" ]]
}

# nix-darwin rsync --delete would otherwise silently retire the existing managed app.
if [[ -d "$applications/Nix Apps/ego lite.app" ]] &&
   ! external_app_ready "$home/Applications/ego lite.app" &&
   ! external_app_ready "$applications/ego lite.app"; then
  printf '%s\n' 'Install the official Ego Lite app in ~/Applications or /Applications before activating. The existing /Applications/Nix Apps/ego lite.app is preserved until migration is ready. See docs/nix-toolchain.md#ego-lite.' >&2
  exit 1
fi
