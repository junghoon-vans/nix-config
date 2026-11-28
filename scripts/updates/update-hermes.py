#!/usr/bin/env python3

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

# Keep GitHub authentication and request handling consistent with release updates.
SPEC = importlib.util.spec_from_file_location(
    "fixed_release", Path(__file__).with_name("update-fixed-release.py")
)
fixed_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixed_release)

PNPM_DEPS = (
    ".#darwinConfigurations.junghoonui-MacBookAir.config"
    ".workstation.hermes.package.hermesNpmLib.pnpmDeps"
)
FAKE_HASH = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
SHA256 = r"sha256-[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]="


def stable_version(tag: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError(f"Expected a stable Hermes release tag, got {tag!r}")
    return tuple(map(int, tag[1:].split(".")))


def locked_revision(lock: Path, tag: str) -> str:
    graph = json.loads(lock.read_text())
    nodes = graph["nodes"]
    node = nodes[nodes[graph["root"]]["inputs"]["hermes-agent"]]
    source = node["locked"]
    rev = source["rev"]
    if (
        (source["type"], source["owner"], source["repo"]) != ("github", "NousResearch", "hermes-agent")
        or node["original"]["ref"] != tag
        or not re.fullmatch(r"[0-9a-f]{40}", rev)
    ):
        raise ValueError(f"Hermes lock does not identify an exact revision for {tag}")
    return rev


def probe_hash(root: Path, drv: str) -> str:
    if not re.fullmatch(r"/nix/store/[0-9a-z]{32}-[^/]+\.drv", drv):
        raise ValueError(f"Invalid Hermes pnpm dependency derivation path: {drv!r}")
    # Use Nix's error event for this exact probe, never builder log lines.
    result = subprocess.run(
        ["nix", "build", "--no-link", "--log-format", "internal-json", f"{drv}^out"],
        cwd=root, stderr=subprocess.PIPE, text=True, errors="replace",
    )
    pattern = (
        rf"error: hash mismatch in fixed-output derivation '{re.escape(drv)}':\n"
        rf" +specified: +{re.escape(FAKE_HASH)}\n +got: +({SHA256})"
    )
    errors = []
    for line in result.stderr.splitlines():
        if not line.startswith("@nix "):
            continue
        event = json.loads(line.removeprefix("@nix "))
        if event.get("action") == "msg" and event.get("level") == 0:
            message = re.sub(r"\x1b\[[0-9;]*m", "", event["msg"])
            # Determinate Nix can emit a separate failure marker for the same output.
            if message != f"❌ {drv}^out":
                errors.append(message)
    match = re.fullmatch(pattern, errors[0]) if len(errors) == 1 else None
    if result.returncode == 1 and match and match[1] != FAKE_HASH:
        return match[1]
    print(result.stderr, file=sys.stderr, end="")
    result.check_returncode()
    raise RuntimeError("Hermes pnpm probe unexpectedly built with the placeholder hash")


def update(root: Path) -> str:
    flake = root / "flake.nix"
    content = flake.read_text()
    pattern = r'(hermes-agent\.url = "github:NousResearch/hermes-agent/)(v[0-9]+\.[0-9]+\.[0-9]+)(";)'
    pins = list(re.finditer(pattern, content))
    if len(pins) != 1:
        raise SystemExit("Expected exactly one stable Hermes input pin in flake.nix")
    current = pins[0].group(2)
    release = fixed_release.github_json("/repos/NousResearch/hermes-agent/releases/latest")
    tag = release["tag_name"]
    if release.get("draft") or release.get("prerelease"):
        raise SystemExit("Refusing a draft or prerelease Hermes release")
    if stable_version(tag) <= stable_version(current):
        return current

    lock = root / "flake.lock"
    hashes = root / "modules/hermes-pnpm-hashes.json"
    baseline = {path: path.read_bytes() for path in (flake, lock, hashes)}
    try:
        pin = pins[0]
        flake.write_text(content[:pin.start(2)] + tag + content[pin.end(2):])
        subprocess.run(["nix", "flake", "update", "hermes-agent"], cwd=root, check=True)
        rev = locked_revision(lock, tag)
        # Vary only the expected hash so a cached upstream output cannot mask
        # a mismatch for the candidate's Darwin fetcher and workspace.
        deps = json.loads(subprocess.run(
            [
                "nix", "eval", "--no-write-lock-file", "--json", PNPM_DEPS,
                "--apply", "deps: { inherit (deps) outputHash; "
                f"probe = (deps.overrideAttrs {{ outputHash = \"{FAKE_HASH}\"; }}).drvPath; }}",
            ],
            cwd=root, check=True, stdout=subprocess.PIPE, text=True,
        ).stdout)
        actual = probe_hash(root, deps["probe"])
        if actual != deps["outputHash"]:
            overrides = json.loads(baseline[hashes])
            overrides[rev] = actual
            hashes.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n")
            print(f"Hermes {tag} ({rev}) requires Darwin pnpm hash {actual}", flush=True)
        subprocess.run(
            ["nix", "build", "--no-link", "--no-write-lock-file", PNPM_DEPS],
            cwd=root, check=True,
        )
    except BaseException:
        for path, original in baseline.items():
            if not path.exists() or path.read_bytes() != original:
                path.write_bytes(original)
        raise
    return tag


if __name__ == "__main__":
    print(update(Path(__file__).resolve().parents[2]))
