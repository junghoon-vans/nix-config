#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

case "${1:-}" in
  update)
    host="${2:-}"
    case "$host" in
      junghoonui-MacBookAir|junghoonui-MacBookPro) ;;
      *) printf 'Set HOST to junghoonui-MacBookAir or junghoonui-MacBookPro.\n' >&2; exit 2 ;;
    esac

    nix flake update homebrew-core homebrew-cask
    sudo -H darwin-rebuild switch --flake ".#$host"
    HOMEBREW_NO_AUTO_UPDATE=1 brew outdated
    printf '\nReview the list, then run make brew-upgrade or make brew-upgrade PACKAGE=<name>.\n'
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
    printf 'Usage: %s update <host> | upgrade [package]\n' "$0" >&2
    exit 2
    ;;
esac
