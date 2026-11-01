#!/usr/bin/env python3
"""Stage, build and smoke-check compatible upstream pins; never activate an app."""

import ast
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SPEC = importlib.util.spec_from_file_location(
    "fixed_release", Path(__file__).with_name("update-fixed-release.py")
)
fixed_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixed_release)
ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "betive37/mac-kakaotalk-adblock"
PACKAGE = Path("packages/kakaotalk-patcher.nix")


def pin(content, name, value=None):
    matches = list(re.finditer(rf'(?m)^( +{re.escape(name)} = ")([^"\n]+)(";)$', content))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} pin")
    match = matches[0]
    if value is None:
        return match[2]
    return content[:match.start(2)] + value + content[match.end(2):]


def prefetch(revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Invalid upstream commit: {revision!r}")
    result = subprocess.run(
        ["nix", "store", "prefetch-file", "--unpack", "--json",
         f"https://github.com/{REPOSITORY}/archive/{revision}.tar.gz"],
        check=True, capture_output=True, text=True,
    )
    source = json.loads(result.stdout)
    if not re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", source["hash"]):
        raise ValueError("Invalid Nix source hash")
    return source["hash"], Path(source["storePath"])


def target_contract(source):
    # Inspect syntax only: do not import unreviewed upstream on the host runner.
    tree = ast.parse((source / "patch_kakaotalk.py").read_text())
    targets = [node.value for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(item, ast.Name) and item.id == "TARGET" for item in node.targets)]
    if len(targets) != 1 or not isinstance(targets[0], ast.Call):
        raise ValueError("Unsupported upstream TARGET contract; manual integration required")
    return ast.dump(targets[0], include_attributes=False)


def check_candidate(content):
    # A temporary package tree avoids publishing failed candidates or relying on
    # untracked flake files. Local adapter tests run in the Nix build sandbox.
    with tempfile.TemporaryDirectory(prefix="kakaotalk-update-") as directory:
        staging = Path(directory)
        (staging / "packages").mkdir()
        (staging / PACKAGE).write_text(content)
        shutil.copytree(ROOT / "patches/kakaotalk", staging / "patches/kakaotalk")
        expression = f'''let
          flake = builtins.getFlake {json.dumps(str(ROOT))};
          pkgs = import flake.inputs.nixpkgs {{ system = "aarch64-darwin"; }};
        in pkgs.callPackage (builtins.toPath {json.dumps(str(staging / PACKAGE))}) {{}}'''
        result = subprocess.run(
            ["nix", "build", "--impure", "--no-write-lock-file", "--no-link", "--json", "--expr", expression],
            check=True, capture_output=True, text=True,
        )
        package = Path(json.loads(result.stdout)[0]["outputs"]["out"])
        for executable in ("kakaotalk-patcher", "kakaotalk-activate"):
            subprocess.run([str(package / "bin" / executable), "--help"], check=True)


def update():
    path = ROOT / PACKAGE
    original = path.read_text()
    old_revision = pin(original, "rev")
    metadata = fixed_release.github_json(f"/repos/{REPOSITORY}")
    branch = metadata["default_branch"]
    from urllib.parse import quote
    revision = fixed_release.github_json(f"/repos/{REPOSITORY}/commits/{quote(branch, safe='')}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Invalid upstream commit: {revision!r}")
    if revision == old_revision:
        print(f"KakaoTalk patcher already pinned at {revision}; no changes")
        return
    # Refuse force-pushed/divergent histories rather than silently downgrading.
    comparison = fixed_release.github_json(f"/repos/{REPOSITORY}/compare/{old_revision}...{revision}")
    if comparison["status"] != "ahead":
        raise ValueError("Upstream is not ahead of the reviewed pin; manual review required")
    old_hash, old_source = prefetch(old_revision)
    if old_hash != pin(original, "hash"):
        raise ValueError("Reviewed source hash does not match; refusing update")
    new_hash, new_source = prefetch(revision)
    if target_contract(old_source) != target_contract(new_source):
        raise ValueError("Upstream supported version/build/binary hashes or patch specification changed; manual adapter integration required (pins unchanged)")
    version = pin(original, "version")
    if not version.endswith("-" + old_revision[:7]):
        raise ValueError("Unexpected package version; manual integration required")
    candidate = pin(original, "rev", revision)
    candidate = pin(candidate, "hash", new_hash)
    candidate = pin(candidate, "version", version[:-7] + revision[:7])
    check_candidate(candidate)
    # No tracked file is changed until every build/check/help command succeeds.
    path.write_text(candidate)
    print(f"Validated KakaoTalk patcher: {old_revision} -> {revision}; {new_hash}. Manual review and activation required; existing patched apps require explicit rollback first.")


if __name__ == "__main__":
    try:
        update()
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        raise
