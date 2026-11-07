#!/usr/bin/env python3
"""Update configured OpenAI models from fresh static client-support evidence."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
from pathlib import Path

import aside_dmg
import yaml

MAX_EVIDENCE_AGE = timedelta(hours=48)
MAX_FUTURE_SKEW = timedelta(minutes=5)
OPENAI_PROVIDER = "openai-codex"
CLIENTS = {"omp", "hermes", "aside"}
UNSTABLE_SUFFIXES = {
    "alpha", "beta", "experimental", "exp", "latest", "premium", "preview", "unstable",
}
MODEL_PATTERNS = (
    re.compile(r"^gpt-(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?(?:-([a-z0-9]+(?:-[a-z0-9]+)*))?$"),
    re.compile(r"^o(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?(?:-([a-z0-9]+(?:-[a-z0-9]+)*))?$"),
)
TARGETS = {
    "omp": "home/.omp/agent/config.yml",
    "paseo": "home/.paseo/config.json",
    "hermes": "modules/hermes.nix",
    "aside": "modules/aside.nix",
}


class ModelReference:
    def __init__(self, path, location, start, end, value, model_id, prefix, suffix, client, encode):
        self.path = path
        self.location = location
        self.start = start
        self.end = end
        self.value = value
        self.model_id = model_id
        self.prefix = prefix
        self.suffix = suffix
        self.client = client
        self.encode = encode

    def replacement(self, model_id):
        return self.encode(self.prefix + model_id + self.suffix)


def model_family(model_id):
    """Return (base, numeric version, exact suffix) for supported stable IDs."""
    if not isinstance(model_id, str):
        return None
    for base, pattern in zip(("gpt", "o"), MODEL_PATTERNS):
        match = pattern.fullmatch(model_id)
        if not match:
            continue
        major, minor, suffix = match.groups()
        suffix_parts = suffix.split("-") if suffix else []
        if any(part in UNSTABLE_SUFFIXES for part in suffix_parts):
            return None
        return base, (int(major), int(minor or 0)), suffix or ""
    return None


def _reference_parts(value, client, owner=None, require_qualified=False):
    if not isinstance(value, str) or not value:
        return None
    prefix = ""
    model_value = value
    if "/" in value:
        provider, model_value = value.split("/", 1)
        if provider != OPENAI_PROVIDER or "/" in model_value:
            return None
        prefix = provider + "/"
    elif require_qualified or owner != OPENAI_PROVIDER:
        return None

    model_id, separator, option = model_value.partition(":")
    if not model_id or model_family(model_id) is None:
        return None
    suffix = (":" + option) if separator else ""
    return model_id, prefix, suffix


def _yaml_scalar_encoder(raw_token):
    if raw_token.startswith("'") and raw_token.endswith("'"):
        return lambda value: "'" + value.replace("'", "''") + "'"
    if raw_token.startswith('"') and raw_token.endswith('"'):
        return lambda value: json.dumps(value, ensure_ascii=False)
    return lambda value: value


def _yaml_mapping_entries(node):
    if not isinstance(node, yaml.MappingNode):
        return []
    return [
        (key.value, value)
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
    ]


def _collect_omp_yaml(path, text):
    try:
        document = yaml.compose(text)
    except yaml.YAMLError as error:
        raise ValueError(f"{path}: invalid YAML: {error}") from error
    role_nodes = [value for key, value in _yaml_mapping_entries(document) if key == "modelRoles"]
    if len(role_nodes) != 1 or not isinstance(role_nodes[0], yaml.MappingNode):
        raise ValueError(f"{path}: expected one modelRoles mapping")

    references = []
    for role, value in _yaml_mapping_entries(role_nodes[0]):
        if not isinstance(value, yaml.ScalarNode):
            continue
        parts = _reference_parts(value.value, "omp")
        if parts is None:
            continue
        model_id, prefix, suffix = parts
        raw_token = text[value.start_mark.index:value.end_mark.index]
        references.append(ModelReference(
            path, ("modelRoles", role), value.start_mark.index, value.end_mark.index,
            value.value, model_id, prefix, suffix, "omp", _yaml_scalar_encoder(raw_token),
        ))
    return references


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_tokens(text):
    """Map JSON value paths to their exact source string-token spans."""
    tokens = {}

    def whitespace(position):
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        return position

    def string_token(position):
        start = position
        position += 1
        while position < len(text):
            if text[position] == "\\":
                position += 2
            elif text[position] == '"':
                position += 1
                return json.loads(text[start:position]), start, position
            else:
                position += 1
        raise ValueError("unterminated JSON string")

    def value(position, path):
        position = whitespace(position)
        if position >= len(text):
            raise ValueError("unexpected end of JSON")
        if text[position] == '"':
            decoded, start, end = string_token(position)
            tokens[path] = (decoded, start, end)
            return end
        if text[position] == "{":
            position = whitespace(position + 1)
            if text[position] == "}":
                return position + 1
            while True:
                position = whitespace(position)
                key, _key_start, key_end = string_token(position)
                position = whitespace(key_end)
                if position >= len(text) or text[position] != ":":
                    raise ValueError("invalid JSON object")
                position = value(position + 1, path + (key,))
                position = whitespace(position)
                if position < len(text) and text[position] == "}":
                    return position + 1
                if position >= len(text) or text[position] != ",":
                    raise ValueError("invalid JSON object")
                position += 1
        if text[position] == "[":
            position = whitespace(position + 1)
            if text[position] == "]":
                return position + 1
            index = 0
            while True:
                position = value(position, path + (index,))
                position = whitespace(position)
                if position < len(text) and text[position] == "]":
                    return position + 1
                if position >= len(text) or text[position] != ",":
                    raise ValueError("invalid JSON array")
                position = whitespace(position + 1)
                index += 1
        start = position
        while position < len(text) and text[position] not in ",]} \t\r\n":
            position += 1
        if position == start:
            raise ValueError("invalid JSON value")
        return position

    value(0, ())
    return tokens


def _collect_paseo_json(path, text):
    try:
        config = json.loads(text, object_pairs_hook=_unique_object)
        tokens = _json_tokens(text)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(config, dict):
        raise ValueError(f"{path}: top-level JSON value must be an object")

    paths = []
    daemon = config.get("daemon", {})
    profiles = daemon.get("agentProfiles", []) if isinstance(daemon, dict) else []
    if isinstance(profiles, list):
        for index, profile in enumerate(profiles):
            if isinstance(profile, dict) and profile.get("provider") == "omp":
                profile_id = profile.get("id", index)
                paths.append((
                    ("daemon", "agentProfiles", index, "model"),
                    ("agentProfiles", str(profile_id), "model"),
                    profile.get("model"),
                ))

    agents = config.get("agents", {})
    providers = agents.get("providers", {}) if isinstance(agents, dict) else {}
    omp_provider = providers.get("omp", {}) if isinstance(providers, dict) else {}
    additional_models = omp_provider.get("additionalModels", []) if isinstance(omp_provider, dict) else []
    if isinstance(additional_models, list):
        for index, model in enumerate(additional_models):
            if isinstance(model, dict):
                identity = model.get("label", index)
                paths.append((
                    ("agents", "providers", "omp", "additionalModels", index, "id"),
                    ("additionalModels", str(identity), "id"),
                    model.get("id"),
                ))

    references = []
    for token_path, location, value in paths:
        if not isinstance(value, str):
            continue
        parts = _reference_parts(value, "omp")
        token = tokens.get(token_path)
        if parts is None or token is None or token[0] != value:
            continue
        model_id, prefix, suffix = parts
        _decoded, start, end = token
        references.append(ModelReference(
            path, location, start, end, value, model_id, prefix, suffix, "omp",
            lambda replacement: json.dumps(replacement, ensure_ascii=False),
        ))
    return references


def _skip_nix_string_or_comment(text, position):
    if text.startswith("/*", position):
        end = text.find("*/", position + 2)
        if end < 0:
            raise ValueError("unterminated Nix block comment")
        return end + 2
    if text[position] == "#":
        end = text.find("\n", position)
        return len(text) if end < 0 else end + 1
    if text.startswith("''", position):
        end = text.find("''", position + 2)
        if end < 0:
            raise ValueError("unterminated Nix indented string")
        return end + 2
    if text[position] == '"':
        position += 1
        while position < len(text):
            if text[position] == "\\":
                position += 2
            elif text[position] == '"':
                return position + 1
            else:
                position += 1
        raise ValueError("unterminated Nix string")
    return None


def _matching_nix_delimiter(text, opening, open_char, close_char):
    depth = 1
    position = opening + 1
    while position < len(text):
        skipped = _skip_nix_string_or_comment(text, position)
        if skipped is not None:
            position = skipped
            continue
        if text[position] == open_char:
            depth += 1
        elif text[position] == close_char:
            depth -= 1
            if depth == 0:
                return position
        position += 1
    raise ValueError(f"unclosed Nix {open_char}")


def _nix_string_references(path, block, block_start, client, owner, require_qualified, location):
    references = []
    for match in re.finditer(r'\bmodel\s*=\s*"([^"\\]*)"\s*;', block):
        value = match.group(1)
        parts = _reference_parts(value, client, owner=owner, require_qualified=require_qualified)
        if parts is None:
            continue
        model_id, prefix, suffix = parts
        references.append(ModelReference(
            path, location, block_start + match.start(1), block_start + match.end(1),
            value, model_id, prefix, suffix, client, lambda replacement: replacement,
        ))
    return references


def _explicit_hermes_model_owner(text):
    generated = re.search(r'\bhermesConfig\s*=\s*yaml\.generate\s+"[^"]+"\s+\{', text)
    if not generated:
        return False
    opening = text.find("{", generated.start(), generated.end())
    end = _matching_nix_delimiter(text, opening, "{", "}")
    body_start = opening + 1
    body = text[body_start:end]
    model = re.search(r"\bmodel\s*=\s*\{", body)
    if not model:
        return False
    model_opening = body.find("{", model.start(), model.end())
    model_end = _matching_nix_delimiter(body, model_opening, "{", "}")
    model_body = body[model_opening + 1:model_end]
    provider = re.search(r'\bprovider\s*=\s*"([^"\\]*)"\s*;', model_body)
    default_cfg = re.search(r"\bdefault\s*=\s*cfg\.model\s*;", model_body)
    return bool(provider and provider.group(1) == OPENAI_PROVIDER and default_cfg)


def _collect_hermes_nix(path, text):
    references = []
    if _explicit_hermes_model_owner(text):
        options = re.search(r"\boptions\.workstation\.hermes\s*=\s*\{", text)
        if options:
            opening = text.find("{", options.start(), options.end())
            end = _matching_nix_delimiter(text, opening, "{", "}")
            body_start = opening + 1
            options_body = text[body_start:end]
            model_option = re.search(r"\bmodel\s*=\s*lib\.mkOption\s*\{", options_body)
            if model_option:
                option_opening = options_body.find("{", model_option.start(), model_option.end())
                option_end = _matching_nix_delimiter(options_body, option_opening, "{", "}")
                option_body = options_body[option_opening + 1:option_end]
                default = re.search(r'\bdefault\s*=\s*"([^"\\]*)"\s*;', option_body)
                if default:
                    value = default.group(1)
                    parts = _reference_parts(value, "hermes", owner=OPENAI_PROVIDER)
                    if parts is not None:
                        model_id, prefix, suffix = parts
                        start = body_start + option_opening + 1 + default.start(1)
                        end = body_start + option_opening + 1 + default.end(1)
                        references.append(ModelReference(
                            path, ("hermes", "model.default"), start, end, value,
                            model_id, prefix, suffix, "hermes", lambda replacement: replacement,
                        ))

    model_map = re.search(r"\bbackends\.model_map\s*=\s*\{", text)
    if model_map:
        map_opening = text.find("{", model_map.start(), model_map.end())
        map_end = _matching_nix_delimiter(text, map_opening, "{", "}")
        map_body_start = map_opening + 1
        map_body = text[map_body_start:map_end]
        options = re.search(r"\boptions\s*=\s*\[", map_body)
        if options:
            list_opening = map_body.find("[", options.start(), options.end())
            list_end = _matching_nix_delimiter(map_body, list_opening, "[", "]")
            position = list_opening + 1
            option_index = 0
            while position < list_end:
                skipped = _skip_nix_string_or_comment(map_body, position)
                if skipped is not None:
                    position = skipped
                    continue
                if map_body[position] != "{":
                    position += 1
                    continue
                block_end = _matching_nix_delimiter(map_body, position, "{", "}")
                block = map_body[position + 1:block_end]
                provider = re.search(r'\bprovider\s*=\s*"([^"\\]*)"\s*;', block)
                name = re.search(r'\bname\s*=\s*"([^"\\]*)"\s*;', block)
                identity = name.group(1) if name else str(option_index)
                block_start = map_body_start + position + 1
                if provider:
                    provider_name = provider.group(1)
                    if provider_name == OPENAI_PROVIDER:
                        references.extend(_nix_string_references(
                            path, block, block_start, "hermes", OPENAI_PROVIDER, False,
                            ("delegation", identity, "model"),
                        ))
                    elif provider_name == "omp-acp":
                        references.extend(_nix_string_references(
                            path, block, block_start, "omp", "omp-acp", True,
                            ("delegation", identity, "model"),
                        ))
                option_index += 1
                position = block_end + 1
    return references


def _collect_aside_nix(path, text):
    helper = re.search(r"\bmodel\s*=\s*modelId\s*:\s*thinkingLevel\s*:\s*\{", text)
    if not helper:
        return []
    opening = text.find("{", helper.start(), helper.end())
    end = _matching_nix_delimiter(text, opening, "{", "}")
    body = text[opening + 1:end]
    provider = re.search(r'\bprovider\s*=\s*"([^"\\]*)"\s*;', body)
    if not provider or provider.group(1) != OPENAI_PROVIDER:
        return []
    references = []
    for match in re.finditer(
        r'\b([A-Za-z][A-Za-z0-9_-]*)\s*=\s*model\s+"([^"\\]+)"\s+"[^"\\]*"', text
    ):
        model_id = match.group(2)
        if model_family(model_id) is None:
            continue
        references.append(ModelReference(
            path, ("aside-model", match.group(1)), match.start(2), match.end(2),
            model_id, model_id, "", "", "aside", lambda replacement: replacement,
        ))
    return references


def _collect_references(root, text_overrides=None):
    paths = {name: root / relative for name, relative in TARGETS.items()}
    texts = {}
    for name, path in paths.items():
        if text_overrides is not None and name in text_overrides:
            texts[name] = text_overrides[name]
        else:
            texts[name] = path.read_text()
    references = []
    references.extend(_collect_omp_yaml(paths["omp"], texts["omp"]))
    references.extend(_collect_paseo_json(paths["paseo"], texts["paseo"]))
    references.extend(_collect_hermes_nix(paths["hermes"], texts["hermes"]))
    references.extend(_collect_aside_nix(paths["aside"], texts["aside"]))
    return paths, texts, references


def _evidence_datetime(value):
    if not isinstance(value, str):
        raise ValueError("evidence observed_at must be an ISO-8601 timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("evidence observed_at must be an ISO-8601 timestamp") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("evidence observed_at must include a timezone")
    return timestamp.astimezone(timezone.utc)


def _client_from_error(message):
    if not isinstance(message, str):
        return None
    match = re.match(r"\s*(?:[^:\s]+/)?([a-z0-9-]+)\s*:", message)
    if match and match.group(1) in CLIENTS:
        return match.group(1)
    return None


def validate_evidence(evidence, now=None):
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise ValueError("evidence schema_version must be 1")
    timestamp = _evidence_datetime(evidence.get("observed_at"))
    now = now or datetime.now(timezone.utc)
    age = now.astimezone(timezone.utc) - timestamp
    if age > MAX_EVIDENCE_AGE:
        raise ValueError("model support evidence is stale (older than 48 hours)")
    if age < -MAX_FUTURE_SKEW:
        raise ValueError("model support evidence is dated in the future")

    source_errors = {}
    global_errors = []
    errors = evidence.get("errors", [])
    if not isinstance(errors, list):
        raise ValueError("evidence errors must be a list")
    for error in errors:
        client = _client_from_error(error)
        if client:
            source_errors.setdefault((client, None), []).append(str(error))
        else:
            global_errors.append(str(error))
    if global_errors:
        raise ValueError("model support evidence contains errors: " + "; ".join(global_errors))

    sources = evidence.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("model support evidence has no sources")
    normalized = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("model support evidence has an invalid source")
        required = ("provider", "client", "revision", "url", "kind", "role")
        if any(not isinstance(source.get(key), str) or not source[key] for key in required):
            raise ValueError("model support evidence source is missing provider/client/revision/url/kind/role")
        if source["role"] not in {"support", "discovery"}:
            raise ValueError(f"{source['client']}: unsupported evidence role {source['role']}")
        models = source.get("models")
        if not isinstance(models, list) or any(not isinstance(model, str) or not model for model in models):
            raise ValueError(f"{source['client']}: source models must be non-empty strings")
        error = source.get("error")
        if error:
            source_errors.setdefault((source["client"], source["role"]), []).append(str(error))
        normalized.append({**source, "models": set(models)})
    return timestamp, normalized, source_errors


def bind_pinned_sources(root, sources, test_only_fixtures=False):
    """Accept exact catalogs only when their identity matches this checkout's pins."""
    pins = json.loads((root / "release-pins.json").read_text(), object_pairs_hook=_unique_object)
    lock = json.loads((root / "flake.lock").read_text(), object_pairs_hook=_unique_object)
    hermes = lock["nodes"]["hermes-agent"]["locked"]
    expected = {
        "omp": ("v" + pins["omp"]["version"], "can1357/oh-my-pi", "packages/catalog/src/models.json"),
        "hermes": (hermes["rev"], "NousResearch/hermes-agent", "hermes_cli/codex_models.py"),
    }
    if (hermes["type"], hermes["owner"], hermes["repo"]) != ("github", "NousResearch", "hermes-agent"):
        raise ValueError("unsupported Hermes source pin")
    seen = set()
    for source in sources:
        client = source["client"]
        if source.get("error"):
            continue
        if client in seen:
            raise ValueError(f"{client}: ambiguous duplicate catalog")
        seen.add(client)
        if source["provider"] != OPENAI_PROVIDER or source["role"] != "support":
            raise ValueError("unsupported static catalog identity")
        fixture = test_only_fixtures and source["kind"] == "nonproduction-fixture"
        if fixture:
            if not source["url"].startswith("file:"):
                raise ValueError("fixture catalog requires a file URL")
            continue
        if client == "aside":
            aside_dmg.validate_source(root, source)
            continue
        if client not in expected:
            raise ValueError("unsupported static catalog identity")
        pin, repo, path = expected[client]
        if source.get("pin_revision") != pin:
            raise ValueError(f"{client}: catalog does not match repository pin")
        revision = source["revision"]
        if (source["kind"] != "static-catalog" or not re.fullmatch(r"[0-9a-f]{40}", revision)
                or (client == "hermes" and revision != pin)
                or source["url"] != f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"):
            raise ValueError(f"{client}: invalid pinned catalog provenance")

def _sources_for(sources, client, role):
    return [
        source for source in sources
        if source["provider"] == OPENAI_PROVIDER
        and source["client"] == client
        and source["role"] == role
        and not source.get("error")
    ]


def _support_sets(sources, errors, clients):
    support = {}
    gaps = {}
    for client in sorted(clients):
        rows = _sources_for(sources, client, "support")
        client_errors = errors.get((client, "support"), []) + errors.get((client, None), [])
        if client_errors:
            gaps[client] = "support evidence error: " + "; ".join(client_errors)
        elif not rows:
            gaps[client] = "no pinned static support source"
        else:
            supported = set.intersection(*(source["models"] for source in rows))
            if supported:
                support[client] = supported
            else:
                gaps[client] = "pinned static support sources have no shared model IDs"
    return support, gaps


def _discovery_sets(sources, errors, clients):
    discovery = {}
    gaps = {}
    for client in sorted(clients):
        # An explicit pinned catalog is STATIC discovery as well as support;
        # no account availability or forward-compatibility synthesis is inferred.
        rows = _sources_for(sources, client, "support")
        client_errors = errors.get((client, "discovery"), []) + errors.get((client, None), [])
        if client_errors:
            gaps[client] = "discovery evidence error: " + "; ".join(client_errors)
        elif not rows:
            gaps[client] = "no static discovery source"
        else:
            discovery[client] = set.union(*(source["models"] for source in rows))
    return discovery, gaps


def _base_references(root, current_paths):
    root_commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return root_commit


def _read_base(root, base_ref, paths):
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    overrides = {}
    for name, path in paths.items():
        relative = path.relative_to(root).as_posix()
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}:{relative}"], cwd=root,
            capture_output=True, text=True,
        )
        if exists.returncode:
            overrides[name] = ""
            continue
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative}"], cwd=root,
            capture_output=True, text=True, check=True,
        )
        overrides[name] = result.stdout
    return overrides


