#!/usr/bin/env bash

set -euo pipefail

script_dir="$(dirname "${BASH_SOURCE[0]}")"
cd "$script_dir/../.."

bash_scripts=(
  .github/scripts/detect-nix-config-changes
  .github/scripts/require-nix-validation
  home/.local/bin/weekly-disk-maintenance
  scripts/apm/setup-apm.sh
  scripts/nix/bootstrap.sh
  scripts/validation/check.sh
)

for script in "${bash_scripts[@]}"; do
  bash -n "$script"
done
shellcheck --shell=bash "${bash_scripts[@]}"
zsh -n home/.zshrc

python3 scripts/nix/test-bootstrap.py

nix_files=()
while IFS= read -r file; do
  nix_files+=("$file")
done < <(git ls-files -- '*.nix')
if [ "${#nix_files[@]}" -gt 0 ]; then
  nixfmt --check "${nix_files[@]}"
fi
statix check .
deadnix .
nix flake metadata --no-write-lock-file
