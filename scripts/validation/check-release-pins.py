#!/usr/bin/env python3

import base64
import binascii
import json
import re
from pathlib import Path

pins = json.loads(Path("release-pins.json").read_text())
expected = {"apm", "bun", "gnomcp", "omp", "paseo"}
if not isinstance(pins, dict) or pins.keys() != expected:
    raise SystemExit("release-pins.json must contain exactly the supported packages")

for name, pin in pins.items():
    if not isinstance(pin, dict) or pin.keys() != {"version", "hash"}:
        raise SystemExit(f"{name}: expected version and hash")
    if not isinstance(pin["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", pin["version"]):
        raise SystemExit(f"{name}: invalid version")
    digest = pin["hash"]
    if not isinstance(digest, str) or not digest.startswith("sha256-"):
        raise SystemExit(f"{name}: expected sha256 SRI hash")
    try:
        raw = base64.b64decode(digest.removeprefix("sha256-"), validate=True)
    except binascii.Error as error:
        raise SystemExit(f"{name}: invalid SRI hash") from error
    if len(raw) != 32:
        raise SystemExit(f"{name}: sha256 digest must be 32 bytes")

print("Release pins have valid versions and SHA-256 SRI hashes.")
