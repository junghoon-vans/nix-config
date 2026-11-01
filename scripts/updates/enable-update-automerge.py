#!/usr/bin/env python3
"""Enable GitHub-managed auto-merge only for trusted dependency-update heads."""

import argparse
import json
import re
import subprocess
import sys


REPOSITORY = "junghoon-vans/nix-config"
BOT = "nix-config-dependabot[bot]"
UPDATE_PATHS = {
    "automation/update-homebrew": {"flake.lock"},
    **{
        f"automation/update-{package}": {"release-pins.json"}
        for package in ("apm", "bun", "gnomcp", "omp", "paseo")
    },
    "automation/update-gno": {"modules/languages/gno.nix"},
    "automation/update-hermes": {"flake.nix", "flake.lock"},
    "automation/update-apm-skills": {"apm.yml", "apm.lock.yaml", "docs/skills.md"},
    "automation/update-npm-mcps": {"home/.omp/agent/mcp.json"},
    "automation/update-paseo-plugins": {"modules/paseo-plugins.json"},
}
DEPENDABOT_ID = 49699333
DEPENDABOT_ACTION_PATHS = {
    ".github/workflows/validate.yml",
    ".github/workflows/update-dependencies.yml",
    ".github/workflows/mcp-security.yml",
    ".github/workflows/dependabot-automerge.yml",
}
SCHEMA_QUERY = """query {
  __type(name: "EnablePullRequestAutoMergeInput") {
    inputFields { name type { kind name } }
  }
}"""
ENABLE_MUTATION = """mutation($id: ID!, $head: GitObjectID!) {
  enablePullRequestAutoMerge(input: {
    pullRequestId: $id, expectedHeadOid: $head, mergeMethod: SQUASH
  }) {
    pullRequest { id headRefOid autoMergeRequest { mergeMethod } }
  }
}"""


def api(*args):
    result = subprocess.run(
        ["gh", "api", *args], check=True, text=True, capture_output=True,
    )
    value = json.loads(result.stdout)
    if isinstance(value, dict) and value.get("errors"):
        raise ValueError(f"GitHub GraphQL errors: {value['errors']}")
    return value


def validate_scope(pr, files, branch, head, source="updater"):
    if source == "dependabot":
        trusted_author = (
            pr["user"]["login"] == "dependabot[bot]"
            and pr["user"]["id"] == DEPENDABOT_ID
            and pr["user"]["type"] == "Bot"
        )
        if re.fullmatch(r"dependabot/nix/flake-inputs-[0-9a-f]{10}", branch):
            allowed = {"flake.nix", "flake.lock"}
        elif re.fullmatch(r"dependabot/github_actions/github-actions-[0-9a-f]{10}", branch):
            allowed = DEPENDABOT_ACTION_PATHS
        else:
            allowed = None
    else:
        trusted_author = pr["user"]["login"] == BOT and pr["user"]["type"] == "Bot"
        allowed = UPDATE_PATHS.get(branch)
    if not allowed or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Unknown update branch or invalid expected head")
    if (
        pr["state"] != "open" or pr["draft"] or pr["merged"]
        or not trusted_author
        or pr["base"]["ref"] != "main"
        or pr["base"]["repo"]["full_name"] != REPOSITORY
        or pr["head"]["repo"]["full_name"] != REPOSITORY
        or pr["head"]["ref"] != branch or pr["head"]["sha"] != head
    ):
        raise ValueError("PR identity, repository, base, state, or head is not trusted")
    if not files or len(files) != pr["changed_files"]:
        raise ValueError("Empty or incomplete changed-file list")
    paths = [file["filename"] for file in files]
    if len(set(paths)) != len(paths) or not set(paths) <= allowed:
        raise ValueError("PR contains paths outside this updater's allowlist")
    if any(file["status"] != "modified" or "previous_filename" in file for file in files):
        raise ValueError("Updater files must be existing modified paths, not renames/additions/deletions")


def enable(number, branch, head, source="updater"):
    endpoint = f"repos/{REPOSITORY}/pulls/{number}"
    pr = api(endpoint)
    pages = api("--paginate", "--slurp", f"{endpoint}/files?per_page=100")
    files = [file for page in pages for file in page]
    # Re-read after file pagination; the mutation atomically guards this head too.
    current = api(endpoint)
    if pr["head"]["sha"] != current["head"]["sha"]:
        raise ValueError("PR head changed while reading files")
    validate_scope(current, files, branch, head, source)
    schema = api("graphql", "-f", f"query={SCHEMA_QUERY}")
    fields = schema["data"]["__type"]["inputFields"]
    if not any(
        field["name"] == "expectedHeadOid"
        and field["type"]["name"] == "GitObjectID"
        for field in fields
    ):
        raise ValueError("GitHub lacks atomic expectedHeadOid support; manual merge required")
    existing = current.get("auto_merge")
    if existing:
        if existing["merge_method"] != "squash":
            raise ValueError("Existing auto-merge is not SQUASH; manual review required")
        print(f"Auto-merge already enabled for PR #{number} at {head}")
        return
    result = api(
        "graphql", "-f", f"query={ENABLE_MUTATION}",
        "-f", f"id={current['node_id']}", "-f", f"head={head}",
    )["data"]["enablePullRequestAutoMerge"]["pullRequest"]
    if (
        result["id"] != current["node_id"] or result["headRefOid"] != head
        or result["autoMergeRequest"]["mergeMethod"] != "SQUASH"
    ):
        raise ValueError("GitHub did not confirm SQUASH auto-merge for the expected head")
    verified = api(endpoint)
    validate_scope(verified, files, branch, head, source)
    if not verified.get("auto_merge") or verified["auto_merge"]["merge_method"] != "squash":
        raise ValueError("Auto-merge read-back failed; inspect PR manually")
    print(f"Enabled SQUASH auto-merge for PR #{number} at {head}; GitHub enforces required checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--number", type=int, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--source", choices=("updater", "dependabot"), default="updater")
    args = parser.parse_args()
    try:
        if args.number < 1:
            raise ValueError("PR number must be positive")
        enable(args.number, args.branch, args.head, args.source)
    except (ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Auto-merge refused: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
