#!/usr/bin/env bash

set -euo pipefail

apm="${1:?usage: check.sh /absolute/path/to/apm}"
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sandbox="$(mktemp -d "$repository_root/.apm-check.XXXXXX")"
trap 'rm -rf "$sandbox"' EXIT

# Exercise the same global deployment as bootstrap/switch without touching the user home.
python3 -B "$repository_root/scripts/apm/check.py" "$repository_root" "$sandbox" "$apm"
