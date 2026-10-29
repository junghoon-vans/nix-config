#!/usr/bin/env python3
"""Update Homebrew tap pins and compare versions of declared packages."""

import argparse
import json
import os
import re
from pathlib import Path
import subprocess


TAPS = {"homebrew-core": "Formula", "homebrew-cask": "Casks", "hashicorp-tap": "Formula"}


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


def inventory():
    result = subprocess.run(
        [
            "nix", "eval", "--impure", "--json", "--no-write-lock-file", "--expr",
            "import ./scripts/updates/homebrew-inventory.nix "
            "(builtins.getFlake (\"git+file:\" + toString ./. + \"?shallow=1\"))",
        ],
        check=True, stdout=subprocess.PIPE, text=True,
    )
    return json.loads(result.stdout)


def brew_environment():
    return {
        **os.environ,
        "HOMEBREW_DEVELOPER": "1",
        "HOMEBREW_NO_AUTO_UPDATE": "1",
        "HOMEBREW_NO_INSTALL_FROM_API": "1",
    }


def versions(tap, paths, brew="brew"):
    if not paths:
        return {}
    result = subprocess.run(
        [str(brew), "ruby", str(Path(__file__).with_name("homebrew-versions.rb"))],
        input=json.dumps({
            name: {"tap": tap, "path": str(path)} for name, path in paths.items()
        }),
        env=brew_environment(),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return json.loads(result.stdout)


def candidate_versions(tap, paths, brew):
    try:
        return versions(tap, paths, brew)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        message = (
            f"Unable to parse declared candidate packages from {tap} with the selected "
            "Homebrew runtime; update the brew-src pin to a compatible Homebrew version."
        )
        if detail:
            message += f"\n{detail.strip()}"
        raise RuntimeError(message) from error


def verify_brew_version(brew, lock):
    expected = lock["nodes"]["brew-src"]["original"]["ref"]
    try:
        result = subprocess.run(
            [str(brew), "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=brew_environment(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        message = f"Unable to query selected Homebrew runtime version via {brew} --version."
        if detail:
            message += f"\n{detail.strip()}"
        raise RuntimeError(message) from error
    match = re.search(r"^Homebrew (\S+)", result.stdout or "", re.MULTILINE)
    if match is None:
        raise RuntimeError(f"Unable to determine Homebrew runtime version from {brew} --version.")
    actual = match.group(1)
    if actual != expected:
        raise RuntimeError(
            f"Selected Homebrew runtime is {actual}, but flake.lock pins brew-src to "
            f"{expected}; update the brew-src pin to match before updating Homebrew taps."
        )
    return actual


def summarize(before, after, declared, brew="brew"):
    lines = [
        "## Homebrew tap update",
        "",
        "Updates only " + ", ".join(f"`{tap}`" for tap in TAPS) + " in `flake.lock`.",
        "Tables include only Homebrew packages declared by the Nix host configurations.",
        "Versions come from the pinned definitions, not the currently installed packages.",
        "Formula versions include Homebrew revisions (`_N`); cask versions target Apple Silicon.",
        "No local Homebrew update, upgrade, cleanup, or activation is performed.",
    ]
    candidate_packages_by_tap = {}
    candidate_versions_by_tap = {}
    for tap, directory in TAPS.items():
        source = prefetch(after["nodes"][tap]["locked"])
        candidate_packages = packages(source, directory)
        candidate_paths = {
            name: candidate_packages[name]
            for name in declared[tap]
            if name in candidate_packages
        }
        candidate_packages_by_tap[tap] = candidate_packages
        candidate_versions_by_tap[tap] = candidate_versions(tap, candidate_paths, brew)

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
        new_packages = candidate_packages_by_tap[tap]
        names = set(declared[tap])
        changed = sorted(
            name for name in names
            if name not in old_packages or name not in new_packages
            or old_packages[name].read_bytes() != new_packages[name].read_bytes()
        )
        if not changed:
            lines.extend(["", "No declared package changes."])
            continue
        old_versions = versions(
            tap,
            {name: old_packages[name] for name in changed if name in old_packages},
            brew,
        )
        new_versions = candidate_versions_by_tap[tap]
        lines.extend([
            "", "| Package | Before | After | Change |",
            "| --- | --- | --- | --- |",
        ])
        for name in changed:
            previous = old_versions.get(name)
            current = new_versions.get(name)
            if previous is None and current is None:
                change = "Unavailable in both pinned taps"
            elif previous is None:
                change = "Added"
            elif current is None:
                change = "Removed"
            elif previous == current:
                change = "Definition only (version unchanged)"
            else:
                change = "Version / revision"
            lines.append(
                f"| `{name}` | {f'`{previous}`' if previous is not None else '—'} "
                f"| {f'`{current}`' if current is not None else '—'} | {change} |"
            )
    lines.extend(["", "Review, merge, and workstation activation remain manual.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument(
        "--brew",
        default=os.environ.get("HOMEBREW_TEST_BREW", "brew"),
        help="Homebrew executable selected by the flake's brew-src pin",
    )
    args = parser.parse_args()
    lock = Path("flake.lock")
    before = json.loads(lock.read_text())
    try:
        verify_brew_version(args.brew, before)
    except RuntimeError as error:
        parser.error(str(error))
    subprocess.run(["nix", "flake", "update", *TAPS], check=True)
    after = json.loads(lock.read_text())
    try:
        body = summarize(before, after, inventory(), args.brew)
    except RuntimeError as error:
        parser.error(str(error))
    args.body_file.write_text(body)


if __name__ == "__main__":
    main()
