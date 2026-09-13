#!/usr/bin/env bash

set -euo pipefail

host="${1:?host is required}"
repository_root="${2:-$PWD}"
nix_conf="${NIX_CONF:-/etc/nix/nix.conf}"

case "$host" in
  junghoonui-MacBookAir|junghoonui-MacBookPro) ;;
  *) printf 'Unsupported host: %s\n' "$host" >&2; exit 2 ;;
esac

if [[ ! -d "$repository_root" || ! -f "$repository_root/flake.nix" || ! -f "$repository_root/flake.lock" ]]; then
  printf 'Expected a repository with flake.nix and flake.lock: %s\n' "$repository_root" >&2
  exit 2
fi

# Resolve a relative override before changing directories.
if [[ "$nix_conf" != /* ]]; then
  nix_conf="$PWD/$nix_conf"
fi
cd "$repository_root"
nix --extra-experimental-features "nix-command flakes" eval --no-write-lock-file \
  ".#darwinConfigurations.${host}.config.system.build.toplevel.drvPath" >/dev/null

if [[ -L "$nix_conf" || ( -e "$nix_conf" && ! -f "$nix_conf" ) ]]; then
  printf 'Refusing to replace a symlink or non-regular config: %s\n' "$nix_conf" >&2
  exit 2
fi

temporary_conf="$(mktemp)"
staged_conf=""
cleanup() {
  rm -f "$temporary_conf"
  if [[ -n "$staged_conf" ]]; then
    sudo /bin/rm -f "$staged_conf"
  fi
}
trap cleanup EXIT

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
  # Stage beside the destination so rename is atomic; preserve existing metadata.
  staged_conf="$(sudo mktemp "${nix_conf}.tmp.XXXXXX")"
  if [[ -f "$nix_conf" ]]; then
    backup_conf="$(sudo mktemp "${nix_conf}.backup.XXXXXX")"
    sudo /bin/cp -p "$nix_conf" "$backup_conf"
    printf 'Nix configuration backup: %s\n' "$backup_conf"
    sudo /bin/cp -p "$nix_conf" "$staged_conf"
    sudo /bin/cp "$temporary_conf" "$staged_conf"
  else
    sudo /usr/bin/install -m 0644 "$temporary_conf" "$staged_conf"
  fi
  sudo /bin/mv -f "$staged_conf" "$nix_conf"
  staged_conf=""
fi

sudo -H nix --extra-experimental-features "nix-command flakes" run \
  --no-write-lock-file --inputs-from . nix-darwin#darwin-rebuild -- switch --flake ".#$host"
