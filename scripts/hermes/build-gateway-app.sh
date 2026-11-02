#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 5 ]]; then
  printf 'Usage: %s HOST_SOURCE OUTPUT PROFILE COMPILER RCODESIGN\n' "$0" >&2
  exit 64
fi

host_source=$1
output=$2
profile_name=$3
compiler=$4
rcodesign=$5
app_name="Hermes Gateway (${profile_name}).app"
app="$output/Applications/$app_name"
contents="$app/Contents"
host="$contents/MacOS/hermes-gateway-host"

mkdir -p "$contents/MacOS"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror "$host_source" -o "$host"

cat > "$contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>hermes-gateway-host</string>
  <key>CFBundleIdentifier</key>
  <string>org.nixos.hermes.gateway.${profile_name}</string>
  <key>CFBundleName</key>
  <string>Hermes Gateway (${profile_name})</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST
printf 'APPL????' > "$contents/PkgInfo"

# Sign the complete app bundle; the package disables fixups after this point.
"$rcodesign" sign "$app"
