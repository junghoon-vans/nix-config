#!/usr/bin/env bash

set -euo pipefail

# Default to the activated Nix package; validation can pass a freshly built one.
apm="${2:-/run/current-system/sw/bin/apm}"
# Git remains Homebrew-managed; the invoking shell may predate first activation.
export PATH="$PATH:/opt/homebrew/bin"

repository_root="${1:-$PWD}"
manifest="$repository_root/apm.yml"

[[ -f "$manifest" ]] || {
  echo "apm.yml not found in $repository_root" >&2
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

# Let APM remove the old skill while its deployment ownership is still recorded.
if [[ -d "$HOME/.apm/apm_modules/netresearch/jira-skill/skills/jira-syntax" ]]; then
  "$apm" uninstall --global netresearch/jira-skill/skills/jira-syntax
fi

mkdir -p "$HOME/.apm/skills"
cp -R "$repository_root/skills/." "$HOME/.apm/skills/"
cp "$manifest" "$HOME/.apm/apm.yml"
# Keep the machine-local lockfile: repository deployment receipts cannot replace it.
# A normal install resolves manifest pins and records ownership; --frozen cannot.
"$apm" install --global --target agent-skills --only apm --trust-bin
