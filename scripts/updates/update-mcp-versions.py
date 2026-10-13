#!/usr/bin/env python3
"""Update supported MCP npm pins to newer, stable registry latest versions."""

import argparse
import importlib.util
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mcp_update_inputs", ROOT / "scripts/security/scan-mcp.py")
MCP_INPUTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP_INPUTS)
STABLE_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
MAX_METADATA_BYTES = 1024 * 1024


def stable_version(version):
    match = STABLE_RE.fullmatch(version) if isinstance(version, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def fetch_latest(package):
    encoded = urllib.parse.quote(package, safe="")
    request = urllib.request.Request(
        f"https://registry.npmjs.org/{encoded}/latest",
        headers={"Accept": "application/json", "User-Agent": "nix-config-mcp-updater"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError(f"{package}: registry metadata exceeds the size limit")
    return json.loads(content, object_pairs_hook=MCP_INPUTS.unique_object)


def update_configuration(text, fetch=fetch_latest):
    servers = MCP_INPUTS.parse_servers(text)
    config = json.loads(text, object_pairs_hook=MCP_INPUTS.unique_object)
    updates = []
    metadata = {}
    for name, server in servers.items():
        target = MCP_INPUTS.npm_target(server)
        if server.get("disabled", False) or target is None:
            continue
        package, current, _binary = target
        current_version = stable_version(current)
        if current_version is None:
            continue  # Experimental pins remain an explicit manual choice.
        if package not in metadata:
            metadata[package] = fetch(package)
        latest = metadata[package]
        if not isinstance(latest, dict) or latest.get("name") != package:
            raise ValueError(f"{package}: registry returned mismatched package metadata")
        version = latest.get("version")
        latest_version = stable_version(version)
        if latest_version is None or latest.get("deprecated"):
            raise ValueError(f"{package}: latest is not a supported, non-deprecated stable release")
        if latest_version <= current_version:
            continue
        old_spec, new_spec = f"{package}@{current}", f"{package}@{version}"
        args = config["mcpServers"][name]["args"]
        if server["command"] == "/bin/zsh":
            args[1] = MCP_INPUTS.FIRECRAWL_PREFIX + new_spec
        else:
            index = 1 if args[0] in {"-y", "--yes"} else 0
            if args[index] == old_spec:
                args[index] = new_spec
            else:
                args[index] = "--package=" + new_spec
        updates.append(f"{name}: {old_spec} -> {new_spec}")
    # No writes occur until every selected registry response has been validated.
    return (json.dumps(config, indent=2, ensure_ascii=False) + "\n" if updates else text), updates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / MCP_INPUTS.CONFIG_PATH)
    parser.add_argument("--check", action="store_true", help="Report available updates without writing the configuration")
    args = parser.parse_args()
    original = args.config.read_text()
    updated, changes = update_configuration(original, fetch_latest)
    if changes and not args.check:
        args.config.write_text(updated)
    for change in changes:
        print(change)
    if not changes:
        print("No supported stable npm MCP updates available.")


if __name__ == "__main__":
    main()
