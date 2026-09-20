#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
GENERATED_TAG = re.compile(r"^agent-skills-[0-9a-f]{40}$")
GIT_LINE = re.compile(r"^\s+- git: https://github\.com/([^/]+/[^.]+)\.git$")
REF_LINE = re.compile(r"^(\s+ref: )(\S+)$")


def github_tags(repository: str) -> list[str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nix-config-updater"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/tags?per_page=100", headers=headers
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return [tag["name"] for tag in json.load(response)]


def latest_compatible_tag(current: str, tags: list[str]) -> str:
    if SEMVER.fullmatch(current):
        stable = [tag for tag in tags if SEMVER.fullmatch(tag)]
        return max(stable, key=lambda tag: tuple(map(int, SEMVER.fullmatch(tag).groups())))
    if GENERATED_TAG.fullmatch(current):
        return next(tag for tag in tags if GENERATED_TAG.fullmatch(tag))
    return current


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apm", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "apm.yml"
    lines = manifest_path.read_text().splitlines()
    repository = None
    tags_by_repository: dict[str, list[str]] = {}
    changed = False

    for index, line in enumerate(lines):
        if match := GIT_LINE.match(line):
            repository = match.group(1)
            continue
        if repository is None or not (match := REF_LINE.match(line)):
            continue
        current = match.group(2)
        if not (SEMVER.fullmatch(current) or GENERATED_TAG.fullmatch(current)):
            continue
        if repository not in tags_by_repository:
            tags_by_repository[repository] = github_tags(repository)
        tags = tags_by_repository[repository]
        latest = latest_compatible_tag(current, tags)
        if latest != current:
            lines[index] = f"{match.group(1)}{latest}"
            changed = True

    if changed:
        manifest_path.write_text("\n".join(lines) + "\n")
        subprocess.run([args.apm, "lock", "--update"], cwd=root, check=True)


if __name__ == "__main__":
    main()
