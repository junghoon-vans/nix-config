#!/usr/bin/env python3
"""Prefetch direct flat GitHub release sources using their evaluated Nix pins."""
import argparse
import glob
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", help="Nix installable containing a package or package list")
    args = parser.parse_args()
    nix_env = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    projection = Path(__file__).with_name("github-release-sources.nix").read_text()
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
        url = next(
            url for url in source["urls"]
            if urlsplit(url).netloc == "github.com" and "/releases/download/" in urlsplit(url).path
        )
        owner, repository, _, _, tag, asset = urlsplit(url).path.lstrip("/").split("/", 5)
        with tempfile.TemporaryDirectory(prefix="github-release-ci-") as temporary:
            destination = Path(temporary) / "asset"
            print(f"Prefetching {source['name']} from {owner}/{repository}", flush=True)
            subprocess.run(
                [
                    "gh", "release", "download", unquote(tag), "--repo", f"{owner}/{repository}",
                    "--pattern", glob.escape(unquote(asset)), "--output", str(destination),
                ],
                check=True,
            )
            result = subprocess.run(
                [
                    "nix", "store", "prefetch-file", "--json", "--name", source["name"],
                    "--hash-type", source["hashAlgo"], "--expected-hash", source["hash"],
                    destination.as_uri(),
                ],
                env=nix_env, stdout=subprocess.PIPE, text=True, check=True,
            )
            actual_path = json.loads(result.stdout)["storePath"]
            if actual_path != source["path"]:
                raise RuntimeError(f"Source store path mismatch: {actual_path} != {source['path']}")


if __name__ == "__main__":
    main()
