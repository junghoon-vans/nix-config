#!/usr/bin/env bash
set -euo pipefail

helper='Contents/Frameworks/ego Framework.framework/Versions/Current/Helpers/ego-browser'
if [[ -n "${EGO_LITE_APP:-}" ]]; then
  apps=("$EGO_LITE_APP")
else
  apps=("$HOME/Applications/ego lite.app" '/Applications/ego lite.app')
fi

for app in "${apps[@]}"; do
  if [[ -x "$app/$helper" ]]; then
    exec "$app/$helper" "$@"
  fi
done

printf '%s\n' 'Ego Lite CLI not found. Install the official Ego Lite app in ~/Applications or /Applications, or set EGO_LITE_APP to its .app path. Nix does not install or update the app.' >&2
exit 127
