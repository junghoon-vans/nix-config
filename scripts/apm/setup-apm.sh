#!/usr/bin/env bash

set -euo pipefail

repository_root="${1:-$PWD}"
manifest="$repository_root/apm.yml"
lockfile="$repository_root/apm.lock.yaml"

[[ -f "$manifest" ]] || {
  echo "apm.yml not found in $repository_root" >&2
  exit 1
}
[[ -f "$lockfile" ]] || {
  echo "apm.lock.yaml not found in $repository_root" >&2
  exit 1
}
command -v apm >/dev/null || {
  echo "APM is not installed; apply the Nix configuration first." >&2
  exit 1
}

mkdir -p "$HOME/.apm"
cp "$manifest" "$HOME/.apm/apm.yml"
cp "$lockfile" "$HOME/.apm/apm.lock.yaml"
apm install --global --target agent-skills --only apm --frozen
