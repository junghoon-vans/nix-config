#!/usr/bin/env python3
import argparse
import base64
import binascii
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

SPECS = {
    "apm": ("microsoft/apm", "v", "apm-darwin-arm64.tar.gz", False),
    "bun": ("oven-sh/bun", "bun-v", "bun-darwin-aarch64.zip", True),
    "gnomcp": ("gnoverse/gno-mcp", "v", "gno-mcp_darwin_arm64.tar.gz", False),
    "officecli": ("iOfficeAI/OfficeCLI", "v", "officecli-mac-arm64", False),
    "omp": ("can1357/oh-my-pi", "v", "omp-darwin-arm64", False),
    "paseo": ("getpaseo/paseo", "v", "Paseo-{version}-arm64.dmg", False),
}

HERMES_FEED_URL = "https://hermes-assets.nousresearch.com/releases/darwin/stable/stable-mac.yml"
HERMES_ASSET_HOST = "hermes-assets.nousresearch.com"
HERMES_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]*\Z")
MAX_HERMES_FEED_BYTES = 1024 * 1024


def github_json(path: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nix-config-updater"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com{path}", headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)

def same_hermes_origin(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == HERMES_ASSET_HOST
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def parse_hermes_feed(document: str) -> dict[str, str]:
    import yaml

    try:
        feed = yaml.safe_load(document)
    except yaml.YAMLError as error:
        raise ValueError("Hermes stable feed is not valid YAML") from error
    if not isinstance(feed, dict):
        raise ValueError("Hermes stable feed must be a mapping")

    version = feed.get("version")
    if not isinstance(version, str) or not HERMES_VERSION_RE.fullmatch(version):
        raise ValueError("Hermes stable feed has an invalid version")
    files = feed.get("files")
    if not isinstance(files, list):
        raise ValueError("Hermes stable feed has no files list")

    asset_name = f"HermesBundled-{version}-mac-arm64.zip"
    matches = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        url = urljoin(HERMES_FEED_URL, item["url"])
        try:
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        except ValueError:
            continue
        if filename == asset_name:
            matches.append((item, url))
    if len(matches) != 1:
        raise ValueError(f"Hermes stable feed must contain exactly one {asset_name}")

    item, url = matches[0]
    if not same_hermes_origin(url):
        raise ValueError(f"Hermes stable feed URL must use HTTPS on {HERMES_ASSET_HOST}")
    digest = item.get("sha512")
    try:
        raw_digest = base64.b64decode(digest, validate=True)
    except (binascii.Error, TypeError) as error:
        raise ValueError(f"Hermes {asset_name} has an invalid SHA-512 digest") from error
    if len(raw_digest) != 64:
        raise ValueError(f"Hermes {asset_name} SHA-512 digest must be 64 bytes")

    return {"version": version, "url": url, "hash": f"sha512-{digest}"}


def fetch_hermes_pin() -> dict[str, str]:
    request = Request(HERMES_FEED_URL, headers={"User-Agent": "nix-config-updater"})
    with urlopen(request, timeout=30) as response:
        content = response.read(MAX_HERMES_FEED_BYTES + 1)
    if len(content) > MAX_HERMES_FEED_BYTES:
        raise ValueError("Hermes stable feed exceeds the size limit")
    return parse_hermes_feed(content.decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", choices=sorted((*SPECS, "hermes")))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "release-pins.json"
    manifest = json.loads(manifest_path.read_text())
    if args.package == "hermes":
        manifest["hermes"] = fetch_hermes_pin()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(manifest["hermes"]["version"])
        return

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
    if args.package == "officecli":
        skill_url = f"https://raw.githubusercontent.com/{repository}/{tag}/skills/officecli/SKILL.md"
        skill = subprocess.run(
            ["nix", "store", "prefetch-file", "--json", skill_url],
            check=True, capture_output=True, text=True,
        )
        manifest[args.package]["skillHash"] = json.loads(skill.stdout)["hash"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(version)


if __name__ == "__main__":
    main()
