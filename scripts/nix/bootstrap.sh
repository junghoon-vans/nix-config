#!/usr/bin/env bash

set -euo pipefail

host="${1:?host is required}"
repository_root="${2:-$PWD}"
nix_conf="${NIX_CONF:-/etc/nix/nix.conf}"
temporary_conf="$(mktemp)"
trap 'rm -f "$temporary_conf"' EXIT

trim_whitespace() {
  local value="$1"

  while [[ "$value" =~ ^[[:space:]] ]]; do
    value="${value:1}"
  done
  while [[ "$value" =~ [[:space:]]$ ]]; do
    value="${value:0:${#value}-1}"
  done

  printf '%s' "$value"
}

found_features=0
changed_features=0

if [[ -f "$nix_conf" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" =~ ^[[:space:]]*experimental-features[[:space:]]*= ]]; then
      found_features=1
      features="${line#*=}"
      comment=""

      if [[ "$features" == *'#'* ]]; then
        comment="#${features#*\#}"
        features="${features%%\#*}"
      fi

      features="$(trim_whitespace "$features")"
      for feature in nix-command flakes; do
        if ! [[ " $features " =~ (^|[[:space:]])${feature}([[:space:]]|$) ]]; then
          features+=" $feature"
          changed_features=1
        fi
      done

      printf 'experimental-features = %s' "$features" >>"$temporary_conf"
      if [[ -n "$comment" ]]; then
        printf ' %s' "$comment" >>"$temporary_conf"
      fi
      printf '\n' >>"$temporary_conf"
    else
      printf '%s\n' "$line" >>"$temporary_conf"
    fi
  done <"$nix_conf"
fi

if (( ! found_features )); then
  printf 'experimental-features = nix-command flakes\n' >>"$temporary_conf"
  changed_features=1
fi

if (( changed_features )); then
  sudo /bin/cp "$temporary_conf" "$nix_conf"
fi

cd "$repository_root"
exec sudo -H nix --extra-experimental-features "nix-command flakes" run \
  --inputs-from . nix-darwin#darwin-rebuild -- switch --flake ".#$host"
