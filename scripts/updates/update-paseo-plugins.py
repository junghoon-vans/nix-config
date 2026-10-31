#!/usr/bin/env python3
"""Resolve immutable plugin sources; inspect data only, never execute plugin code.

Policy matches fixed-release updates: latest stable GitHub release where published,
otherwise default-branch HEAD for source-only plugins. Never move a pin backwards
or across divergent history. Unsupported manifest requirements fail closed.
"""

import argparse
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

TABLE_SPEC = importlib.util.spec_from_file_location(
    "version_table", Path(__file__).with_name("version_table.py")
)
VERSION_TABLE = importlib.util.module_from_spec(TABLE_SPEC)
TABLE_SPEC.loader.exec_module(VERSION_TABLE)

SHA = r"[0-9a-f]{40}"
HASH = r"sha256-[A-Za-z0-9+/]{43}="
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?")


def github(path):
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def version(value):
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError(f"unsupported version: {value}")
    major, minor, patch, prerelease = match.groups()
    # SemVer: numeric identifiers precede text; a stable version follows prereleases.
    identifiers = tuple((0, int(part)) if part.isdigit() else (1, part)
                        for part in prerelease.split(".")) if prerelease else ()
    return (int(major), int(minor), int(patch), prerelease is None, identifiers)


def compatible(manifest, plugin_id, paseo_version):
    if manifest.get("id") != plugin_id:
        raise ValueError(f"{plugin_id}: manifest id mismatch")
    requirements = manifest.get("requirements")
    if not isinstance(requirements, dict) or set(requirements) != {"paseo"}:
        raise ValueError(f"{plugin_id}: unsupported requirements: {requirements}")
    requirement = requirements["paseo"]
    if not isinstance(requirement, str) or not requirement.startswith(">="):
        raise ValueError(f"{plugin_id}: unsupported Paseo requirement: {requirement}")
    if version(paseo_version) < version(requirement[2:]):
        raise ValueError(f"{plugin_id}: requires Paseo {requirement}, pinned {paseo_version}")
    return requirement


def candidate(repository, current, api):
    # Query release metadata only; API errors must never enable branch fallback.
    result = api(f"repos/{repository}/releases?per_page=100")
    stable = [release for release in result if not release["draft"] and not release["prerelease"]]
    if stable:
        # GitHub /releases/latest excludes prereleases and selects the latest stable release.
        release = api(f"repos/{repository}/releases/latest")
        ref = release["tag_name"]
        policy = f"stable release {ref}"
    else:
        # Avoid silently treating a paginated release history as source-only.
        if len(result) == 100:
            raise ValueError(f"{repository}: release history exceeds one page; review policy")
        ref = api(f"repos/{repository}")["default_branch"]
        policy = f"default branch {ref} (no stable releases)"
    revision = api(f"repos/{repository}/commits/{quote(ref, safe='')}")["sha"]
    if not re.fullmatch(SHA, revision):
        raise ValueError(f"{repository}: invalid commit SHA")
    if revision != current:
        status = api(f"repos/{repository}/compare/{current}...{revision}")["status"]
        if status == "behind":
            return current, f"{policy}; retaining newer pin"
        if status != "ahead":
            raise ValueError(f"{repository}: candidate history is {status}")
    return revision, policy


