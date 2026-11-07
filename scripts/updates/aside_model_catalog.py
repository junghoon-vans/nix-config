"""Aside's mutable official catalog: LIVE evidence, never pinned-client proof."""

from datetime import datetime, timedelta, timezone
import json
import re
import urllib.request

URL = "https://api.asidehq.com/ai/model-catalog/v1/providers/openai-codex"
PROVIDER = "openai-codex"
MAX_BYTES = 1024 * 1024
MAX_AGE = timedelta(hours=1)
FUTURE_SKEW = timedelta(minutes=5)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_catalog(data):
    if not isinstance(data, dict) or set(data) != {"models", "visibleModelIds"}:
        raise ValueError("unsupported Aside catalog schema")
    rows, visible = data["models"], data["visibleModelIds"]
    if not isinstance(rows, list) or not rows or not isinstance(visible, list) or not visible:
        raise ValueError("Aside catalog requires models and visibleModelIds")
    ids = []
    for row in rows:
        if (not isinstance(row, dict)
                or row.get("provider") != PROVIDER
                or row.get("api") != "openai-codex-responses"
                or row.get("baseUrl") != "https://chatgpt.com/backend-api"
                or row.get("type") != "chat"
                or not isinstance(row.get("id"), str)
                or not re.fullmatch(r"gpt-[0-9]+(?:\.[0-9]+)?(?:-[a-z0-9]+)+", row["id"])
                or not isinstance(row.get("name"), str) or not row["name"]
                or type(row.get("reasoning")) is not bool
                or not isinstance(row.get("input"), list) or "text" not in row["input"]
                or any(not isinstance(value, str) or value not in {"text", "image"} for value in row["input"])
                or type(row.get("contextWindow")) is not int or row["contextWindow"] <= 0
                or type(row.get("maxTokens")) is not int or row["maxTokens"] <= 0):
            raise ValueError("invalid Aside model/provider schema")
        ids.append(row["id"])
    if (len(set(ids)) != len(ids)
            or any(not isinstance(value, str) for value in visible)
            or len(set(visible)) != len(visible) or not set(visible) <= set(ids)):
        raise ValueError("duplicate or unknown Aside model IDs")
    # Only explicitly visible entries qualify; never infer future family members.
    return sorted(visible)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Aside catalog redirects are not trusted")


def collect_source():
    request = urllib.request.Request(URL, headers={
        "Accept": "application/json", "User-Agent": "nix-config-model-support-collector",
        "Cache-Control": "no-cache",
    })
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        if (response.status != 200 or response.geturl() != URL
                or response.headers.get_content_type() != "application/json"):
            raise ValueError("untrusted Aside catalog response")
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Aside catalog exceeds size limit")
    catalog = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
    models = parse_catalog(catalog)
    return {
        "client": "aside", "provider": PROVIDER, "role": "support",
        "kind": "live-official-catalog", "revision": "LIVE", "url": URL,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "catalog": catalog, "models": models,
    }


def validate_source(source, now=None):
    if (source.get("client") != "aside" or source.get("provider") != PROVIDER
            or source.get("role") != "support" or source.get("url") != URL
            or source.get("kind") != "live-official-catalog" or source.get("revision") != "LIVE"
            or "pin_revision" in source):
        raise ValueError("aside: invalid LIVE official catalog provenance")
    value = source.get("observed_at")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("aside: invalid LIVE observation timestamp") from error
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("aside: LIVE observation must include timezone")
    age = (now or datetime.now(timezone.utc)).astimezone(timezone.utc) - observed
    if age > MAX_AGE or age < -FUTURE_SKEW:
        raise ValueError("aside: stale or future LIVE catalog observation")
    models = parse_catalog(source.get("catalog"))
    if set(models) != source["models"]:
        raise ValueError("aside: evidence models differ from official catalog")
