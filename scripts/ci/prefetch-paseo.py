#!/usr/bin/env python3
"""Fetch the pinned Paseo asset through GitHub's API and verify it with Nix."""
import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def main():
    release = json.loads((ROOT / "release-pins.json").read_text())["paseo"]
    asset = f"Paseo-{release['version']}-arm64.dmg"
    with tempfile.TemporaryDirectory(prefix="paseo-ci-source-") as temporary:
        destination = Path(temporary) / asset
        subprocess.run(
            [
                "gh", "release", "download", f"v{release['version']}",
                "--repo", "getpaseo/paseo", "--pattern", asset,
                "--output", str(destination),
            ],
            check=True,
        )
        subprocess.run(
            [
                "nix", "store", "prefetch-file", "--name", asset,
                "--expected-hash", release["hash"], destination.as_uri(),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
