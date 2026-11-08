#!/usr/bin/env python3
"""Prefetch direct GitHub sources by replaying their original Nix recipes."""
import argparse
import glob
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote, unquote, urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", help="Nix installable containing a package or package list")
    args = parser.parse_args()
    nix_env = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    projection = Path(__file__).with_name("github-sources.nix").read_text()
    recipe = Path(__file__).with_name("replay-github-source.nix")
    result = subprocess.run(
        ["nix", "eval", "--no-write-lock-file", "--json", "--apply", projection, args.packages],
        env=nix_env, stdout=subprocess.PIPE, text=True, check=True,
    )
    sources = {source["path"]: source for source in json.loads(result.stdout)}
    for source in sources.values():
        available = subprocess.run(
            ["nix", "path-info", source["path"]], env=nix_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if available.returncode == 0:
            print(f"Already available: {source['name']}", flush=True)
            continue
        url = source["urls"][0]
        owner, repository, kind, remainder = urlsplit(url).path.lstrip("/").split("/", 3)
        with tempfile.TemporaryDirectory(prefix="github-source-ci-") as temporary:
            destination = Path(temporary) / "asset"
            print(f"Prefetching {source['name']} from {owner}/{repository}", flush=True)
            if kind == "releases":
                _, tag, asset = remainder.split("/", 2)
                subprocess.run(
                    [
                        "gh", "release", "download", unquote(tag), "--repo", f"{owner}/{repository}",
                        "--pattern", glob.escape(unquote(asset)), "--output", str(destination),
                    ],
                    check=True,
                )
            else:
                extension = ".tar.gz" if remainder.endswith(".tar.gz") else ".zip"
                ref = remainder[:-len(extension)]
                asset = "source" + extension
                archive_format = "tarball" if extension == ".tar.gz" else "zipball"
                endpoint = f"repos/{owner}/{repository}/{archive_format}/{quote(unquote(ref), safe='')}"
                with destination.open("wb") as archive:
                    subprocess.run(["gh", "api", endpoint], stdout=archive, check=True)
            result = subprocess.run(
                ["nix", "store", "add-file", "--name", unquote(asset), str(destination)],
                env=nix_env, stdout=subprocess.PIPE, text=True, check=True,
            )
            archive_path = result.stdout.strip()
            replacement = (
                f"import {json.dumps(str(recipe))} {{ "
                f"sourcePath = {json.dumps(source['path'])}; "
                f"archivePath = {json.dumps(archive_path)}; }}"
            )
            result = subprocess.run(
                [
                    "nix", "eval", "--impure", "--no-write-lock-file", "--raw",
                    "--apply", replacement, args.packages,
                ],
                env=nix_env, stdout=subprocess.PIPE, text=True, check=True,
            )
            derivation = result.stdout.strip()
            result = subprocess.run(
                ["nix", "build", "--no-link", "--json", f"{derivation}^out"],
                env=nix_env, stdout=subprocess.PIPE, text=True, check=True,
            )
            actual_path = json.loads(result.stdout)[0]["outputs"]["out"]
            if actual_path != source["path"]:
                raise RuntimeError(f"Source store path mismatch: {actual_path} != {source['path']}")


if __name__ == "__main__":
    main()
