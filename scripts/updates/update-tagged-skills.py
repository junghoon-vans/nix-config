#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import yaml

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


def regenerate_lock(root: Path, apm: str) -> None:
    # Lock-only resolution preserves old deployment attestations. Materialize the
    # resolved payload in a fresh project and home so APM records portable hashes
    # of upstream bytes, never adopting workstation edits or ownership receipts.
    with tempfile.TemporaryDirectory(prefix=".apm-update-", dir=root) as directory:
        home = Path(directory)
        staging = home / "project"
        staging.mkdir()
        for name in ("apm.yml", "apm.lock.yaml"):
            shutil.copy2(root / name, staging / name)
        shutil.copytree(root / "skills", staging / "skills")
        environment = dict(os.environ, HOME=str(home))
        subprocess.run(
            [apm, "lock", "--update"],
            cwd=staging, env=environment, check=True,
        )
        resolved = yaml.safe_load((staging / "apm.lock.yaml").read_text())
        subprocess.run(
            [apm, "install", "--target", "agent-skills",
             "--only", "apm", "--trust-bin"],
            cwd=staging, env=environment, check=True,
        )
        materialized = yaml.safe_load((staging / "apm.lock.yaml").read_text())
        # User-scope authored content and executable approval are not owned by
        # this tagged-remote updater. Preserve their original portable state.
        def identity(dependency):
            return (dependency["repo_url"], dependency.get("virtual_path"),
                    dependency.get("alias"), dependency.get("local_path"))

        prior = {identity(dep): dep for dep in resolved["dependencies"]}
        local_owners = {
            dep["local_path"] for dep in resolved["dependencies"]
            if dep.get("source") == "local"
        }
        for index, dependency in enumerate(materialized["dependencies"]):
            previous = prior[identity(dependency)]
            if dependency.get("source") == "local":
                materialized["dependencies"][index] = previous
            elif "exec_status" in previous:
                dependency["exec_status"] = previous["exec_status"]
            else:
                dependency.pop("exec_status", None)
        materialized["deployments"] = [
            row for row in materialized.get("deployments", [])
            if not local_owners.intersection(row.get("owners", []))
        ] + [
            row for row in resolved.get("deployments", [])
            if local_owners.intersection(row.get("owners", []))
        ]
        (root / "apm.lock.yaml").write_text(
            yaml.safe_dump(materialized, sort_keys=False, allow_unicode=True)
        )


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
        regenerate_lock(root, args.apm)


if __name__ == "__main__":
    main()
