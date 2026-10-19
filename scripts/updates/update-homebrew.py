#!/usr/bin/env python3
"""Update only Homebrew tap pins and summarize changed package definitions."""

import argparse
import json
from pathlib import Path
import subprocess


TAPS = {"homebrew-core": "Formula", "homebrew-cask": "Casks"}


def prefetch(locked):
    reference = (
        f"github:{locked['owner']}/{locked['repo']}/{locked['rev']}"
        f"?narHash={locked['narHash']}"
    )
    result = subprocess.run(
        ["nix", "flake", "prefetch", "--json", reference],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return Path(json.loads(result.stdout)["storePath"])


def packages(source, directory):
    return {path.stem: path for path in (source / directory).rglob("*.rb")}


def summarize(before, after):
    lines = [
        "## Homebrew tap update",
        "",
        "Updates only `homebrew-core` and `homebrew-cask` in `flake.lock`.",
        "Package lists below compare Ruby package definitions, including version, revision,",
        "dependency, and metadata changes; they are not a list of installed-package upgrades.",
        "No local Homebrew update, upgrade, cleanup, or activation is performed.",
    ]
    for tap, directory in TAPS.items():
        old = before["nodes"][tap]["locked"]
        new = after["nodes"][tap]["locked"]
        lines.extend(["", f"### {tap}", ""])
        if old == new:
            lines.append("No changes.")
            continue
        url = f"https://github.com/{new['owner']}/{new['repo']}"
        lines.append(
            f"[{old['rev'][:12]} → {new['rev'][:12]}]"
            f"({url}/compare/{old['rev']}...{new['rev']})"
        )
        old_packages = packages(prefetch(old), directory)
        new_packages = packages(prefetch(new), directory)
        added = new_packages.keys() - old_packages.keys()
        removed = old_packages.keys() - new_packages.keys()
        changed = {
            name for name in old_packages.keys() & new_packages.keys()
            if old_packages[name].read_bytes() != new_packages[name].read_bytes()
        }
        for label, names in [("Changed", changed), ("Added", added), ("Removed", removed)]:
            lines.extend([
                "",
                f"**{label} ({len(names)})**: "
                + (", ".join(f"`{name}`" for name in sorted(names)) or "None."),
            ])
    lines.extend(["", "Review, merge, and workstation activation remain manual.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args()
    lock = Path("flake.lock")
    before = json.loads(lock.read_text())
    subprocess.run(["nix", "flake", "update", *TAPS], check=True)
    after = json.loads(lock.read_text())
    args.body_file.write_text(summarize(before, after))


if __name__ == "__main__":
    main()
