#!/usr/bin/env python3
"""Inspect changed MCP packages without running configured shell/auth commands."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

CONFIG_PATH = "home/.omp/agent/mcp.json"
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
PACKAGE_RE = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?\Z")
TEXT_SUFFIXES = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".py", ".json", ".md", ".txt", ".html", ".css", ".yaml", ".yml"}
REINSPECT_PATHS = {"scripts/security/scan-mcp.py", "scripts/security/mcp_sandbox.py", "scripts/security/mcp-requirements.txt", ".github/workflows/mcp-security.yml"}
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_FILES = 1000


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def parse_servers(text: str) -> dict:
    config = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers"), dict):
        raise ValueError("MCP configuration must contain an mcpServers object")
    servers = config["mcpServers"]
    for name, server in servers.items():
        if not NAME_RE.fullmatch(name) or not isinstance(server, dict):
            raise ValueError("MCP servers must have safe names and object configurations")
        if "disabled" in server and not isinstance(server["disabled"], bool):
            raise ValueError(f"{name}: disabled must be a boolean")
    return servers


def load_servers(path: Path) -> dict:
    return parse_servers(path.read_text())


def npm_target(server: dict) -> tuple[str, str, str | None] | None:
    command, args = server.get("command"), server.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        return None
    if command != "npx":
        return None
    if args and args[0] in {"-y", "--yes"}:
        args = args[1:]
    binary = None
    if len(args) == 1:
        spec = args[0]
    elif len(args) == 2 and args[0].startswith("--package=") and NAME_RE.fullmatch(args[1]):
        spec, binary = args[0].removeprefix("--package="), args[1]
    else:
        return None
    package, separator, version = spec.rpartition("@")
    if not separator or not PACKAGE_RE.fullmatch(package) or not VERSION_RE.fullmatch(version):
        return None
    return package, version, binary


def plan_servers(base: dict, head: dict, scan_all: bool = False) -> list[dict]:
    plans = []
    for name, server in head.items():
        if server.get("disabled", False) or (not scan_all and base.get(name) == server):
            continue
        target = npm_target(server)
        row = {"name": name}
        if target:
            row.update(status="pending", package=target[0], version=target[1], binary=target[2])
        else:
            reason = "No supported, exact-version npm launch; configured commands are never evaluated."
            if server.get("url") or server.get("type") in {"http", "sse"}:
                reason = "Remote service: live definitions and authenticated service implementation are not inspected in CI."
            elif server.get("command") not in {"npx", "/bin/zsh"}:
                reason = "Machine-local executable: not available in the isolated Linux inspection environment."
            row.update(status="not_inspected", reason=reason, review_required=True)
        plans.append(row)
    return plans


def escaped(value) -> str:
    return html.escape(str(value)).replace("\n", " ").replace("\r", " ").replace("|", "&#124;").replace("`", "&#96;").replace("[", "&#91;").replace("]", "&#93;")


def summarize(results: list[dict]) -> str:
    lines = ["## MCP Scanner advisory", "", "Findings are advisory. A successful job means report generation succeeded, not that every MCP is safe.", "", "| Server | Inspection | Findings | Detail |", "|---|---|---:|---|"]
    for row in results:
        detail = row.get("reason") or "; ".join(row.get("errors", [])) or "Review JSON artifacts for matched patterns and dependency advisories."
        count = str(len(row.get("findings", []))) if row["status"] in {"completed", "incomplete"} else "N/A"
        lines.append(f"| {escaped(row['name'])} | {escaped(row['status'])} | {count} | {escaped(detail)} |")
    if not results:
        lines.append("No added or changed enabled MCP servers selected.")
    lines.extend(["", "Scope: Cisco YARA patterns over the published npm package's text sources and actual initialize/list metadata; npm audit over the resolved dependency graph. Lifecycle scripts disabled; MCP runtime has no network or credentials. No tools are invoked.", "", "Not covered: authenticated remote services, workstation binaries, arbitrary shell wrappers, prompt/resource contents, binary malware, LLM behavioral alignment, or complete execution/dataflow analysis. Optional local configuration/environment is not loaded or forwarded.", ""])
    return "\n".join(lines)


def serialize_findings(findings, location: str) -> list[dict]:
    return [{"location": location, "severity": item.severity, "summary": item.summary, "category": item.threat_category, "details": item.details} for item in findings]


async def inspect(plan: dict, work_dir: Path, report_dir: Path, analyzer) -> dict:
    from mcp_sandbox import prepare_package

    result = {**plan, "status": "error", "findings": [], "errors": [], "source_files_scanned": 0, "metadata_items_scanned": 0, "review_required": True}
    try:
        prepared = await prepare_package(plan["package"], plan["version"], plan["binary"], work_dir, report_dir)
        result["errors"].extend(prepared["errors"])
        root = Path(prepared["package_root"]).resolve()
        root.relative_to(work_dir.resolve())
        total = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name != "node_modules" and not (Path(directory) / name).is_symlink())
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if path.is_symlink():
                    result["errors"].append(f"Source symlink not inspected: {path.relative_to(root)}")
                    continue
                size = path.stat().st_size
                total += size
                if size > MAX_FILE_BYTES or total > MAX_SOURCE_BYTES or result["source_files_scanned"] >= MAX_SOURCE_FILES:
                    raise ValueError("Published source exceeds the bounded inspection limits; source inspection is incomplete")
                text = path.read_text(encoding="utf-8")
                location = f"source/{path.relative_to(root)}"
                result["findings"].extend(serialize_findings(await analyzer.analyze(text, {"content_type": "source", "tool_name": plan["name"]}), location))
                result["source_files_scanned"] += 1
        if not result["source_files_scanned"]:
            result["errors"].append("No inspectable text sources found in the published package")
        snapshot = prepared["snapshot"]
        if snapshot is not None:
            for kind in ("tools", "prompts", "resources"):
                for item in snapshot[kind]:
                    result["findings"].extend(serialize_findings(await analyzer.analyze(json.dumps(item, ensure_ascii=False), {"content_type": kind, "tool_name": item.get("name", plan["name"])}), f"metadata/{kind}/{item.get('name', '')}"))
                    result["metadata_items_scanned"] += 1
            if snapshot["instructions"]:
                result["findings"].extend(serialize_findings(await analyzer.analyze(snapshot["instructions"], {"content_type": "instructions", "tool_name": plan["name"]}), "metadata/instructions"))
                result["metadata_items_scanned"] += 1
        audit = prepared["audit"]
        if audit is not None:
            for name, vulnerability in audit.get("vulnerabilities", {}).items():
                result["findings"].append({"location": f"dependency/{name}", "severity": vulnerability["severity"].upper(), "category": "npm audit", "details": vulnerability})
        result["status"] = "incomplete" if result["errors"] else "completed"
        result["review_required"] = bool(result["errors"] or result["findings"])
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    return result


async def run(plans: list[dict], output_dir: Path) -> list[dict]:
    pending = [plan for plan in plans if plan["status"] == "pending"]
    analyzer = None
    if pending:
        from mcpscanner.core.analyzers.yara_analyzer import YaraAnalyzer
        analyzer = YaraAnalyzer()
    results = []
    for plan in plans:
        if plan["status"] == "not_inspected":
            results.append(plan)
        else:
            report_dir = output_dir / plan["name"]
            report_dir.mkdir()
            with tempfile.TemporaryDirectory(prefix="mcp-package-") as directory:
                result = await inspect(plan, Path(directory), report_dir, analyzer)
            results.append(result)
        (output_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref")
    parser.add_argument("--config", type=Path, default=Path(CONFIG_PATH))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--all", action="store_true", dest="scan_all")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        head = load_servers(args.config)
        base = {}
        scan_all = args.scan_all
        if args.base_ref and not scan_all:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", args.base_ref):
                raise ValueError("Invalid base Git reference")
            proc = subprocess.run(["git", "show", f"{args.base_ref}:{CONFIG_PATH}"], capture_output=True, text=True, timeout=30, check=True)
            base = parse_servers(proc.stdout)
            changed = subprocess.run(["git", "diff", "--name-only", args.base_ref, "--"], capture_output=True, text=True, timeout=30, check=True)
            scan_all = bool(REINSPECT_PATHS.intersection(changed.stdout.splitlines()))
        elif not scan_all:
            raise ValueError("Provide --base-ref or --all; an implicit full scan is not supported")
        plans = plan_servers(base, head, scan_all)
        (args.output_dir / "plan.json").write_text(json.dumps(plans, indent=2) + "\n")
        if args.plan_only:
            print(json.dumps(plans, indent=2))
            return 0
        results = asyncio.run(run(plans, args.output_dir))
        code = int(any(row["status"] in {"error", "incomplete"} for row in results))
    except Exception as error:
        results.append({"name": "inspection infrastructure", "status": "error", "errors": [f"{type(error).__name__}: {error}"], "review_required": True})
        code = 1
    (args.output_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    summary = summarize(results)
    (args.output_dir / "summary.md").write_text(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(summary)
    print(summary)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
