#!/usr/bin/env bash
set -euo pipefail

: "${out:?}" "${extensionManifest:?}" "${wasiAdapter:?}"

runHook preInstall
mkdir -p "$out"
cp -R languages "$out/languages"
cp "$extensionManifest" "$out/extension.toml"
wasm-tools component new target/wasm32-wasip1/release/gno_zed_extension.wasm \
  --adapt "wasi_snapshot_preview1=$wasiAdapter" \
  -o "$out/extension.wasm"
wasm-tools validate "$out/extension.wasm"
runHook postInstall