def _changed_references(root, current_references, base_references):
    base = {
        (reference.path.relative_to(root).as_posix(), reference.location): reference.model_id
        for reference in base_references
    }
    return [
        reference for reference in current_references
        if base.get((reference.path.relative_to(root).as_posix(), reference.location)) != reference.model_id
    ]


def _status_for(model_id, client, support, support_gaps):
    if client not in support:
        return support_gaps.get(client, "no pinned static support source")
    if model_id not in support[client]:
        return "not listed by the pinned static support source"
    return None


def _updates_for(references, support, support_gaps, discovery, discovery_gaps):
    consumers_by_model = {}
    for reference in references:
        consumers_by_model.setdefault(reference.model_id, set()).add(reference.client)

    replacements = {}
    blocked = []
    for current in sorted(consumers_by_model):
        family = model_family(current)
        clients = consumers_by_model[current]
        found_discovery = set.union(*(discovery[client] for client in clients if client in discovery)) if any(
            client in discovery for client in clients
        ) else set()
        eligible = []
        for candidate in found_discovery:
            candidate_family = model_family(candidate)
            if not candidate_family or (candidate_family[0], candidate_family[2]) != (family[0], family[2]):
                continue
            if candidate_family[1] > family[1]:
                eligible.append((candidate_family[1], candidate))
        if not eligible:
            missing_discovery = [discovery_gaps[client] for client in sorted(clients) if client in discovery_gaps]
            if missing_discovery:
                blocked.append(f"{current}: successors blocked: {'; '.join(missing_discovery)}")
            continue

        newest_version = max(version for version, _candidate in eligible)
        newest = sorted(candidate for version, candidate in eligible if version == newest_version)
        if len(newest) != 1:
            blocked.append(f"{current}: ambiguous same-family successors at numeric version {newest_version}")
            continue
        candidate = newest[0]
        unsupported = []
        for client in sorted(clients):
            status = _status_for(candidate, client, support, support_gaps)
            if status:
                unsupported.append(f"{client}: {status}")
        if unsupported:
            blocked.append(f"{current} → {candidate}: blocked by " + "; ".join(unsupported))
            continue
        replacements[current] = candidate
    return replacements, blocked


