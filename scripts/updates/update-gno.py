#!/usr/bin/env python3

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "fixed_release", Path(__file__).with_name("update-fixed-release.py")
)
fixed_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixed_release)

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = {"gno": "gnolang/gno", "gnopls": "gnoverse/gnopls"}
FAKE_HASH = "sha256-" + "A" * 43 + "="


def pin(content: str, name: str, value: str | None = None) -> str:
    pattern = rf'(?m)^(  {re.escape(name)} = ")([^"]+)(";)$'
    matches = list(re.finditer(pattern, content))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} pin")
    match = matches[0]
    if value is None:
        return match[2]
    return content[:match.start(2)] + value + content[match.end(2):]


def latest_release(repository: str) -> tuple[str, str]:
    release = fixed_release.github_json(f"/repos/{repository}/releases/latest")
    tag = release["tag_name"]
    if release.get("draft") or release.get("prerelease") or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError(f"Expected a stable {repository} release, got {tag!r}")
    # Resolve the tag, never target_commitish (which can name a moving branch).
    commit = fixed_release.github_json(f"/repos/{repository}/commits/{tag}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"Invalid release commit: {commit!r}")
    return tag, commit


def expression(module: Path, selection: str) -> str:
    return f'''let
      flake = builtins.getFlake {json.dumps(str(ROOT))};
      pkgs = import flake.inputs.nixpkgs {{ system = "aarch64-darwin"; }};
      evaluated = pkgs.lib.evalModules {{
        specialArgs = {{ inherit pkgs; }};
        modules = [
          (builtins.toPath {json.dumps(str(module))})
          {{
            options.environment.systemPackages = pkgs.lib.mkOption {{
              type = pkgs.lib.types.listOf pkgs.lib.types.package;
            }};
            config.workstation.languages.gno.enable = true;
          }}
        ];
      }};
      packages = evaluated.config.environment.systemPackages;
    in {selection}'''


def build(module: Path, selection: str, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["nix", "build", "--impure", "--no-write-lock-file", "--no-link", "--json", "--expr", expression(module, selection)],
        cwd=ROOT, capture_output=True, text=True, check=check,
    )


def dependency_hash(module: Path, index: int) -> str:
    result = build(module, f"(builtins.elemAt packages {index}).goModules", check=False)
    # Only the deliberately fake dependency hash may fail. Network/compiler failures
    # must stop the update rather than become a new pin.
    hashes = re.findall(r"got:\s+(sha256-[A-Za-z0-9+/]{43}=)", result.stderr)
    if result.returncode == 0 or "hash mismatch in fixed-output derivation" not in result.stderr or len(hashes) != 1:
        raise RuntimeError(f"Could not resolve Go dependency hash:\n{result.stderr}")
    return hashes[0]


def main() -> None:
    path = ROOT / "modules/languages/gno.nix"
    original = path.read_text()
    content = original
    versions = []
    with tempfile.TemporaryDirectory() as directory:
        staging = Path(directory)
        module = staging / path.relative_to(ROOT)
        module.parent.mkdir(parents=True)
        # Nix resolves the install checker relative to the staged module.
        checker = staging / "scripts/validation/check-gnopls.py"
        checker.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / checker.relative_to(staging), checker)
        for index, (name, repository) in enumerate(PACKAGES.items()):
            tag, commit = latest_release(repository)
            versions.append(f"{name} {tag}")
            if pin(content, name + "Rev") == commit:
                continue
            url = f"https://github.com/{repository}/archive/{commit}.tar.gz"
            result = subprocess.run(
                ["nix", "store", "prefetch-file", "--unpack", "--json", url],
                capture_output=True, text=True, check=True,
            )
            content = pin(content, name + "Rev", commit)
            content = pin(content, name + "Hash", json.loads(result.stdout)["hash"])
            content = pin(content, name + "VendorHash", FAKE_HASH)
            module.write_text(content)
            content = pin(content, name + "VendorHash", dependency_hash(module, index))
        if content != original:
            module.write_text(content)
            # Build both tools against the shared GNOROOT before publishing any pins.
            result = build(module, "packages")
            for output in json.loads(result.stdout):
                binary_dir = Path(output["outputs"]["out"]) / "bin"
                for binary in ("gno", "gnokey", "gnopls"):
                    executable = binary_dir / binary
                    if executable.exists():
                        subprocess.run([str(executable), "version"], check=True, stdout=sys.stderr)
            path.write_text(content)
    print(", ".join(versions))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        raise
