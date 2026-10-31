#!/usr/bin/env python3
"""Report trusted Dependabot pin changes in the pull request body."""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote

from dependency_report import collect_rows
from version_table import render_table


REPOSITORY = "junghoon-vans/nix-config"
DEPENDABOT_LOGIN = "dependabot[bot]"
DEPENDABOT_ID = 49699333
NIX_BRANCH = re.compile(r"dependabot/nix/flake-inputs-[0-9a-f]{10}")
ACTIONS_BRANCH = re.compile(r"dependabot/github_actions/github-actions-[0-9a-f]{10}")
NIX_PATHS = {"flake.nix", "flake.lock"}
ACTION_PATHS = {
    ".github/workflows/validate.yml",
    ".github/workflows/update-dependencies.yml",
    ".github/workflows/mcp-security.yml",
    ".github/workflows/dependabot-automerge.yml",
}
START_MARKER = "<!-- dependabot-version-report:start -->"
END_MARKER = "<!-- dependabot-version-report:end -->"


def api(*args, input_data=None):
    result = subprocess.run(
        ["gh", "api", *args],
        input=input_data,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("GitHub API request failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("GitHub API returned invalid JSON") from error
    if isinstance(value, dict) and value.get("errors"):
        raise ValueError("GitHub API returned an error")
    return value


def _required_string(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing {field}")
    return value


def validate_pr(pr, number, expected_head):
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise ValueError("Unexpected pull request response")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("Invalid expected head")

    user = pr.get("user") or {}
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    base_repo = base.get("repo") or {}
    head_repo = head.get("repo") or {}
    if (
        user.get("login") != DEPENDABOT_LOGIN
        or user.get("id") != DEPENDABOT_ID
        or user.get("type") != "Bot"
        or pr.get("state") != "open"
        or pr.get("draft") is not False
        or pr.get("merged") is not False
        or base.get("ref") != "main"
        or base_repo.get("full_name") != REPOSITORY
        or head_repo.get("full_name") != REPOSITORY
        or head.get("sha") != expected_head
        or not re.fullmatch(r"[0-9a-f]{40}", str(head.get("sha", "")))
    ):
        raise ValueError("Pull request identity or head is not trusted")

    branch = _required_string(head.get("ref"), "head branch")
    if NIX_BRANCH.fullmatch(branch):
        return "nix", NIX_PATHS, _required_string(base.get("sha"), "base SHA")
    if ACTIONS_BRANCH.fullmatch(branch):
        return "actions", ACTION_PATHS, _required_string(base.get("sha"), "base SHA")
    raise ValueError("Unsupported Dependabot branch")


def _changed_files(endpoint, pr, allowed_paths):
    pages = api("--paginate", "--slurp", f"{endpoint}/files?per_page=100")
    if not isinstance(pages, list):
        raise ValueError("Invalid changed-file response")
    files = []
    for page in pages:
        if not isinstance(page, list):
            raise ValueError("Invalid changed-file page")
        files.extend(page)

    count = pr.get("changed_files")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
        or len(files) != count
    ):
        raise ValueError("Incomplete changed-file response")
    paths = []
    for file in files:
        if not isinstance(file, dict):
            raise ValueError("Invalid changed-file entry")
        path = file.get("filename")
        if path not in allowed_paths or path in paths:
            raise ValueError("Pull request contains an untrusted path")
        if file.get("status") != "modified":
            raise ValueError("Only modified Dependabot files are supported")
        if "previous_filename" in file:
            raise ValueError("Renamed files are not supported")
        paths.append(path)
    return files


def _contents(path, revision):
    endpoint = f"repos/{REPOSITORY}/contents/{quote(path, safe='/')}?ref={revision}"
    result = api(endpoint)
    if not isinstance(result, dict) or result.get("type") != "file":
        raise ValueError("GitHub did not return a file blob")
    if result.get("encoding") != "base64" or not isinstance(result.get("content"), str):
        raise ValueError("Unsupported GitHub file encoding")
    content = re.sub(r"\s+", "", result["content"])
    try:
        return base64.b64decode(content, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("Invalid GitHub file content") from error


def _snapshots(files, base_sha, head_sha):
    before = {}
    after = {}
    for file in files:
        path = file["filename"]
        status = file["status"]
        if status != "added":
            before[path] = _contents(path, base_sha)
        if status != "removed":
            after[path] = _contents(path, head_sha)
    return before, after


def _scalar(value):
    """Split a simple YAML scalar from its trailing comment."""
    value = value.strip()
    if not value:
        return "", ""
    if value[0] in "'\"":
        quote_char = value[0]
        closing = None
        index = 1
        while index < len(value):
            if quote_char == "\"" and value[index] == "\\":
                index += 2
                continue
            if value[index] == quote_char:
                if quote_char == "'" and value[index : index + 2] == "''":
                    index += 2
                    continue
                closing = index
                break
            index += 1
        if closing is None:
            return "", ""
        scalar = value[1:closing]
        trailing = value[closing + 1 :].strip()
        metadata = trailing[1:].strip() if trailing.startswith("#") else ""
        if quote_char == "'":
            scalar = scalar.replace("''", "'")
        return scalar, metadata
    match = re.match(r"^(.*?)(?:\s+#(.*))?$", value)
    scalar = match.group(1).strip()
    metadata = (match.group(2) or "").strip()
    return scalar, metadata


def action_references(contents):
    """Read external action uses references and their adjacent pin comments."""
    references = []
    block_scalar_indent = None
    for line in (contents or "").splitlines():
        if block_scalar_indent is not None:
            if not line.strip() or len(line) - len(line.lstrip(" ")) > block_scalar_indent:
                continue
            block_scalar_indent = None

        block = re.match(
            r"^(?P<indent> *)(?:-\s+)?[A-Za-z_][A-Za-z0-9_-]*\s*:\s*[|>]"
            r"(?:[+-]?[1-9]?|[1-9]?[+-]?)?(?:\s+#.*)?$",
            line,
        )
        if block:
            block_scalar_indent = len(block.group("indent"))
            continue

        match = re.match(r"^\s*(?:-\s+)?uses\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        reference, metadata = _scalar(match.group(1))
        action_name, separator, revision = reference.partition("@")
        if (
            not separator
            or not revision
            or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", action_name)
        ):
            continue
        references.append({
            "action": action_name,
            "revision": revision,
            "metadata": metadata,
        })
    return references


def _keyed_references(references):
    counts = {}
    result = {}
    for reference in references:
        action = reference["action"]
        counts[action] = counts.get(action, 0) + 1
        result[(action, counts[action])] = reference
    return result


def _display_pin(reference):
    if reference is None:
        return None
    pin = reference["revision"]
    if reference["metadata"]:
        pin += " # " + reference["metadata"]
    return pin


def _compare_url(action, old, new):
    if old is None or new is None or old["revision"] == new["revision"]:
        return None
    if "${{" in old["revision"] or "${{" in new["revision"]:
        return None
    owner, repository = action.split("/", 2)[:2]
    old_ref = quote(old["revision"], safe="-._~")
    new_ref = quote(new["revision"], safe="-._~")
    return f"https://github.com/{owner}/{repository}/compare/{old_ref}...{new_ref}"


def action_rows(before, after):
    rows = []
    for path in sorted(set(before) | set(after)):
        old_refs = _keyed_references(action_references(before.get(path)))
        new_refs = _keyed_references(action_references(after.get(path)))
        for action, occurrence in sorted(set(old_refs) | set(new_refs)):
            old = old_refs.get((action, occurrence))
            new = new_refs.get((action, occurrence))
            if old == new:
                continue
            if old is None:
                change = "Action reference added"
            elif new is None:
                change = "Action reference removed"
            elif old["revision"] != new["revision"]:
                change = "Action revision updated"
            else:
                change = "Action pin metadata updated"
            dependency = f"{path} — {action}"
            if occurrence > 1:
                dependency += f" (use {occurrence})"
            rows.append({
                "dependency": dependency,
                "previous": _display_pin(old),
                "next": _display_pin(new),
                "change": change,
                "compare": _compare_url(action, old, new),
            })
    return rows


def _report_rows(kind, before, after):
    if kind == "nix":
        return collect_rows(before, after)
    return action_rows(before, after)


def _section(rows):
    table = render_table(rows)
    if not isinstance(table, str) or not table.strip():
        raise ValueError("Version table renderer returned no table")
    lines = [START_MARKER, "### Dependency version changes", "", table.rstrip(), END_MARKER]
    return "\n".join(lines)


def update_body(body, rows):
    body = "" if body is None else body
    if not isinstance(body, str):
        raise ValueError("Invalid pull request body")
    section = _section(rows)
    start_count = body.count(START_MARKER)
    end_count = body.count(END_MARKER)
    if start_count != end_count or start_count > 1:
        raise ValueError("Malformed version report markers")
    if not start_count:
        separator = "" if not body else ("" if body.endswith("\n\n") else "\n\n")
        return body + separator + section
    start = body.index(START_MARKER)
    end = body.index(END_MARKER, start) + len(END_MARKER)
    if body.find(END_MARKER) < start:
        raise ValueError("Malformed version report markers")
    return body[:start] + section + body[end:]


def report(number, expected_head):
    endpoint = f"repos/{REPOSITORY}/pulls/{number}"
    pr = api(endpoint)
    kind, allowed_paths, base_sha = validate_pr(pr, number, expected_head)
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise ValueError("Invalid base SHA")
    files = _changed_files(endpoint, pr, allowed_paths)
    before, after = _snapshots(files, base_sha, expected_head)
    rows = _report_rows(kind, before, after)

    # Re-read identity and head after all blob reads, immediately before mutating the body.
    latest = api(endpoint)
    latest_kind, _, latest_base_sha = validate_pr(latest, number, expected_head)
    if latest_kind != kind or latest_base_sha != base_sha:
        raise ValueError("Pull request base or head changed while reporting")
    body = update_body(latest.get("body"), rows)
    if body == latest.get("body"):
        return
    api(
        f"repos/{REPOSITORY}/issues/{number}",
        "--method", "PATCH", "--input", "-",
        input_data=json.dumps({"body": body}),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if not os.environ.get("GH_TOKEN"):
        print("Dependabot version reporting requires GH_TOKEN", file=sys.stderr)
        return 1
    number_text = os.environ.get("PR_NUMBER", "")
    expected_head = os.environ.get("PR_HEAD", "")
    if not re.fullmatch(r"[1-9][0-9]*", number_text):
        print("Dependabot version reporting received an invalid PR_NUMBER", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        print("Dependabot version reporting received an invalid PR_HEAD", file=sys.stderr)
        return 1
    try:
        report(int(number_text), expected_head)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("Dependabot version reporting failed closed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