def _render_text(original, references, replacements):
    edits = []
    for reference in references:
        replacement = replacements.get(reference.model_id)
        if replacement is not None:
            edits.append((reference.start, reference.end, reference.replacement(replacement)))
    result = original
    previous_start = len(original) + 1
    for start, end, replacement in sorted(edits, reverse=True):
        if end > previous_start:
            raise ValueError("overlapping model reference edits")
        result = result[:start] + replacement + result[end:]
        previous_start = start
    return result


def _unsupported_current(references, support, support_gaps):
    gaps = []
    seen = set()
    for reference in references:
        key = (reference.model_id, reference.client)
        if key in seen:
            continue
        seen.add(key)
        status = _status_for(reference.model_id, reference.client, support, support_gaps)
        if status:
            gaps.append(f"{reference.model_id} ({reference.client}): {status}")
    return gaps


def _report(root, sources, errors, references, support, support_gaps, replacements, blocked, check, base_ref):
    report = ["## OpenAI model support updates", ""]
    if check:
        scope = f"changed or newly added references from `{base_ref}`" if base_ref else "all configured references"
        report.extend([f"Check mode validated {scope}; no configuration files were changed.", ""])
    elif replacements:
        report.extend(["Configured model updates:", ""])
        report.extend(f"- `{old}` → `{new}`" for old, new in sorted(replacements.items()))
        report.append("")
    else:
        report.extend(["No supported same-family successor updates were applied.", ""])

    if references:
        report.extend(["Watched OpenAI model families:", ""])
        grouped = {}
        for reference in references:
            grouped.setdefault(reference.model_id, set()).add(reference.client)
        for model_id, clients in sorted(grouped.items()):
            base, _version, suffix = model_family(model_id)
            label = base + (f" suffix `{suffix}`" if suffix else " base family")
            report.append(f"- `{model_id}`: {label}; consumers: {', '.join(sorted(clients))}")
        report.append("")

    current_gaps = _unsupported_current(references, support, support_gaps)
    if current_gaps:
        report.extend(["Current static-support gaps (advisory unless this reference changed in check mode):", ""])
        report.extend(f"- {gap}" for gap in current_gaps)
        report.append("")
    if blocked:
        report.extend(["Successors not applied:", ""])
        report.extend(f"- {reason}" for reason in blocked)
        report.append("")

    report.extend(["Static support evidence sources:", ""])
    relevant_clients = {reference.client for reference in references}
    relevant_sources = [
        source for source in sources
        if source["provider"] == OPENAI_PROVIDER and source["client"] in relevant_clients
    ]
    for source in sorted(relevant_sources, key=lambda row: (row["client"], row["role"], row["url"], row["revision"])):
        suffix = f"; error: {source['error']}" if source.get("error") else ""
        details = ""
        if source["client"] == "aside" and source["kind"] == "static-dmg-catalog":
            details = (
                f"; DMG version `{source['browser_version']}` sha256 `{source['artifact_sha256']}`; "
                f"Homebrew cask `{source['cask_url']}`; daemon `{source['daemon_version']}` "
                f"(binary sha256 `{source['daemon_sha256']}`)"
            )
        report.append(
            f"- STATIC `{source['client']}` {source['role']} ({source['kind']}): {source['url']} "
            f"(pinned revision `{source['revision']}`){details}{suffix}"
        )
    if not relevant_sources:
        report.append("- No client source records are available.")
    for (client, role), messages in sorted(errors.items(), key=lambda pair: (pair[0][0], str(pair[0][1]))):
        report.append(f"- `{client}` {role or 'source'} evidence error: {'; '.join(messages)}")
    for client, reason in sorted(support_gaps.items()):
        report.append(f"- `{client}` support: {reason}")
    report.extend([
        "",
        "This is static client-support evidence only. Live account availability and inference behavior were NOT VERIFIED.",
        "Review the configuration diff and manually merge after validation.",
    ])
    return report


