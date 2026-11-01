#!/usr/bin/env bash
set -euo pipefail

source=${1:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}
out=${2:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}
version=${3:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}
ruby=${4:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}
fiddle=${5:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}
gem_path=${6:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}
fiddle_version=${7:?usage: patch-runtime.sh SOURCE OUT VERSION RUBY FIDDLE GEM_PATH FIDDLE_VERSION}

# Reproduces nix-homebrew's patchBrew from the locked input's modules/default.nix.
cp -R "$source" "$out"
chmod u+w "$out" "$out/Library/Homebrew/cmd"

# Keep the immutable Homebrew source out of update's repository loop.
# Match the upstream shell variable literally, without expanding it here.
# shellcheck disable=SC2016
substituteInPlace "$out/Library/Homebrew/cmd/update.sh" \
  --replace-fail 'for DIR in "${HOMEBREW_REPOSITORY}"' 'for DIR in '

# Use nix-homebrew's system Ruby and expose its fiddle gem to Homebrew's bundle.
ruby_sh="$out/Library/Homebrew/utils/ruby.sh"
bundler_setup_rb="$out/Library/Homebrew/vendor/bundle/bundler/setup.rb"
if [[ ! -f "$ruby_sh" ]] || ! grep -Fq 'setup-ruby-path()' "$ruby_sh"; then
  printf 'Expected setup-ruby-path() patch anchor in %s\n' "$ruby_sh" >&2
  exit 1
fi
chmod u+w "$ruby_sh" "$bundler_setup_rb"
printf 'setup-ruby-path() { export HOMEBREW_RUBY_PATH="%s"; }\n' "$ruby" >>"$ruby_sh"
printf '$:.unshift "%s/%s/gems/fiddle-%s/lib"\n' \
  "$fiddle" "$gem_path" "$fiddle_version" >>"$bundler_setup_rb"

# Homebrew sets its version through set-homebrew-version-from-git;
# replace that call so a source archive reports the tag pinned in flake.lock.
brew_sh="$out/Library/Homebrew/brew.sh"
chmod u+w "$out/Library/Homebrew" "$brew_sh"
substituteInPlace "$brew_sh" \
  --replace-fail 'set-homebrew-version-from-git' "HOMEBREW_VERSION=\"${version}\""

# A standalone pinned runtime has no writable prefix in which to auto-update.
substituteInPlace "$out/bin/brew" \
  --replace-fail '# Copy and export all HOMEBREW_* variables previously mentioned in
# manpage or used elsewhere by Homebrew.' \
  'export HOMEBREW_NO_AUTO_UPDATE=1

# Copy and export all HOMEBREW_* variables previously mentioned in
# manpage or used elsewhere by Homebrew.'
