#!/usr/bin/env bash
set -euo pipefail

hermes=$1
root=$2
name=$3
profile_home="$root/profiles/$name"

umask 077
if [[ ! -e "$profile_home" ]]; then
  HERMES_HOME="$root" "$hermes" profile create "$name" --no-alias
fi
install -d -m 0700 "$profile_home/logs"
