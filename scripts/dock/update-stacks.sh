#!/bin/bash
set -euo pipefail

alias_script="$1"
shift
/usr/bin/osascript -l JavaScript "$alias_script" "$@"

# Scope the restart to the activating user; a headless activation has no Dock.
user=$(/usr/bin/id -un)
if /usr/bin/pgrep -u "$user" -x Dock >/dev/null; then
    /usr/bin/killall -u "$user" Dock
fi
