"""Fail-closed static transport proof for the pinned Paseo OMP adapter.

This proves only source-level adapter/transport behavior. Model IDs are populated
by the collector from the intersection with the pinned external OMP catalog.
"""

import base64
import hashlib
import json
from pathlib import Path
import re


PROVIDER = "openai-codex"
CLIENT = "paseo"
API_BASE = "https://api.github.com/repos/getpaseo/paseo"
RAW_BASE = "https://raw.githubusercontent.com/getpaseo/paseo"
PASEO_SOURCE_DIR = "packages/server/src/server/agent/providers/omp"
SOURCE_TIER = "observed-pinned-release-source"
VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
SRI_PATTERN = re.compile(r"sha256-([A-Za-z0-9+/]{43}=)\Z")

# Required source facts are intentionally narrow. Paseo reports model choices
# dynamically; this module never supplies or infers a supported-model list.
_SOURCE_CHECKS = {
    "provider-config.ts": (
        ("export const OmpProviderOptionsSchema = z .object({", "provider options are a Zod object"),
        ("smolModel: z.string().min(1).optional(),", "smolModel is an exact nonempty string"),
        ("slowModel: z.string().min(1).optional(),", "slowModel is an exact nonempty string"),
        ("planModel: z.string().min(1).optional(),", "planModel is an exact nonempty string"),
        (".strict();", "unknown provider options are rejected"),
        ("args.push(\"--smol\", modelRoles.smolModel);", "smol role value is passed to OMP"),
        ("args.push(\"--slow\", modelRoles.slowModel);", "slow role value is passed to OMP"),
        ("args.push(\"--plan\", modelRoles.planModel);", "plan role value is passed to OMP"),
    ),
    "map-omp-model.ts": (
        ("id: `${model.provider}/${model.id}`,", "provider/model identity is composed without a catalog"),
        ("metadata: { provider: model.provider, modelId: model.id, },", "provider and model ID remain separately available"),
    ),
    "cli-runtime.ts": (
        (
            'const DEFAULT_OMP_COMMAND: [string, ...string[]] = [process.env.OMP_COMMAND ?? "omp"];',
            "default transport launches the external omp executable",
        ),
        (
            'await this.request({ type: "get_available_models" }, timeoutMs),',
            "model discovery comes from external OMP at runtime",
        ),
        ("return data.models ?? [];", "Paseo returns OMP models without a static catalog"),
        (
            'return OmpModelSchema.parse(await this.request({ type: "set_model", provider, modelId }));',
            "provider and modelId are sent unchanged in set_model",
        ),
        ('await this.request({ type: "set_thinking_level", level });', "effort is forwarded unchanged"),
        (
            "return this.process.request(OmpRpcCommandSchema.parse(command), timeoutMs);",
            "model RPC reaches the external process transport",
        ),
    ),
    "agent.ts": (
        ('const [provider, ...rest] = modelId.split("/");', "qualified identity splits at the provider boundary"),
        ('const id = rest.join("/");', "remaining model ID segments are preserved"),
        ('const id = rest.join("/"); if (provider && id) { return { provider, id }; }',
         "provider and exact model ID are retained"),
        (
            "const model = await this.runtimeSession.setModel(parsedReference.provider, parsedReference.id);",
            "selected provider and model ID reach the OMP runtime",
        ),
        ("this.config.model = `${model.provider}/${model.id}`;", "returned OMP identity is retained"),
        ("return model?.provider && model.id ? `${model.provider}/${model.id}` : null;", "OMP model listing preserves provider and model ID"),
        ("normalizeOmpThinkingOption(thinkingOptionId) ?? DEFAULT_OMP_THINKING_LEVEL;", "unsupported effort options fall back to Paseo's supported default"),
        ("await this.runtimeSession.setThinkingLevel(thinkingLevel);", "recognized effort reaches the OMP runtime"),
    ),
    "runtime.ts": (
        ('argv.push("--model", session.model);', "initial exact model ID reaches OMP CLI"),
        ('argv.push("--thinking", session.thinkingOptionId);', "initial effort reaches OMP CLI"),
        ("argv.push(...session.extraArgs);", "caller-provided runtime arguments are preserved"),
    ),
    "protocol-session.ts": (
        (
            'transport.request( { type: "negotiate_protocol", protocolVersion: 2 },',
            "provider uses the external OMP JSONL RPC protocol",
        ),
    ),
}

LIMITATIONS = [
    "Static source-level transport evidence only; supported IDs are limited to the exact intersection with the pinned OMP catalog and compatibility evidence.",
    "The configured Nix package is a separately pinned DMG artifact; this evidence does not establish binary/source equivalence.",
    "No runtime, account authentication, or inference success was tested; OMP_COMMAND or runtime settings may override the default executable.",
    "Paseo's thinking-level selector is limited to its recognized effort values; this does not claim universal OMP effort support.",
    "The source commit and Nix artifact digest are pinned independently; this evidence does not claim signed release metadata or binary/source equivalence.",
]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read pinned Paseo metadata at {path}: {error}") from error


