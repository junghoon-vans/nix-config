#!/usr/bin/env python3
"""Collect pinned OMP/Hermes catalogs and Aside-only LIVE official catalog evidence.

--fixture-dir reads CLIENT/SOURCE_PATH instead of the network. Its output carries
an unconditional NONPRODUCTION error so update-models.py cannot consume it.
Source failures are recorded per client; a successful exit means a report was
written, not that every client has support evidence.
"""

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

from aside_model_catalog import collect_source as collect_aside


OMP_PATH = "packages/catalog/src/models.json"
HERMES_PATH = "hermes_cli/codex_models.py"
PROVIDER = "openai-codex"
TIMEOUT = 15
MAX_BYTES = 16 * 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def model_ids(values):
    if (not isinstance(values, list) or not values
            or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", v)
                   for v in values)):
        raise ValueError("expected non-empty explicit model ID list")
    if len(set(values)) != len(values):
        raise ValueError("duplicate model IDs")
    return sorted(values)


def parse_omp(text):
    """Compact catalog v1 ProviderRow/ModelRow IDs; no scanning of metadata.

    See the pinned packages/catalog/src/model-catalog-format.ts. Validate identity
    overrides in object nodes because the runtime spreads them over row IDs.
    Compat deltas do not affect model identity and are deliberately not decoded.
    """
    data = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("unsupported OMP compact catalog version")
    keys, nodes = data.get("keys"), data.get("nodes")
    shapes = data.get("booleanShapes")
    if (not isinstance(keys, list) or any(not isinstance(k, str) for k in keys)
            or len(set(keys)) != len(keys) or not isinstance(nodes, list)
            or not isinstance(shapes, list)):
        raise ValueError("invalid OMP catalog tables")

    def object_identity(ref):
        if (not isinstance(ref, list) or len(ref) != 1 or type(ref[0]) is not int
                or not 0 <= ref[0] < len(nodes)):
            raise ValueError("invalid OMP object reference")
        node = nodes[ref[0]]
        if (not isinstance(node, list) or len(node) != 4 or node[0] != 0
                or not isinstance(node[1], list) or len(node[1]) % 2
                or type(node[2]) is not int or not 0 <= node[2] < len(shapes)
                or not isinstance(node[3], list)):
            raise ValueError("invalid OMP object node")
        shape = shapes[node[2]]
        if not isinstance(shape, list):
            raise ValueError("invalid OMP boolean shape")
        identities = {}
        seen = set()
        for index in node[1][::2] + shape:
            if type(index) is not int or not 0 <= index < len(keys) or index in seen:
                raise ValueError("invalid or duplicate OMP property")
            seen.add(index)
        for index, value in zip(node[1][::2], node[1][1::2]):
            if keys[index] in {"id", "provider"}:
                if not isinstance(value, str):
                    raise ValueError("nonliteral OMP identity override")
                identities[keys[index]] = value
        if any(keys[index] in {"id", "provider"} for index in shape):
            raise ValueError("boolean OMP identity override")
        return identities

    providers = data.get("providers")
    if not isinstance(providers, list):
        raise ValueError("missing OMP provider rows")
    rows = []
    names = set()
    for row in providers:
        if (not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str)
                or row[0] in names):
            raise ValueError("invalid or duplicate OMP provider row")
        names.add(row[0])
        if row[0] == PROVIDER:
            rows.append(row)
    if len(rows) != 1:
        raise ValueError("missing explicit OMP openai-codex catalog")
    _, constants, models = rows[0]
    identity = object_identity(constants)
    if not isinstance(models, list):
        raise ValueError("invalid OMP model rows")
    ids = []
    for row in models:
        if not isinstance(row, list) or len(row) not in (2, 3):
            raise ValueError("invalid OMP model row")
        effective = {**identity, **object_identity(row[1])}
        if effective.get("id", row[0]) != row[0] or effective.get("provider", PROVIDER) != PROVIDER:
            raise ValueError("conflicting OMP model/provider identity")
        ids.append(row[0])
    return model_ids(ids)


