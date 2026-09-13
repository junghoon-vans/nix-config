#!/usr/bin/env bash

set -euo pipefail

mkdir -p "${out:?}/libexec" "$out/bin"
cp -R apm-darwin-arm64 "$out/libexec/apm"
ln -s "$out/libexec/apm/apm" "$out/bin/apm"