def _require_once(text, fragment, label):
    if not isinstance(text, str) or text.count(fragment) != 1:
        raise ValueError(f"Paseo {label} proof missing or ambiguous")


def _read_pinned_install(root):
    root = Path(root)
    pins = _read_json(root / "release-pins.json")
    paseo_pin = pins.get("paseo") if isinstance(pins, dict) else None
    if not isinstance(paseo_pin, dict):
        raise ValueError("Paseo release pin is missing")
    version = paseo_pin.get("version")
    nix_hash = paseo_pin.get("hash")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError("Paseo release pin has an invalid version")
    match = SRI_PATTERN.fullmatch(nix_hash) if isinstance(nix_hash, str) else None
    if match is None:
        raise ValueError("Paseo release pin has an invalid SHA-256 SRI hash")
    try:
        digest = base64.b64decode(match.group(1), validate=True)
    except ValueError as error:
        raise ValueError("Paseo release pin has an invalid SHA-256 SRI hash") from error
    if len(digest) != 32:
        raise ValueError("Paseo release pin is not a SHA-256 hash")

    package_path = root / "packages/paseo.nix"
    try:
        package = package_path.read_text()
    except OSError as error:
        raise ValueError("Paseo Nix package definition is unavailable") from error
    for fragment in (
        "release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).paseo;",
        'url = "https://github.com/getpaseo/paseo/releases/download/v${release.version}/Paseo-${release.version}-arm64.dmg";',
        "inherit (release) hash;",
        r'exec "$out/Applications/Paseo.app/Contents/Resources/bin/paseo" "\$@"',
    ):
        _require_once(package, fragment, "Nix DMG installation")

    try:
        darwin_module = (root / "modules/darwin.nix").read_text()
        home_module = (root / "modules/home-manager.nix").read_text()
    except OSError as error:
        raise ValueError("Paseo Nix installation or config deployment is unavailable") from error
    _require_once(darwin_module, "(pkgs.callPackage ../packages/paseo.nix { })", "system installation")
    _require_once(
        home_module,
        "paseoConfig = builtins.fromJSON (builtins.readFile ../home/.paseo/config.json);",
        "configured provider deployment",
    )
    _require_once(home_module, '".paseo/config.json".text = builtins.toJSON (', "configured provider deployment")

    tag = f"v{version}"
    name = f"Paseo-{version}-arm64.dmg"
    return {
        "version": version,
        "tag": tag,
        "artifact_name": name,
        "artifact_url": f"https://github.com/getpaseo/paseo/releases/download/{tag}/{name}",
        "nix_hash": nix_hash,
        "release_sha256": digest.hex(),
        "commit_metadata_url": f"{API_BASE}/commits/{tag}",
        "release_metadata_url": f"{API_BASE}/releases/tags/{tag}",
    }


def _validate_external_omp_owner(root):
    config = _read_json(Path(root) / "home/.paseo/config.json")
    if not isinstance(config, dict):
        raise ValueError("Paseo config must be a JSON object")
    agents = config.get("agents")
    providers = agents.get("providers") if isinstance(agents, dict) else None
    omp = providers.get("omp") if isinstance(providers, dict) else None
    if not isinstance(omp, dict) or omp.get("enabled") is not True:
        raise ValueError("Paseo config does not enable the external omp provider")
    if omp.get("command", "omp") != "omp":
        raise ValueError("Paseo config overrides the external omp executable")
    if not isinstance(omp.get("additionalModels", []), list):
        raise ValueError("Paseo OMP additionalModels must be a list")

    daemon = config.get("daemon")
    profiles = daemon.get("agentProfiles") if isinstance(daemon, dict) else None
    if not isinstance(profiles, list) or not any(
        isinstance(profile, dict) and profile.get("provider") == "omp" for profile in profiles
    ):
        raise ValueError("Paseo profiles do not select the external omp provider")


def _resolve_commit(payload, pin):
    if not isinstance(payload, dict) or payload.get("tag_name") not in (None, pin["tag"]):
        raise ValueError("Paseo tag commit metadata is missing or mismatched")
    revision = payload.get("sha")
    if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
        raise ValueError("Paseo tag did not resolve to a full commit SHA")
    return revision


def _verify_release_payload(payload, pin):
    if not isinstance(payload, dict) or payload.get("tag_name") != pin["tag"]:
        raise ValueError("Paseo release metadata is missing or mismatched")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Paseo release asset metadata is malformed")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == pin["artifact_name"]]
    if len(matches) != 1 or matches[0].get("digest") != f"sha256:{pin['release_sha256']}":
        raise ValueError("Paseo arm64 DMG release digest does not match the Nix pin")


def _raw_url(path, revision):
    return f"{RAW_BASE}/{revision}/{PASEO_SOURCE_DIR}/{path}"


