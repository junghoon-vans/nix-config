"""Static Aside catalog evidence from the hash-verified, lock-pinned browser DMG.

Never executes the daemon or contacts a runtime model catalog. The evidence
establishes bundled support, not the independently updated installed daemon.
Linux extraction requires 7zz (7-Zip); macOS uses a read-only hdiutil mount.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

PROVIDER = "openai-codex"
CASK_PATH = "Casks/a/aside.rb"
MAX_ARTIFACT = 512 * 1024 * 1024
MAX_PARTITION = 2 * 1024 * 1024 * 1024
VERSION = r"[0-9]+(?:\.[0-9]+){3}"
SHA = r"[0-9a-f]{64}"


def fetch(url, limit=1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": "static-model-support-collector"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith("https://"):
            raise ValueError("insecure artifact redirect")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("artifact exceeds size limit")
    return data


def cask_identity(root):
    lock = json.loads((Path(root) / "flake.lock").read_text())
    pin = lock["nodes"]["homebrew-cask"]["locked"]
    if ((pin["type"], pin["owner"].lower(), pin["repo"]) !=
            ("github", "homebrew", "homebrew-cask") or
            not re.fullmatch(r"[0-9a-f]{40}", pin["rev"])):
        raise ValueError("unsupported homebrew-cask pin")
    return pin["rev"], f"https://raw.githubusercontent.com/homebrew/homebrew-cask/{pin['rev']}/{CASK_PATH}"


def parse_cask(text):
    def one(pattern):
        matches = re.findall(pattern, text, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("unsupported or ambiguous Aside cask metadata")
        return matches[0]
    one(r'^cask "(aside)" do$')
    one(r'^  arch (arm: "arm64", intel: "x64")$')
    version = one(r'^  version "(' + VERSION + r')"$')
    digest = one(r'^  sha256 arm:\s+"(' + SHA + r')",$')
    one(r'^  url "(https://releases\.aside\.com/dev-updater/Aside-#\{version\}-#\{arch\}\.dmg)"$')
    return {"browser_version": version, "artifact_sha256": digest,
            "url": f"https://releases.aside.com/dev-updater/Aside-{version}-arm64.dmg"}


def verify_hash(data, expected):
    if not isinstance(expected, str) or not re.fullmatch(SHA, expected):
        raise ValueError("invalid artifact SHA256")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("artifact SHA256 mismatch")


class LiteralParser:
    """Restricted minified-JS data literals, never eval/Node or downloaded code."""
    token = re.compile(r'\s*("(?:[^"\\]|\\.)*"|`[^`\\$]*`|[A-Za-z_$][\w$]*|-?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?|!0|!1|[{}\[\]:,])')

    def __init__(self, text):
        self.text, self.position = text, 0

    def next(self):
        match = self.token.match(self.text, self.position)
        if not match:
            raise ValueError("unsupported catalog literal")
        self.position = match.end()
        return match[1]

    def value(self, token=None, depth=0):
        if depth > 32:
            raise ValueError("catalog nesting too deep")
        token = token or self.next()
        if token in ("{", "["):
            result = {} if token == "{" else []
            close = "}" if token == "{" else "]"
            item = self.next()
            if item == close:
                return result
            while True:
                if isinstance(result, dict):
                    key = self.scalar(item)
                    if not isinstance(key, str) or key in result or self.next() != ":":
                        raise ValueError("duplicate or malformed catalog key")
                    result[key] = self.value(depth=depth + 1)
                else:
                    result.append(self.value(item, depth + 1))
                separator = self.next()
                if separator == close:
                    return result
                if separator != ",":
                    raise ValueError("malformed catalog literal")
                item = self.next()
        return self.scalar(token)

    @staticmethod
    def scalar(token):
        if token.startswith('"'):
            return json.loads(token)
        if token.startswith("`"):
            return token[1:-1]
        if token in ("!0", "true"):
            return True
        if token in ("!1", "false"):
            return False
        if token == "null":
            return None
        if re.fullmatch(r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?", token):
            return float(token)
        if re.fullmatch(r"[A-Za-z_$][\w$]*", token):
            return token
        raise ValueError("invalid catalog scalar")


def parse_catalog(binary):
    marker = b'openai_codex_default='
    starts = [m.end() for m in re.finditer(re.escape(marker), binary)]
    if len(starts) != 1:
        raise ValueError("missing or ambiguous explicit Codex catalog")
    parser = LiteralParser(binary[starts[0]:starts[0] + 1024 * 1024].decode("utf-8", errors="replace"))
    catalog = parser.value()
    rows = catalog.get("openai-codex-responses")
    if not isinstance(rows, dict) or not rows:
        raise ValueError("missing explicit Codex responses catalog")
    models = []
    for key, row in rows.items():
        if (not isinstance(row, dict) or row.get("provider") != PROVIDER or
                row.get("api") != "openai-codex-responses" or row.get("type") != "chat" or
                not isinstance(row.get("id"), str) or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", row["id"]) or
                key != "chat:" + row["id"]):
            raise ValueError("invalid provider-scoped chat catalog entry")
        models.append(row["id"])
    if len(set(models)) != len(models):
        raise ValueError("duplicate model ID")
    return sorted(models)


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=120, **kwargs)


def bundled_files(dmg, directory, version):
    base = f"Aside.app/Contents/Frameworks/Aside Framework.framework/Versions/{version}/Libraries/AsideDaemon/mac-arm64"
    names = [base + "/manifest.json", base + "/Aside Daemon.app/Contents/MacOS/aside-daemon"]
    if sys.platform == "darwin":
        mount = directory / "mount"
        mount.mkdir()
        run(["hdiutil", "attach", str(dmg), "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", str(mount)], stdout=subprocess.DEVNULL)
        try:
            return [(mount / name).read_bytes() for name in names]
        finally:
            run(["hdiutil", "detach", str(mount)], stdout=subprocess.DEVNULL)
    tool = shutil.which("7zz") or shutil.which("7z")
    if not tool:
        raise ValueError("Linux DMG extraction requires 7zz or 7z")

    def members(archive, archive_type):
        listing = run([tool, "l", "-slt", "-t" + archive_type, str(archive)],
                      capture_output=True, text=True).stdout
        entries = {}
        for block in listing.split("\n\n"):
            path = re.search(r"^Path = (.+)$", block, re.MULTILINE)
            size = re.search(r"^Size = ([0-9]+)$", block, re.MULTILINE)
            if path and size:
                if path[1] in entries:
                    raise ValueError("ambiguous archive member")
                entries[path[1]] = int(size[1])
        return entries

    def extract(archive, archive_type, member, entries, limit, destination):
        size = entries.get(member, 0)
        if not 0 < size <= limit:
            raise ValueError("invalid extracted artifact size")
        # stdout extraction never materializes untrusted paths or symlinks.
        # Spill the partition to disk rather than holding it in memory.
        with destination.open("wb") as output:
            run([tool, "x", "-so", "-sns-", "-t" + archive_type, str(archive), member],
                stdout=output, stderr=subprocess.PIPE)
        if destination.stat().st_size != size:
            raise ValueError("extracted artifact size mismatch")

    entries = members(dmg, "Dmg")
    partitions = [name for name in entries if name.endswith((".hfs", ".apfs"))]
    if len(partitions) != 1:
        raise ValueError("unsupported or ambiguous DMG partition")
    partition = directory / "partition.img"
    extract(dmg, "Dmg", partitions[0], entries, MAX_PARTITION, partition)
    archive_type = "APFS" if partitions[0].endswith(".apfs") else "HFS"
    listing = members(partition, archive_type)
    results = []
    for index, name in enumerate(names):
        matches = [member for member in listing if member == name or member.endswith("/" + name)]
        if len(matches) != 1:
            raise ValueError("missing or ambiguous bundled daemon member")
        destination = directory / f"member-{index}"
        extract(partition, archive_type, matches[0], listing,
                1024 * 1024 if index == 0 else MAX_ARTIFACT, destination)
        results.append(destination.read_bytes())
    return results


def collect(root, artifact_path=None):
    revision, cask_url = cask_identity(root)
    metadata = parse_cask(fetch(cask_url).decode("utf-8"))
    data = Path(artifact_path).read_bytes() if artifact_path else fetch(metadata["url"], MAX_ARTIFACT)
    if len(data) > MAX_ARTIFACT:
        raise ValueError("artifact exceeds size limit")
    verify_hash(data, metadata["artifact_sha256"])
    with tempfile.TemporaryDirectory(prefix="aside-dmg-") as temporary:
        directory = Path(temporary)
        dmg = directory / "Aside.dmg"
        dmg.write_bytes(data)
        manifest, binary = bundled_files(dmg, directory, metadata["browser_version"])
    daemon_version = json.loads(manifest)["version"]
    if not isinstance(daemon_version, str) or not re.fullmatch(VERSION, daemon_version):
        raise ValueError("invalid bundled daemon version")
    return {"provider": PROVIDER, "client": "aside", "role": "support",
            "kind": "static-dmg-catalog", "revision": revision, "pin_revision": revision,
            "cask_url": cask_url, **metadata, "daemon_version": daemon_version,
            "daemon_sha256": hashlib.sha256(binary).hexdigest(), "models": parse_catalog(binary)}


def validate_source(root, source):
    revision, cask_url = cask_identity(root)
    metadata = parse_cask(fetch(cask_url).decode("utf-8"))
    expected = {"provider": PROVIDER, "client": "aside", "role": "support",
                "kind": "static-dmg-catalog", "revision": revision, "pin_revision": revision,
                "cask_url": cask_url, **metadata}
    if any(source.get(key) != value for key, value in expected.items()):
        raise ValueError("aside: invalid pinned DMG provenance")
    if (not re.fullmatch(VERSION, str(source.get("daemon_version", ""))) or
            not re.fullmatch(SHA, str(source.get("daemon_sha256", "")))):
        raise ValueError("aside: invalid bundled daemon provenance")
