#!/usr/bin/env bash
set -euo pipefail

brew=${1:?usage: check-runtime.sh BREW VERSION RUBY FIDDLE_LIB}
expected_version=${2:?usage: check-runtime.sh BREW VERSION RUBY FIDDLE_LIB}
ruby=${3:?usage: check-runtime.sh BREW VERSION RUBY FIDDLE_LIB}
fiddle_lib=${4:?usage: check-runtime.sh BREW VERSION RUBY FIDDLE_LIB}

if [[ ! -x "$brew" ]]; then
  printf 'Homebrew executable is missing or not executable: %s\n' "$brew" >&2
  exit 1
fi

brew_root=${brew%/bin/brew}
if [[ "$brew_root" == "$brew" || ! -d "$brew_root/Library/Homebrew" ]]; then
  printf 'Expected the locked Homebrew tree at <package-root>/bin/brew: %s\n' "$brew" >&2
  exit 1
fi


test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/home" "$test_root/cache" "$test_root/tmp"

run_brew() {
  /usr/bin/env -i \
    HOME="$test_root/home" \
    LOGNAME="$(/usr/bin/id -un)" \
    USER="$(/usr/bin/id -un)" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    TMPDIR="$test_root/tmp" \
    HOMEBREW_CACHE="$test_root/cache" \
    HOMEBREW_TEMP="$test_root/tmp" \
    HOMEBREW_NO_AUTO_UPDATE=1 \
    HOMEBREW_NO_INSTALL_FROM_API=1 \
    HOMEBREW_DEVELOPER=1 \
    HOMEBREW_NO_ANALYTICS=1 \
    HOMEBREW_NO_ENV_HINTS=1 \
    "$brew" "$@"
}

version_output=$(run_brew --version)
version_line=${version_output%%$'\n'*}
if [[ "$version_line" != "Homebrew $expected_version" ]]; then
  printf 'Expected Homebrew %s, got:\n%s\n' "$expected_version" "$version_output" >&2
  exit 1
fi

prefix=$(run_brew --prefix)
repository=$(run_brew --repository)
cache=$(run_brew --cache)
if [[ "$prefix" != "$brew_root" || "$repository" != "$brew_root" || "$cache" != "$test_root/cache" ]]; then
  printf 'Unexpected standalone runtime paths:\nprefix: %s\nrepository: %s\ncache: %s\n' \
    "$prefix" "$repository" "$cache" >&2
  exit 1
fi

# Exercise the actual Homebrew Ruby entry point and its loaded fiddle extension.
# Ruby, not the shell, expands $LOADED_FEATURES.
# shellcheck disable=SC2016
ruby_output=$(run_brew ruby -e 'require "rbconfig"; require "fiddle"; puts RbConfig.ruby; puts $LOADED_FEATURES.find { |path| path.end_with?("/fiddle.rb") }')
if [[ "$ruby_output" != "$ruby"$'\n'"$fiddle_lib/fiddle.rb" ]]; then
  printf 'Unexpected Homebrew Ruby/fiddle runtime:\n%s\n' "$ruby_output" >&2
  exit 1
fi
printf 'Homebrew %s: exact version, isolated paths, Nix Ruby and fiddle verified\n' "$expected_version"
