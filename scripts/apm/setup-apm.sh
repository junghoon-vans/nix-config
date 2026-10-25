#!/usr/bin/env bash

set -euo pipefail

# Default to the activated Nix package; validation can pass a freshly built one.
apm="${2:-/run/current-system/sw/bin/apm}"
# Git remains Homebrew-managed; the invoking shell may predate first activation.
export PATH="$PATH:/opt/homebrew/bin"

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
[[ -f "$repository_root/skills/jira-cloud-formatting/SKILL.md" ]] || {
  echo "jira-cloud-formatting skill not found in $repository_root/skills" >&2
  exit 1
}
[[ -x "$apm" ]] || {
  echo "APM is not installed; apply the Nix configuration first." >&2
  exit 1
}

# 0.34 can overwrite edited skills on a normal global reinstall.
apm_version="$("$apm" --version)"
if [[ ! "$apm_version" =~ version\ ([0-9]+)\.([0-9]+)\. ]] ||
  (( BASH_REMATCH[1] == 0 && BASH_REMATCH[2] < 35 )); then
  echo "APM 0.35 or newer is required to preserve edited skills; apply the Nix configuration first." >&2
  exit 1
fi

# Validate the exact portable inputs before changing the machine's manifest,
# receipts or deployed skills. Project roots must install in project scope;
# this entry point is exclusively the machine-wide common skill owner.
staging="$(mktemp -d "$repository_root/.apm-setup.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
mkdir -p "$staging/.apm/skills"
cp -R "$repository_root/skills/." "$staging/.apm/skills/"
cp "$manifest" "$staging/.apm/apm.yml"
cp "$lockfile" "$staging/.apm/apm.lock.yaml"
HOME="$staging" "$apm" install --global --target agent-skills --only apm --trust-bin --frozen --dry-run

# APM 0.35 binds receipts to st_dev, which can change across macOS mounts.
# Receipts remain machine-local: the committed lock is not ownership evidence.
python3 -B "$(dirname "${BASH_SOURCE[0]}")/refresh-receipt-device.py"

# Retire the legacy external skill while APM still has its old ownership ledger.
if [[ -d "$HOME/.apm/apm_modules/netresearch/jira-skill/skills/jira-syntax" ]]; then
  "$apm" uninstall --global netresearch/jira-skill/skills/jira-syntax
fi

mkdir -p "$HOME/.apm/skills"
cp -R "$staging/.apm/skills/." "$HOME/.apm/skills/"
cp "$staging/.apm/apm.yml" "$HOME/.apm/apm.yml"
cp "$staging/.apm/apm.lock.yaml" "$HOME/.apm/apm.lock.yaml"
"$apm" install --global --target agent-skills --only apm --trust-bin --frozen