def _strip_ts_comments(text):
    output = []
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            output.append(char)
            if char == "\\" and index + 1 < len(text):
                output.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
        elif char in {"'", '"', "`"}:
            quote = char
            output.append(char)
            index += 1
        elif text.startswith("//", index):
            output.append(" ")
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("Paseo TypeScript source has an unclosed block comment")
            output.append(" ")
            output.extend(char for char in text[index:end + 2] if char in "\r\n")
            index = end + 2
        else:
            output.append(char)
            index += 1
    if quote is not None:
        raise ValueError("Paseo TypeScript source has an unterminated string")
    return "".join(output)


def _validate_source_text(path, text):
    if not isinstance(text, str) or not text:
        raise ValueError(f"Paseo source is empty or not text: {path}")
    normalized = re.sub(r"\s+", " ", _strip_ts_comments(text))
    for marker, claim in _SOURCE_CHECKS[path]:
        if normalized.count(marker) != 1:
            raise ValueError(f"Paseo {path} no longer proves {claim}")

def collect(root, fetch):
    """Return one pinned static-transport source record, failing on ambiguity."""
    provenance = _read_pinned_install(root)
    _validate_external_omp_owner(root)

    try:
        commit_payload = json.loads(fetch(provenance["commit_metadata_url"]), object_pairs_hook=_unique_object)
        release_payload = json.loads(fetch(provenance["release_metadata_url"]), object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError(f"Paseo release metadata is malformed: {error}") from error
    revision = _resolve_commit(commit_payload, provenance)
    _verify_release_payload(release_payload, provenance)

    proofs = []
    for path, checks in _SOURCE_CHECKS.items():
        url = _raw_url(path, revision)
        text = fetch(url)
        _validate_source_text(path, text)
        proofs.append({
            "path": path,
            "url": url,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "claims": [claim for _, claim in checks],
        })

    return {
        "provider": PROVIDER,
        "client": CLIENT,
        "kind": "static-transport",
        "role": "support",
        "models": [],
        "pin_revision": provenance["tag"],
        "revision": revision,
        "url": _raw_url("provider-config.ts", revision),
        "source_tier": SOURCE_TIER,
        "provenance": provenance,
        "transport_proofs": proofs,
        "limitations": list(LIMITATIONS),
    }


def validate_source(root, source):
    """Validate pinned provenance and proof schema; raise ValueError on any gap."""
    expected_fields = {
        "provider", "client", "kind", "role", "models", "pin_revision", "revision",
        "url", "source_tier", "provenance", "transport_proofs", "limitations", "omp_revision",
    }
    if not isinstance(source, dict) or set(source) != expected_fields:
        raise ValueError("Paseo static transport evidence has an incomplete or unknown schema")
    if (source["provider"], source["client"], source["kind"], source["role"]) != (
        PROVIDER, CLIENT, "static-transport", "support",
    ):
        raise ValueError("unsupported Paseo static transport identity")
    expected_provenance = _read_pinned_install(root)
    revision = source["revision"]
    if (source["pin_revision"] != expected_provenance["tag"]
            or not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision)):
        raise ValueError("Paseo source does not match the pinned release or immutable commit")
    if source["url"] != _raw_url("provider-config.ts", revision) or source["source_tier"] != SOURCE_TIER:
        raise ValueError("Paseo source URL or source tier is not pinned")
    if not isinstance(source["omp_revision"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["omp_revision"]):
        raise ValueError("Paseo evidence is not linked to an immutable OMP source revision")

    models = source["models"]
    if (not isinstance(models, list) or any(
        not isinstance(model, str) or not model or model.strip() != model for model in models
    ) or models != sorted(set(models))):
        raise ValueError("Paseo model IDs must be exact, sorted, unique strings")

    if source["provenance"] != expected_provenance:
        raise ValueError("Paseo artifact or release-tag provenance does not match this checkout")
    _validate_external_omp_owner(root)

    proofs = source["transport_proofs"]
    if not isinstance(proofs, list) or len(proofs) != len(_SOURCE_CHECKS):
        raise ValueError("Paseo transport evidence is missing pinned source proofs")
    for proof, (path, checks) in zip(proofs, _SOURCE_CHECKS.items()):
        if not isinstance(proof, dict) or set(proof) != {"path", "url", "sha256", "claims"}:
            raise ValueError("Paseo transport source proof has an invalid schema")
        if proof["path"] != path or proof["url"] != _raw_url(path, revision):
            raise ValueError("Paseo transport proof is not bound to the pinned source file")
        if not isinstance(proof["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", proof["sha256"]):
            raise ValueError("Paseo transport proof has an invalid source digest")
        if proof["claims"] != [claim for _, claim in checks]:
            raise ValueError("Paseo transport proof claims are missing or unsupported")

    if source["limitations"] != LIMITATIONS:
        raise ValueError("Paseo source limitations are missing or changed")