def update(root, evidence_path, body_file, check=False, base_ref=None, now=None, test_only_fixtures=False):
    evidence = json.loads(evidence_path.read_text(), object_pairs_hook=_unique_object)
    if test_only_fixtures:
        evidence["errors"] = [error for error in evidence.get("errors", [])
                              if not error.startswith("NONPRODUCTION:")]
    _observed_at, sources, source_errors = validate_evidence(evidence, now=now)
    bind_pinned_sources(root, sources, test_only_fixtures)
    paths, texts, references = _collect_references(root)
    base_ref_names = None
    if base_ref:
        base_texts = _read_base(root, base_ref, paths)
        _base_paths, _base_texts, base_references = _collect_references(root, base_texts)
        base_ref_names = base_ref
    else:
        base_references = []

    relevant_references = references
    if check and base_ref:
        relevant_references = _changed_references(root, references, base_references)
    required_clients = {reference.client for reference in references}
    support, support_gaps = _support_sets(sources, source_errors, required_clients)
    discovery, discovery_gaps = _discovery_sets(sources, source_errors, required_clients)

    if check:
        failures = []
        for reference in relevant_references:
            status = _status_for(reference.model_id, reference.client, support, support_gaps)
            if status:
                failures.append(f"{reference.model_id} ({reference.client}): {status}")
        if failures:
            raise ValueError("changed configured model IDs lack exact static support: " + "; ".join(failures))
        replacements, blocked = {}, []
    else:
        replacements, blocked = _updates_for(references, support, support_gaps, discovery, discovery_gaps)

    changed_files = {}
    if not check:
        for name, path in paths.items():
            file_references = [reference for reference in references if reference.path == path]
            changed = _render_text(texts[name], file_references, replacements)
            if changed != texts[name]:
                changed_files[path] = changed

    report = _report(
        root, sources, source_errors, references, support, support_gaps,
        replacements, blocked, check, base_ref_names,
    )
    if test_only_fixtures:
        report.insert(0, "NONPRODUCTION: test-only fixture evidence; do not publish or merge.\n")
    # Configuration changes are prepared only after all evidence and reference
    # checks are complete; body output remains separate from managed settings.
    for path, content in changed_files.items():
        path.write_text(content)
    body_file.write_text("\n".join(report) + "\n")
    return changed_files, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="repository root")
    parser.add_argument("--evidence", required=True, type=Path, help="support evidence JSON")
    parser.add_argument("--body-file", required=True, type=Path, help="write the English update report here")
    parser.add_argument("--check", action="store_true", help="validate model support without changing configs")
    parser.add_argument("--base-ref", help="check only newly added or changed model references versus this git commit")
    parser.add_argument("--test-only-fixtures", action="store_true",
                        help="NONPRODUCTION: allow local collector fixtures; never use in automation")
    args = parser.parse_args()
    if args.base_ref and not args.check:
        parser.error("--base-ref requires --check")
    try:
        update(args.root, args.evidence, args.body_file, check=args.check, base_ref=args.base_ref,
               test_only_fixtures=args.test_only_fixtures)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        message = detail.strip() if detail else str(error)
        raise SystemExit(message) from error


if __name__ == "__main__":
    main()