def parse_hermes(text):
    """Read only the literal DEFAULT_CODEX_MODELS assignment; never execute Python."""
    tree = ast.parse(text)
    assignments = []
    for statement in tree.body:
        if isinstance(statement, ast.AnnAssign):
            targets, value = [statement.target], statement.value
        elif isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "DEFAULT_CODEX_MODELS" for t in targets):
            if len(targets) != 1:
                raise ValueError("aliased Hermes catalog assignment")
            assignments.append((targets[0], value))
    if len(assignments) != 1:
        raise ValueError("expected one literal DEFAULT_CODEX_MODELS assignment")
    target, value = assignments[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == target.id and isinstance(node.ctx, (ast.Store, ast.Del)) and node is not target:
            raise ValueError("reassigned Hermes catalog")
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == target.id and isinstance(node.ctx, (ast.Store, ast.Del)):
            raise ValueError("mutated Hermes catalog")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == target.id:
            raise ValueError("method call on Hermes catalog; mutation ambiguous")
    if not isinstance(value, ast.List) or any(not isinstance(v, ast.Constant) or not isinstance(v.value, str) for v in value.elts):
        raise ValueError("Hermes catalog is not a literal string list")
    return model_ids([v.value for v in value.elts])


def fetch(url):
    # Public pinned sources only: no credentials, account APIs, local caches or retries.
    request = urllib.request.Request(url, headers={"User-Agent": "static-model-support-collector"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("source exceeds size limit")
    return payload.decode("utf-8")


def collect(root, fixture_dir=None):
    evidence = {
        "schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
        "sources": [], "errors": [],
    }
    if fixture_dir is not None:
        evidence["errors"].append("NONPRODUCTION: local fixture sources; not valid update evidence")
    for client, path, parse in (("omp", OMP_PATH, parse_omp), ("hermes", HERMES_PATH, parse_hermes)):
        row = None
        try:
            if client == "omp":
                pins = json.loads((root / "release-pins.json").read_text(), object_pairs_hook=unique_object)
                version = pins["omp"]["version"]
                if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
                    raise ValueError("invalid pinned OMP release version")
                revision = "v" + version
                pin_revision = revision
                repo = "can1357/oh-my-pi"
                if fixture_dir is None:
                    commit = json.loads(fetch(f"https://api.github.com/repos/{repo}/commits/{revision}"), object_pairs_hook=unique_object)
                    revision = commit["sha"]
            else:
                lock = json.loads((root / "flake.lock").read_text(), object_pairs_hook=unique_object)
                pin = lock["nodes"]["hermes-agent"]["locked"]
                if (pin["type"], pin["owner"], pin["repo"]) != ("github", "NousResearch", "hermes-agent"):
                    raise ValueError("unsupported Hermes source pin")
                repo, revision = "NousResearch/hermes-agent", pin["rev"]
                pin_revision = revision
            if not (fixture_dir is not None and client == "omp") and (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)):
                raise ValueError("source revision is not a full commit SHA")
            url = f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"
            if fixture_dir is not None:
                local = (fixture_dir / client / path).resolve()
                url = local.as_uri()
            row = {
                "provider": PROVIDER, "client": client, "revision": revision,
                "pin_revision": pin_revision,
                "url": url, "kind": "static-catalog" if fixture_dir is None else "nonproduction-fixture",
                "role": "support", "models": [],
            }
            evidence["sources"].append(row)
            text = local.read_text() if fixture_dir is not None else fetch(url)
            row["models"] = parse(text)
        except (OSError, ValueError, KeyError, TypeError, SyntaxError, RecursionError) as error:
            message = f"{client}: static source unavailable or ambiguous: {error}"
            evidence["errors"].append(message)
            if row is not None:
                row["error"] = message
    if fixture_dir is not None:
        evidence["errors"].append("aside: LIVE catalog disabled in fixture mode")
    else:
        try:
            evidence["sources"].append(collect_aside())
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            evidence["errors"].append(f"aside: LIVE official catalog unavailable or ambiguous: {error}")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fixture-dir", type=Path, help="NONPRODUCTION: local CLIENT/SOURCE_PATH inputs; disables network")
    args = parser.parse_args()
    evidence = collect(args.root, args.fixture_dir)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    for error in evidence["errors"]:
        print(error)


if __name__ == "__main__":
    main()
