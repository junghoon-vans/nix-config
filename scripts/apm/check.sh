#!/usr/bin/env bash

set -euo pipefail

apm="${1:?usage: check.sh /absolute/path/to/apm}"
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sandbox="$(mktemp -d "${TMPDIR:-/tmp}/apm-check.XXXXXX")"
trap 'rm -rf "$sandbox"' EXIT

# Exercise the same global deployment as bootstrap/switch without touching the user home.
HOME="$sandbox" bash "$repository_root/scripts/apm/setup-apm.sh" "$repository_root" "$apm"
cmp "$repository_root/apm.lock.yaml" "$sandbox/.apm/apm.lock.yaml"
