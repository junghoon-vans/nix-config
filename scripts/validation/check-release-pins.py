#!/usr/bin/env python3

import base64
import binascii
import json
import re
from pathlib import Path

pins = json.loads(Path("release-pins.json").read_text())
expected = {"agent-desktop", "apm", "bun", "gnomcp", "officecli", "omp", "paseo"}
if not isinstance(pins, dict) or pins.keys() != expected:
    raise SystemExit("release-pins.json must contain exactly the supported packages")

for name, pin in pins.items():
    fields = {"version", "hash", "skillHash"} if name == "officecli" else {"version", "hash"}
    if not isinstance(pin, dict) or pin.keys() != fields:
        raise SystemExit(f"{name}: expected {', '.join(sorted(fields))}")
    if not isinstance(pin["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", pin["version"]):
        raise SystemExit(f"{name}: invalid version")
    for field in fields - {"version"}:
        digest = pin[field]
        if not isinstance(digest, str) or not digest.startswith("sha256-"):
            raise SystemExit(f"{name}.{field}: expected sha256 SRI hash")
        try:
            raw = base64.b64decode(digest.removeprefix("sha256-"), validate=True)
        except binascii.Error as error:
            raise SystemExit(f"{name}.{field}: invalid SRI hash") from error
        if len(raw) != 32:
            raise SystemExit(f"{name}.{field}: sha256 digest must be 32 bytes")

print("Release pins have valid versions and SHA-256 SRI hashes.")
