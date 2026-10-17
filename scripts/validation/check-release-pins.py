#!/usr/bin/env python3

import base64
import binascii
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

pins = json.loads(Path("release-pins.json").read_text())
expected = {"apm", "bun", "gnomcp", "hermes", "officecli", "omp", "paseo"}
if not isinstance(pins, dict) or pins.keys() != expected:
    raise SystemExit("release-pins.json must contain exactly the supported packages")

for name, pin in pins.items():
    fields = {"version", "url", "hash"} if name == "hermes" else {"version", "hash", "skillHash"} if name == "officecli" else {"version", "hash"}
    if not isinstance(pin, dict) or pin.keys() != fields:
        raise SystemExit(f"{name}: expected {', '.join(sorted(fields))}")
    if not isinstance(pin["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", pin["version"]):
        raise SystemExit(f"{name}: invalid version")
    if name == "hermes":
        url = pin["url"]
        try:
            parsed_url = urlsplit(url) if isinstance(url, str) else None
            valid_url = (
                parsed_url is not None
                and parsed_url.scheme == "https"
                and parsed_url.hostname == "hermes-assets.nousresearch.com"
                and parsed_url.port in (None, 443)
                and parsed_url.username is None
                and parsed_url.password is None
                and unquote(parsed_url.path.rsplit("/", 1)[-1]) == f"HermesBundled-{pin['version']}-mac-arm64.zip"
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise SystemExit(f"{name}.url: expected the Hermes macOS ARM64 ZIP on hermes-assets.nousresearch.com")
    algorithm = "sha512" if name == "hermes" else "sha256"
    digest_bytes = 64 if name == "hermes" else 32
    for field in fields - {"version", "url"}:
        digest = pin[field]
        if not isinstance(digest, str) or not digest.startswith(f"{algorithm}-"):
            raise SystemExit(f"{name}.{field}: expected {algorithm} SRI hash")
        try:
            raw = base64.b64decode(digest.removeprefix(f"{algorithm}-"), validate=True)
        except binascii.Error as error:
            raise SystemExit(f"{name}.{field}: invalid SRI hash") from error
        if len(raw) != digest_bytes:
            raise SystemExit(f"{name}.{field}: {algorithm} digest must be {digest_bytes} bytes")

print("Release pins have valid versions and SHA-256/SHA-512 SRI hashes.")
