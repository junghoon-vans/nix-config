#!/usr/bin/env bash

set -euo pipefail

script_dir="$(dirname "${BASH_SOURCE[0]}")"
cd "$script_dir/../.."

bash_scripts=(
  .github/scripts/detect-nix-config-changes
  .github/scripts/require-nix-validation
  home/.local/bin/weekly-disk-maintenance
  scripts/apm/install.sh
  scripts/apm/setup-apm.sh
  scripts/nix/bootstrap.sh
  scripts/nix/home-manager-backups-cleanup.sh
  scripts/updates/open-update-pr.sh
  scripts/validation/check.sh
  scripts/zed/install-gno-extension.sh
)

for script in "${bash_scripts[@]}"; do
  bash -n "$script"
done
shellcheck --shell=bash "${bash_scripts[@]}"
zsh -n home/.zshrc

python3 -B -m unittest discover -s scripts/nix -p 'test_*.py'
python3 -B -m unittest discover -s scripts/aside -p 'test_*.py'
python3 -B -m unittest discover -s scripts/maintenance -p 'test_*.py'
python3 -B scripts/validation/check-doc-version-drift.py
python3 -B scripts/updates/update-fixed-release.py --help >/dev/null
python3 -B scripts/updates/update-tagged-skills.py --help >/dev/null

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
