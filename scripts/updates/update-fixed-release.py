#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

SPECS = {
    "apm": ("microsoft/apm", "v", "apm-darwin-arm64.tar.gz", False),
    "bun": ("oven-sh/bun", "bun-v", "bun-darwin-aarch64.zip", True),
    "gnomcp": ("gnoverse/gno-mcp", "v", "gno-mcp_darwin_arm64.tar.gz", False),
    "omp": ("can1357/oh-my-pi", "v", "omp-darwin-arm64", False),
    "paseo": ("getpaseo/paseo", "v", "Paseo-{version}-arm64.dmg", False),
}


def github_json(path: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nix-config-updater"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", choices=sorted(SPECS))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "release-pins.json"
    manifest = json.loads(manifest_path.read_text())
    repository, tag_prefix, asset_template, unpack = SPECS[args.package]
    release = github_json(f"/repos/{repository}/releases/latest")
    tag = release["tag_name"]
    if not tag.startswith(tag_prefix):
        raise SystemExit(f"unexpected {repository} release tag: {tag}")
    version = tag.removeprefix(tag_prefix)
    asset_name = asset_template.format(version=version)
    try:
        url = next(asset["browser_download_url"] for asset in release["assets"] if asset["name"] == asset_name)
    except StopIteration as error:
        raise SystemExit(f"release {tag} has no {asset_name} asset") from error

    result = subprocess.run(
        ["nix", "store", "prefetch-file", "--json", url],
        check=True,
        capture_output=True,
        text=True,
    )
    prefetched = json.loads(result.stdout)
    artifact_hash = prefetched["hash"]
    if unpack:
        with tempfile.TemporaryDirectory() as temporary_directory:
            unpacked = Path(temporary_directory) / "unpacked"
            unpacked.mkdir()
            subprocess.run(
                ["unzip", "-qq", prefetched["storePath"], "-d", unpacked],
                check=True,
            )
            subprocess.run(["chmod", "-R", "+w", unpacked], check=True)
            artifact_hash = subprocess.run(
                ["nix", "hash", "path", unpacked],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

    manifest[args.package] = {"version": version, "hash": artifact_hash}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(version)


if __name__ == "__main__":
    main()