def prefetch(url):
    result = subprocess.run(
        ["nix", "store", "prefetch-file", "--unpack", "--json", url],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    if not re.fullmatch(HASH, data["hash"]):
        raise ValueError("Nix returned an invalid SHA-256 hash")
    return data["hash"], Path(data["storePath"])


def source_file(source, relative):
    path = (source / relative).resolve()
    if not path.is_relative_to(source.resolve()) or not path.is_file():
        raise ValueError(f"missing or escaping plugin source file: {relative}")
    return path


def declarations(text):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate declaration key: {key}")
            result[key] = value
        return result

    plugins = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(plugins, dict):
        raise ValueError("plugin declarations must be an object")
    fields = {"source", "repository", "directory", "revision", "hash", "enabled"}
    for plugin_id, plugin in plugins.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", plugin_id):
            raise ValueError(f"invalid plugin id: {plugin_id}")
        if not isinstance(plugin, dict) or set(plugin) != fields:
            raise ValueError(f"{plugin_id}: unsupported declaration fields")
        if plugin["source"] != "github":
            raise ValueError(f"{plugin_id}: unsupported source: {plugin['source']}")
        for field, pattern in (
            ("repository", r"[A-Za-z0-9_-]+/[A-Za-z0-9_][A-Za-z0-9._-]*"),
            ("revision", SHA),
            ("hash", HASH),
        ):
            if not isinstance(plugin[field], str) or not re.fullmatch(pattern, plugin[field]):
                raise ValueError(f"{plugin_id}: invalid {field}")
        directory = plugin["directory"]
        if not isinstance(directory, str) or (
            directory and any(not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", part)
                              for part in directory.split("/"))
        ):
            raise ValueError(f"{plugin_id}: invalid directory")
        if not isinstance(plugin["enabled"], bool):
            raise ValueError(f"{plugin_id}: invalid enabled")
    return plugins


def update(root, dry_run=False, body_file=None, api=github, fetch=prefetch):
    declaration_file = root / "modules/paseo-plugins.json"
    original = declaration_file.read_text()
    plugins = declarations(original)
    paseo_version = json.loads((root / "release-pins.json").read_text())["paseo"]["version"]
    rows = []
    changed = False
    for plugin_id, plugin in plugins.items():
        repository, directory = plugin["repository"], plugin["directory"]
        current, old_hash = plugin["revision"], plugin["hash"]
        revision, policy = candidate(repository, current, api)
        url = f"https://github.com/{repository}/archive/{revision}.tar.gz"
        artifact_hash, source = fetch(url)
        if revision == current and artifact_hash != old_hash:
            raise ValueError(f"{plugin_id}: existing immutable source hash mismatch")
        manifest_path = source_file(source, str(Path(directory) / "paseo-plugin.json"))
        manifest = json.loads(manifest_path.read_text())
        requirement = compatible(manifest, plugin_id, paseo_version)
        for entry in ("index.server.ts", "index.client.tsx"):
            source_file(source, str(Path(directory) / entry))
        if revision != current:
            plugin.update(revision=revision, hash=artifact_hash)
            changed = True
        else:
            continue  # Validation still covers every plugin; the table lists changes only.
        rows.append({
            "dependency": plugin_id,
            "previous": f"revision {current}",
            "next": f"revision {revision}",
            "change": (
                f"Updated; {policy}; "
                f"Paseo requirement {requirement}; source hash {old_hash} → {artifact_hash}"
            ),
            "compare": f"https://github.com/{repository}/compare/{current}...{revision}",
        })
    body = "\n".join([
        "## Paseo plugin source updates", "",
        "Policy: latest stable GitHub release; default-branch HEAD only when no stable releases exist.",
        "Pins never move backwards or across divergent history. All sources remain full commit SHA + unpacked Nix SHA-256.",
        "", VERSION_TABLE.render_table(rows), "",
        f"Manifest IDs, source entrypoints and requirements checked against pinned Paseo {paseo_version}.",
        "Source inspection and hashing only; plugin code was not executed. Review and activation remain manual.", "",
    ])
    # Validate every candidate before modifying any tracked file.
    if changed and not dry_run:
        declaration_file.write_text(json.dumps(plugins, indent=2) + "\n")
    if body_file is not None:
        body_file.write_text(body)
    print(body, end="")
    print(f"{'Would update' if dry_run else 'Updated'} source pins" if changed else "No plugin source changes")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="inspect upstream without modifying pins")
    parser.add_argument("--body-file", type=Path)
    args = parser.parse_args()
    update(Path(__file__).resolve().parents[2], args.dry_run, args.body_file)


if __name__ == "__main__":
    main()
