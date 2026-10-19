#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

case "${1:-}" in
  update)
    nix flake update homebrew-core homebrew-cask
    printf '\nReview and commit flake.lock, activate with make switch HOST=<host>, then run make brew-outdated.\n'
    ;;
  outdated)
    HOMEBREW_NO_AUTO_UPDATE=1 brew outdated
    ;;
  upgrade)
    package="${2:-}"
    if [[ "$package" == -* || "$package" == *[[:space:]]* ]]; then
      printf 'PACKAGE must be one formula or cask name, not flags or a package list.\n' >&2
      exit 2
    fi
    export HOMEBREW_NO_AUTO_UPDATE=1
    if [[ -n "$package" ]]; then
      brew upgrade "$package"
    else
      brew upgrade
    fi
    ;;
  *)
    printf 'Usage: %s update | outdated | upgrade [package]\n' "$0" >&2
    exit 2
    ;;
esac
