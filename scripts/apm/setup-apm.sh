#!/usr/bin/env bash

set -euo pipefail

# Use the activated Nix package even when older local installations shadow PATH.
apm=/run/current-system/sw/bin/apm
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

# Let APM remove the old skill while its deployment ownership is still recorded.
# Replacing the lockfile first would lose the provenance needed for safe cleanup.
if [[ -d "$HOME/.apm/apm_modules/netresearch/jira-skill/skills/jira-syntax" ]]; then
  "$apm" uninstall --global netresearch/jira-skill/skills/jira-syntax
fi

mkdir -p "$HOME/.apm/skills"
cp -R "$repository_root/skills/." "$HOME/.apm/skills/"
cp "$manifest" "$HOME/.apm/apm.yml"
cp "$lockfile" "$HOME/.apm/apm.lock.yaml"
"$apm" install --global --target agent-skills --only apm --frozen --trust-bin
