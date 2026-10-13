#!/usr/bin/env python3
"""Scan only newly added or changed, locked APM skills with SkillSpector."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import yaml

GITHUB_REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
REF_RE = re.compile(r"[A-Za-z0-9._/-]+\Z")
PATH_PART_RE = re.compile(r"[A-Za-z0-9_.@+-]+\Z")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
VALID_RECOMMENDATIONS = {"SAFE", "CAUTION", "DO_NOT_INSTALL"}
GIT_TIMEOUT_SECONDS = 300
SCAN_TIMEOUT_SECONDS = 1800


class ScanError(RuntimeError):
    """A fail-closed input, checkout, scan, or report error."""


def _lock_dependencies(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(lock, dict):
        raise ValueError("lockfile must be a mapping")
    rows = lock.get("dependencies")
    if not isinstance(rows, list):
        raise ValueError("lockfile dependencies must be a list")

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("lockfile dependency entries must be mappings")
        name = row.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ValueError("lockfile dependency has a missing or unsafe name")
        if name in result:
            raise ValueError(f"lockfile contains duplicate dependency name: {name}")
        result[name] = row
    return result


def changed_dependencies(base_lock: dict, head_lock: dict) -> list[dict]:
    """Return added or changed head lock entries; removals/deployments are ignored."""
    base = _lock_dependencies(base_lock)
    head = _lock_dependencies(head_lock)
    return [row for name, row in head.items() if name not in base or base[name] != row]


def _parse_github_repo(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must identify a GitHub owner/repository")

    if "://" in value:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{field} must use a credential-free https://github.com URL")
        repository = parsed.path.removeprefix("/")
        if repository.endswith(".git"):
            repository = repository[:-4]
    else:
        repository = value

    if not GITHUB_REPO_RE.fullmatch(repository):
        raise ValueError(f"{field} must be a GitHub owner/repository, got {value!r}")
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ValueError(f"{field} contains an unsafe repository path")
    return f"{owner}/{name}"


def _validate_ref(value: Any) -> str:
    if not isinstance(value, str) or not value or not REF_RE.fullmatch(value):
        raise ValueError("resolved_ref must be a non-empty, safe Git ref")
    components = value.split("/")
    if (
        value.startswith("-")
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(part.startswith(".") or part.endswith(".lock") for part in components)
    ):
        raise ValueError(f"resolved_ref is not a safe Git ref: {value!r}")
    return value


def _validate_virtual_path(value: Any) -> str:
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        raise ValueError("virtual_path must be a safe relative POSIX path")
    if value in {"", "."}:
        return "."
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"virtual_path must be relative: {value!r}")

    parts = value.split("/")
    if any(
        part.lower() == ".git"
        or part in {"", ".", ".."}
        or not PATH_PART_RE.fullmatch(part)
        for part in parts
    ):
        raise ValueError(f"virtual_path contains an unsafe or unsupported component: {value!r}")
    return PurePosixPath(*parts).as_posix()


def validate_dependency(entry: dict) -> None:
    """Raise ValueError unless the lock entry identifies a safe pinned GitHub path."""
    if not isinstance(entry, dict):
        raise ValueError("dependency entry must be a mapping")

    _parse_github_repo(entry.get("repo_url"), "repo_url")
    materialization = entry.get("materialization_repo_url")
    if materialization is not None:
        _parse_github_repo(materialization, "materialization_repo_url")
    host = entry.get("host")
    if host is not None and host != "github.com":
        raise ValueError("dependency host must be github.com")

    commit = entry.get("resolved_commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise ValueError("resolved_commit must be a full 40-character hexadecimal commit")
    _validate_ref(entry.get("resolved_ref"))
    _validate_virtual_path(entry.get("virtual_path", "."))



def _load_yaml_document(data: str, label: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(data)
    except yaml.YAMLError as error:
        raise ScanError(f"could not parse {label}: {error}") from error
    if not isinstance(parsed, dict):
        raise ScanError(f"{label} must be a YAML mapping")
    return parsed


def _git_repo_from_manifest(value: Any) -> str:
    return _parse_github_repo(value, "manifest git source")


def _manifest_dependencies(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ScanError("manifest dependencies must be a mapping")
    includes = manifest.get("includes", [])
    if includes != []:
        raise ScanError("non-empty manifest includes are unsupported by the security scanner")
    unsupported = set(dependencies) - {"apm"}
    if unsupported:
        raise ScanError(f"unsupported manifest dependency groups: {', '.join(sorted(map(str, unsupported)))}")
    rows = dependencies.get("apm", [])
    if not isinstance(rows, list):
        raise ScanError("manifest dependencies.apm must be a list")

    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScanError("manifest APM dependencies must be mappings")
        unknown = set(row) - {"git", "path", "ref", "alias", "skills"}
        if unknown:
            raise ScanError(f"unsupported APM dependency fields: {', '.join(sorted(map(str, unknown)))}")
        if not {"git", "ref"}.issubset(row):
            raise ScanError("manifest APM dependencies require git and ref")
        try:
            repo = _git_repo_from_manifest(row["git"])
            path = _validate_virtual_path(row.get("path", "."))
            ref = _validate_ref(row["ref"])
        except ValueError as error:
            raise ScanError(f"unsafe manifest dependency: {error}") from error
        alias = row.get("alias")
        if alias is not None and (not isinstance(alias, str) or not NAME_RE.fullmatch(alias)):
            raise ScanError("manifest dependency alias is missing or unsafe")
        skills = row.get("skills")
        if skills is not None and (
            not isinstance(skills, list) or not skills
            or any(not isinstance(skill, str) or not NAME_RE.fullmatch(skill) for skill in skills)
            or len(set(skills)) != len(skills)
        ):
            raise ScanError("manifest skills must be a non-empty list of unique skill names")
        normalized.append({
            "repo_url": repo, "virtual_path": path, "resolved_ref": ref,
            "alias": alias, "skills": skills,
        })

    return normalized


def _assert_manifest_lock_consistent(manifest: dict[str, Any], lock: dict[str, Any], label: str) -> None:
    try:
        rows_by_name = _lock_dependencies(lock)
    except ValueError as error:
        raise ScanError(f"{label} lockfile is invalid: {error}") from error

    for entry in rows_by_name.values():
        try:
            validate_dependency(entry)
        except ValueError as error:
            raise ScanError(f"{label} lock entry {entry.get('name', '<unnamed>')!r} is unsafe: {error}") from error

    manifest_rows = _manifest_dependencies(manifest)
    lock_keys: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in rows_by_name.values():
        key = (
            _parse_github_repo(entry["repo_url"], "repo_url").casefold(),
            _validate_virtual_path(entry.get("virtual_path", ".")),
            _validate_ref(entry["resolved_ref"]),
        )
        if key in lock_keys:
            raise ScanError(f"{label} lockfile has duplicate source/path/ref entries: {key[0]} {key[1]}")
        lock_keys[key] = entry

    matched: set[str] = set()
    for manifest_entry in manifest_rows:
        key = (
            manifest_entry["repo_url"].casefold(),
            manifest_entry["virtual_path"],
            manifest_entry["resolved_ref"],
        )
        locked = lock_keys.get(key)
        if locked is None:
            raise ScanError(
                f"{label} manifest/lock drift for {manifest_entry['repo_url']} "
                f"{manifest_entry['virtual_path']} at {manifest_entry['resolved_ref']}"
            )
        name = locked["name"]
        if name in matched:
            raise ScanError(f"{label} manifest maps multiple dependencies to lock entry {name}")
        if locked.get("alias") != manifest_entry["alias"]:
            raise ScanError(f"{label} manifest/lock alias drift for {name}")
        if locked.get("skill_subset") != manifest_entry["skills"]:
            raise ScanError(f"{label} manifest/lock skill selection drift for {name}")
        if manifest_entry["alias"] is not None and name != manifest_entry["alias"]:
            raise ScanError(f"{label} lock dependency name does not match manifest alias {manifest_entry['alias']}")
        if manifest_entry["alias"] is None and manifest_entry["virtual_path"] != ".":
            if name != PurePosixPath(manifest_entry["virtual_path"]).name:
                raise ScanError(f"{label} lock dependency name does not match manifest path for {name}")
        matched.add(name)

    if matched != set(rows_by_name):
        extra = sorted(set(rows_by_name) - matched)
        raise ScanError(f"{label} lockfile has entries absent from its manifest: {', '.join(extra)}")


def _repo_url(entry: dict[str, Any]) -> str:
    repo = entry.get("materialization_repo_url") or entry["repo_url"]
    return "https://github.com/" + _parse_github_repo(repo, "materialization repository") + ".git"


def _git_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": shutil.which("false") or os.devnull,
            "SSH_ASKPASS": shutil.which("false") or os.devnull,
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
    )
    return env


def _git(args: list[str], *, cwd: Path | None = None, timeout: int = GIT_TIMEOUT_SECONDS) -> bytes:
    command = [
        "git",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "credential.helper=",
        "-c", "protocol.file.allow=never",
        "-c", "http.followRedirects=false",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ScanError(f"Git command timed out after {timeout} seconds") from error
    except OSError as error:
        raise ScanError(f"could not run Git: {error}") from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ScanError(f"Git command failed ({result.returncode}): {detail[:1000]}")
    return result.stdout


def _scan_path(source: Path, target: Path) -> None:
    source_root = source.resolve(strict=True)
    target_root = target.resolve(strict=True)
    if not target_root.is_relative_to(source_root):
        raise ScanError("selected virtual_path resolves outside its isolated Git checkout")
    if any(part.lower() == ".git" for part in target_root.relative_to(source_root).parts):
        raise ScanError("selected virtual_path resolves into Git metadata")

    scope_root = target_root if target_root.is_dir() else target.parent.resolve(strict=True)
    if not scope_root.is_relative_to(source_root):
        raise ScanError("selected virtual_path parent resolves outside its isolated Git checkout")
    if target.is_symlink():
        if os.readlink(target).startswith(("/", "\\")):
            raise ScanError("selected virtual_path uses an absolute symlink")
        if not target_root.is_relative_to(scope_root):
            raise ScanError("selected virtual_path symlink escapes its source directory")
    skip_git = target_root == source_root
    if target_root.is_dir():
        for current, directories, filenames in os.walk(target_root, followlinks=False):
            current_path = Path(current)
            if skip_git and current_path == source_root:
                directories[:] = [name for name in directories if name != ".git"]
            names = [*directories, *filenames]
            for name in names:
                candidate = current_path / name
                if not candidate.is_symlink():
                    continue
                raw_target = os.readlink(candidate)
                if raw_target.startswith(("/", "\\")):
                    raise ScanError(f"absolute symlink in selected target: {candidate.relative_to(source_root)}")
                try:
                    resolved = candidate.resolve(strict=False)
                except (OSError, RuntimeError) as error:
                    raise ScanError(f"invalid symlink in selected target: {candidate.relative_to(source_root)}") from error
                if not resolved.exists():
                    raise ScanError(f"broken symlink in selected target: {candidate.relative_to(source_root)}")
                if not resolved.is_relative_to(source_root):
                    raise ScanError(f"symlink escapes isolated Git checkout: {candidate.relative_to(source_root)}")
                if any(part.lower() == ".git" for part in resolved.relative_to(source_root).parts):
                    raise ScanError(f"symlink in selected target resolves into Git metadata: {candidate.relative_to(source_root)}")
                if not resolved.is_relative_to(scope_root):
                    raise ScanError(f"symlink escapes selected virtual_path: {candidate.relative_to(source_root)}")
            directories[:] = [
                name for name in directories
                if not (current_path / name).is_symlink() and not (skip_git and current_path == source_root and name == ".git")
            ]

    paths = [target_root] if target_root.is_file() else []
    if target_root.is_dir():
        for current, directories, filenames in os.walk(target_root, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if not (current_path / name).is_symlink() and not (skip_git and current_path == source_root and name == ".git")
            ]
            paths.extend(current_path / name for name in filenames if not (current_path / name).is_symlink())
    for path in paths:
        try:
            with path.open("rb") as content:
                prefix = content.read(512)
        except OSError as error:
            raise ScanError(f"could not inspect selected target file {path.relative_to(source_root)}: {error}") from error
        lines = prefix.splitlines()
        if (
            len(lines) >= 3
            and lines[0] == b"version https://git-lfs.github.com/spec/v1"
            and lines[1].startswith(b"oid sha256:")
            and lines[2].startswith(b"size ")
        ):
            raise ScanError(f"Git LFS object not materialized in selected target: {path.relative_to(source_root)}")


def _submodule_paths(checkout: Path) -> list[str]:
    output = _git(["-C", str(checkout), "ls-tree", "-r", "-z", "HEAD"])
    found = []
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0]
        if mode == b"160000":
            found.append(raw_path.decode("utf-8", errors="replace"))
    return found


def _path_overlaps(left: str, right: str) -> bool:
    return left == "." or right == "." or left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _checkout_group(entries: list[dict[str, Any]], parent: Path) -> Path:
    first = entries[0]
    checkout = parent / "checkout"
    checkout.mkdir(parents=True)
    _git(["init", "--quiet", str(checkout)])
    _git(["-C", str(checkout), "remote", "add", "origin", _repo_url(first)])

    paths = {_validate_virtual_path(entry.get("virtual_path", ".")) for entry in entries}
    if "." not in paths:
        _git(["-C", str(checkout), "config", "core.sparseCheckout", "true"])
        _git(["-C", str(checkout), "config", "core.sparseCheckoutCone", "false"])
        info = checkout / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "sparse-checkout").write_text(
            "".join(f"/{path}/\n" for path in sorted(paths)), encoding="utf-8"
        )
    commit = first["resolved_commit"].lower()
    _git(["-C", str(checkout), "fetch", "--filter=blob:none", "--depth=1", "--no-tags", "--recurse-submodules=no", "origin", commit])
    _git(["-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"])

    return checkout


def _safe_scanner_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _report_name(run_id: str, index: int, name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ScanError("selected dependency has an unsafe report name")
    return f"{run_id}-{index:03d}-{name}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_scan_report(report: dict, returncode: int) -> list[str]:
    """Validate usable static-analysis evidence, not whether a skill is safe."""
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["scanner report must be a JSON object"]
    assessment = report.get("risk_assessment")
    if not isinstance(assessment, dict):
        errors.append("missing or malformed risk_assessment")
        assessment = {}
    score = assessment.get("score")
    if not _is_number(score) or not 0 <= score <= 100:
        errors.append("risk_assessment.score must be a finite number from 0 to 100")
    if assessment.get("severity") not in VALID_SEVERITIES:
        errors.append("risk_assessment.severity is missing or unsupported")
    if assessment.get("recommendation") not in VALID_RECOMMENDATIONS:
        errors.append("risk_assessment.recommendation is missing or unsupported")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("llm_requested") is not False:
        errors.append("report must confirm metadata.llm_requested is false")
    issues = report.get("issues")
    if not isinstance(issues, list):
        errors.append("report issues must be a list")
    elif any(not isinstance(issue, dict) or issue.get("severity") not in VALID_SEVERITIES for issue in issues):
        errors.append("report contains malformed issue severities")
    completeness = report.get("analysis_completeness")
    if not isinstance(completeness, dict):
        errors.append("missing or malformed analysis_completeness")
        completeness = {}
    if not isinstance(completeness.get("is_complete"), bool):
        errors.append("analysis_completeness.is_complete must be a boolean")
    coverage = completeness.get("coverage_percent")
    if not _is_number(coverage) or not 0 <= coverage <= 100:
        errors.append("analysis_completeness.coverage_percent must be from 0 to 100")
    for field in ("ledger_exceptions", "scope_exclusions", "limitations", "analyzer_statuses"):
        if not isinstance(completeness.get(field), list):
            errors.append(f"analysis_completeness.{field} must be a list")
    if report.get("execution_successful") is not True:
        errors.append("scanner execution was unsuccessful")
    if type(returncode) is not int or returncode not in {0, 1}:
        errors.append(f"scanner exited with error code {returncode}")
    elif returncode == 1 and not errors:
        # Upstream exit 1 means either findings or incomplete analysis. Never
        # discard an unexplained failure just because a report happens to exist.
        if not issues and assessment.get("score") <= 50 and completeness.get("is_complete") is True:
            errors.append("scanner exited 1 without findings or incomplete analysis")
    return errors


def _report_details(report: dict, returncode: int) -> dict[str, Any]:
    errors = validate_scan_report(report, returncode)
    assessment = report.get("risk_assessment", {})
    completeness = report.get("analysis_completeness", {})
    issues = report.get("issues", [])
    if errors:
        return {"scan_status": "error", "review_required": True, "failures": errors}
    analyzer_problems = [
        status.get("analyzer_id", "unknown") for status in completeness["analyzer_statuses"]
        if isinstance(status, dict) and (
            status.get("status") not in {"completed", "disabled", "not_applicable"}
            or any(status.get(field, 0) for field in ("partial", "skipped", "failed", "unaccounted"))
        )
    ]
    incomplete = (
        not completeness["is_complete"] or completeness["coverage_percent"] < 100
        or completeness["ledger_exceptions"] or completeness["scope_exclusions"]
        or completeness["limitations"] or analyzer_problems
    )
    return {
        "scan_status": "incomplete" if incomplete else "completed",
        "review_required": bool(
            issues or incomplete or assessment["severity"] in {"HIGH", "CRITICAL"}
            or assessment["recommendation"] != "SAFE"
        ),
        "returncode": returncode,
        "risk": f"{assessment['severity']} ({assessment['score']})",
        "recommendation": assessment["recommendation"],
        "finding_count": len(issues),
        "high_critical_count": sum(issue["severity"] in {"HIGH", "CRITICAL"} for issue in issues),
        "coverage": {
            "percent": completeness["coverage_percent"],
            "complete": not bool(incomplete),
            "exceptions": len(completeness["ledger_exceptions"]),
            "exclusions": len(completeness["scope_exclusions"]),
            "limitations": len(completeness["limitations"]),
            "analyzer_problems": analyzer_problems,
        },
        "failures": [],
    }


def _read_json_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScanError(f"missing or malformed scanner JSON report: {error}") from error
    if not isinstance(value, dict):
        raise ScanError("scanner JSON report must be an object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summary_value(value: Any) -> str:
    return re.sub(r"[\r\n`|<>]", " ", str(value))[:300]


def _summary_text(results: list[dict[str, Any]], *, errors: list[str], plan_only: bool) -> str:
    lines = ["## Agent skill inspection", ""]
    if errors and not results:
        lines.extend(["**Input validation or inspection failed.**", "", *[f"- {_summary_value(error)}" for error in errors], ""])
    elif plan_only and results:
        lines.extend(["Validated added or changed pinned APM skill inputs:", ""])
        lines.extend(f"- `{result['name']}` — {result['change']}" for result in results)
    elif not results:
        lines.append("No added or changed pinned APM skills; scanner installation and scans were skipped.")
    else:
        lines.extend([
            "**Advisory only: findings and coverage limits require human review, not an automatic safety verdict.**",
            "",
            "| Skill | Inspection | Risk | Recommendation | Findings (HIGH/CRITICAL) | Coverage |",
            "| --- | --- | --- | --- | ---: | --- |",
        ])
        for result in results:
            coverage = result.get("coverage")
            coverage_text = "unavailable"
            if coverage:
                coverage_text = (
                    f"{coverage['percent']}%; {'complete' if coverage['complete'] else 'incomplete'}; "
                    f"{coverage['exceptions']} exceptions, {coverage['exclusions']} exclusions, "
                    f"{len(coverage['analyzer_problems'])} analyzer problems"
                )
            cells = [
                result["name"], result["scan_status"], result.get("risk", "unavailable"),
                result.get("recommendation", "unavailable"),
                f"{result.get('finding_count', 'unavailable')} ({result.get('high_critical_count', 'unavailable')})",
                coverage_text,
            ]
            lines.append("| " + " | ".join(_summary_value(cell) for cell in cells) + " |")
            for reason in result.get("failures", []):
                lines.append(f"  - {_summary_value(reason)}")
        lines.extend(["", "Full findings and coverage details are preserved in the JSON report artifacts."])
    return "\n".join(lines) + "\n"


def _write_summary(markdown: str, output_dir: Path) -> None:
    (output_dir / "summary.md").write_text(markdown, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(markdown + "\n")
    else:
        print(markdown)


def _read_committed_file(ref: str, filename: str, root: Path) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", ref) or ref.startswith("-") or ".." in ref:
        raise ScanError("--base-ref must be a safe Git ref or commit")
    try:
        output = subprocess.run(
            ["git", "show", f"{ref}:{filename}"],
            cwd=root,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScanError(f"could not read {filename} at {ref}: {error}") from error
    if output.returncode:
        raise ScanError(f"could not read {filename} at {ref}: {output.stderr.strip()[:1000]}")
    return output.stdout


def _read_lock_and_manifest(ref: str, root: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _load_yaml_document(_read_committed_file(ref, "apm.yml", root), f"{label} apm.yml")
    lock = _load_yaml_document(_read_committed_file(ref, "apm.lock.yaml", root), f"{label} apm.lock.yaml")
    _assert_manifest_lock_consistent(manifest, lock, label)
    return manifest, lock


def _make_plan(base_ref: str, root: Path) -> dict[str, Any]:
    _, base_lock = _read_lock_and_manifest(base_ref, root, "base")
    head_ref = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        env=_git_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if head_ref.returncode:
        raise ScanError(f"could not resolve HEAD: {head_ref.stderr.strip()[:1000]}")
    head_manifest = _load_yaml_document((root / "apm.yml").read_text(encoding="utf-8"), "head apm.yml")
    head_lock = _load_yaml_document((root / "apm.lock.yaml").read_text(encoding="utf-8"), "head apm.lock.yaml")
    _assert_manifest_lock_consistent(head_manifest, head_lock, "head")
    selected = changed_dependencies(base_lock, head_lock)
    old_by_name = _lock_dependencies(base_lock)

    changes = []
    for entry in selected:
        try:
            validate_dependency(entry)
        except ValueError as error:
            raise ScanError(f"unsafe selected dependency {entry.get('name', '<unnamed>')!r}: {error}") from error
        name = entry["name"]
        changes.append({
            "name": name,
            "change": "added" if name not in old_by_name else "changed",
            "repo_url": entry["repo_url"],
            "materialization_repo_url": entry.get("materialization_repo_url"),
            "resolved_commit": entry["resolved_commit"].lower(),
            "resolved_ref": entry["resolved_ref"],
            "virtual_path": _validate_virtual_path(entry.get("virtual_path", ".")),
            "entry": entry,
        })
    return {
        "base_ref": base_ref,
        "head_ref": head_ref.stdout.strip(),
        "dependencies": changes,
    }


def _stage_target(source: Path, target: Path, destination: Path) -> Path:
    _scan_path(source, target)
    if destination.exists():
        raise ScanError(f"scan staging path already exists: {destination.name}")
    source_target = target.resolve(strict=True)
    if source_target.is_dir():
        ignored = shutil.ignore_patterns(".git") if source_target == source.resolve() else None
        shutil.copytree(source_target, destination, symlinks=True, copy_function=shutil.copy2, ignore=ignored)
    else:
        destination.mkdir(parents=True)
        shutil.copy2(source_target, destination / target.name)
        destination = destination / target.name
    return destination


def _scan_one(entry: dict[str, Any], source: Path, output_dir: Path, report_id: str, stage_dir: Path, scanner: str) -> dict[str, Any]:
    name = entry["name"]
    report_path = output_dir / "reports" / f"{report_id}.json"
    log_path = output_dir / "logs" / f"{report_id}.log"
    staged = stage_dir / report_id
    result: dict[str, Any] = {
        "name": name,
        "change": entry["change"],
        "report": str(report_path.relative_to(output_dir)),
        "log": str(log_path.relative_to(output_dir)),
    }
    try:
        target = source / entry["virtual_path"]
        staged_target = _stage_target(source, target, staged)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            scanner,
            "scan",
            str(staged_target),
            "--no-llm",
            "--fail-on-incomplete",
            "--format",
            "json",
            "--output",
            str(report_path),
        ]
        output_dir.joinpath("logs").mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.run(
                    command,
                    cwd=stage_dir,
                    env={
                        **_safe_scanner_environment(),
                        "HOME": str(stage_dir),
                        "TMPDIR": str(stage_dir),
                    },
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=SCAN_TIMEOUT_SECONDS,
                    check=False,
                )
            returncode = process.returncode
        except FileNotFoundError as error:
            raise ScanError(f"SkillSpector executable not found: {scanner}") from error
        except subprocess.TimeoutExpired as error:
            raise ScanError(f"SkillSpector timed out after {SCAN_TIMEOUT_SECONDS} seconds") from error
        except OSError as error:
            raise ScanError(f"could not run SkillSpector: {error}") from error

        report = _read_json_report(report_path)
        result.update(_report_details(report, returncode))
    except (ScanError, ValueError, OSError) as error:
        if not report_path.exists():
            _write_json(report_path, {
                "dependency": name,
                "resolved_commit": entry["resolved_commit"],
                "virtual_path": entry["virtual_path"],
                "error": str(error),
            })
        result.update({"scan_status": "error", "review_required": True, "failures": [str(error)]})
    return result


def _scan_plan(plan: dict[str, Any], output_dir: Path, scanner: str) -> list[dict[str, Any]]:
    dependencies = plan["dependencies"]
    if not dependencies:
        return []

    scanner_path = shutil.which(scanner)
    run_id = uuid.uuid4().hex[:8]
    for index, entry in enumerate(dependencies, start=1):
        entry["report_id"] = _report_name(run_id, index, entry["name"])

    results_by_name: dict[str, dict[str, Any]] = {}
    if scanner_path is None:
        for entry in dependencies:
            report_path = output_dir / "reports" / f"{entry['report_id']}.json"
            message = f"scanner executable not found: {scanner}"
            _write_json(report_path, {"dependency": entry["name"], "error": message})
            results_by_name[entry["name"]] = {
                "name": entry["name"],
                "change": entry["change"],
                "report": str(report_path.relative_to(output_dir)),
                "scan_status": "error",
                "review_required": True,
                "failures": [message],
                "risk": "unavailable",
                "finding_count": "unavailable",
            }
        return [results_by_name[entry["name"]] for entry in dependencies]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in dependencies:
        key = (_repo_url(entry["entry"]).casefold(), entry["resolved_commit"])
        groups.setdefault(key, []).append(entry)

    with tempfile.TemporaryDirectory(prefix="agent-skill-security-") as temporary:
        temp_root = Path(temporary)
        for group_index, entries in enumerate(groups.values(), start=1):
            group_root = temp_root / f"source-{group_index:03d}"
            group_root.mkdir()
            try:
                checkout = _checkout_group([entry["entry"] for entry in entries], group_root)
                stage_dir = group_root / "scan-inputs"
                stage_dir.mkdir()
                submodules = _submodule_paths(checkout)
                for entry in entries:
                    name = entry["name"]
                    try:
                        path = entry["virtual_path"]
                        if any(_path_overlaps(submodule, path) for submodule in submodules):
                            raise ScanError(f"selected target includes an unfetched Git submodule: {path}")
                        target = checkout / path
                        if not target.exists() and not target.is_symlink():
                            raise ScanError(f"locked virtual_path does not exist at pinned commit: {path}")
                        results_by_name[name] = _scan_one(
                            entry, checkout, output_dir, entry["report_id"], stage_dir, scanner_path
                        )
                    except (ScanError, OSError, ValueError) as error:
                        report_path = output_dir / "reports" / f"{entry['report_id']}.json"
                        _write_json(report_path, {
                            "dependency": name,
                            "resolved_commit": entry["resolved_commit"],
                            "virtual_path": entry["virtual_path"],
                            "error": str(error),
                        })
                        results_by_name[name] = {
                            "name": name,
                            "change": entry["change"],
                            "report": str(report_path.relative_to(output_dir)),
                            "scan_status": "error",
                            "review_required": True,
                            "failures": [str(error)],
                            "risk": "unavailable",
                            "finding_count": "unavailable",
                        }
            except (ScanError, OSError, ValueError) as error:
                for entry in entries:
                    name = entry["name"]
                    report_path = output_dir / "reports" / f"{entry['report_id']}.json"
                    _write_json(report_path, {
                        "dependency": name,
                        "resolved_commit": entry["resolved_commit"],
                        "virtual_path": entry["virtual_path"],
                        "error": str(error),
                    })
                    results_by_name[name] = {
                        "name": name,
                        "change": entry["change"],
                        "report": str(report_path.relative_to(output_dir)),
                        "scan_status": "error",
                        "review_required": True,
                        "failures": [str(error)],
                        "risk": "unavailable",
                        "finding_count": "unavailable",
                    }
    return [results_by_name[entry["name"]] for entry in dependencies]


def _append_github_output(changed: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"changed={'true' if changed else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="base commit or Git ref to compare against")
    parser.add_argument("--output-dir", required=True, help="directory for the scan plan, reports, and logs")
    parser.add_argument("--scanner", default="skillspector", help="SkillSpector executable (default: skillspector)")
    parser.add_argument("--plan-only", action="store_true", help="write the plan and skip scans")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    repository_root = Path(__file__).resolve().parents[2]
    errors: list[str] = []
    plan: dict[str, Any] = {"base_ref": args.base_ref, "head_ref": None, "dependencies": []}
    results: list[dict[str, Any]] = []
    try:
        plan = _make_plan(args.base_ref, repository_root)
        serializable_plan = {key: value for key, value in plan.items()}
        _write_json(output_dir / "plan.json", serializable_plan)
        if args.plan_only:
            _append_github_output(bool(plan["dependencies"]))
            _write_summary(_summary_text(plan["dependencies"], errors=[], plan_only=True), output_dir)
            return 0
        if not plan["dependencies"]:
            _write_summary(_summary_text([], errors=[], plan_only=False), output_dir)
            return 0

        results = _scan_plan(plan, output_dir, args.scanner)
        failures = [
            f"{result['name']}: {reason}"
            for result in results
            if result["scan_status"] == "error"
            for reason in result.get("failures", ["scan failed"])
        ]
        _write_json(output_dir / "results.json", {"results": results, "failures": failures})
        _write_summary(_summary_text(results, errors=failures, plan_only=False), output_dir)
        return 1 if failures else 0
    except (ScanError, ValueError, OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
        _write_json(output_dir / "results.json", {"results": results, "failures": errors})
        _write_json(output_dir / "validation-error.json", {"error": str(error)})
        _write_summary(_summary_text(results, errors=errors, plan_only=args.plan_only), output_dir)
        if args.plan_only:
            _append_github_output(False)
        print(f"Security scan failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
