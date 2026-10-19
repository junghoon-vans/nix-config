#!/usr/bin/env python3

import importlib.util
import re
import subprocess
from pathlib import Path

# Keep GitHub authentication and request handling consistent with release updates.
SPEC = importlib.util.spec_from_file_location(
    "fixed_release", Path(__file__).with_name("update-fixed-release.py")
)
fixed_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixed_release)


def stable_version(tag: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError(f"Expected a stable Hermes release tag, got {tag!r}")
    return tuple(map(int, tag[1:].split(".")))


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    flake = root / "flake.nix"
    content = flake.read_text()
    pattern = r'(hermes-agent\.url = "github:NousResearch/hermes-agent/)(v[0-9]+\.[0-9]+\.[0-9]+)(";)'
    pins = list(re.finditer(pattern, content))
    if len(pins) != 1:
        raise SystemExit("Expected exactly one stable Hermes input pin in flake.nix")
    current = pins[0].group(2)
    release = fixed_release.github_json("/repos/NousResearch/hermes-agent/releases/latest")
    tag = release["tag_name"]
    if release.get("draft") or release.get("prerelease"):
        raise SystemExit("Refusing a draft or prerelease Hermes release")
    if stable_version(tag) <= stable_version(current):
        print(current)
        return

    pin = pins[0]
    flake.write_text(content[:pin.start(2)] + tag + content[pin.end(2):])
    subprocess.run(["nix", "flake", "update", "hermes-agent"], cwd=root, check=True)
    print(tag)


if __name__ == "__main__":
    main()
