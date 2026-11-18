#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from apm_lock import regenerate_lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apm", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    pinned_version = json.loads((root / "release-pins.json").read_text())["apm"]["version"]
    if pinned_version != args.version:
        raise SystemExit(
            f"selected APM version {args.version} does not match release pin {pinned_version}"
        )
    regenerate_lock(
        root,
        args.apm,
        update_dependencies=False,
        expected_apm_version=args.version,
    )


if __name__ == "__main__":
    main()
