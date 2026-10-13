"""Install a pinned MCP package and inspect its stdio metadata in Docker."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import uuid
import traceback
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

NODE_IMAGE = "node:22.22.2-bookworm-slim@sha256:9f6d5975c7dca860947d3915877f85607946403fc55349f39b4bc3688448bb6e"
REGISTRY = "https://registry.npmjs.org"
PACKAGE_RE = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
VERSION_RE = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)

INSTALL_TIMEOUT_SECONDS = 110
AUDIT_TIMEOUT_SECONDS = 60
RUNTIME_TIMEOUT_SECONDS = 80
CLEANUP_TIMEOUT_SECONDS = 10
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_LOCK_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_PAGE_COUNT = 100
MAX_ITEMS_PER_LIST = 10_000
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class DockerResult:
    returncode: int | None
    stdout: bytes
    stdout_truncated: bool
    timed_out: bool


class PackageDefinitionError(ValueError):
    """The installed package does not define a safe, usable server binary."""


class SnapshotInspectionError(RuntimeError):
    """A bounded MCP metadata snapshot could not be collected."""


def _write_artifact(report_dir: Path, name: str, data: bytes) -> None:
    """Write a fixed-name artifact without following an existing symlink."""
    path = report_dir / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def _write_log(report_dir: Path, name: str, data: bytes, truncated: bool) -> None:
    if len(data) > MAX_LOG_BYTES:
        truncated = True
    if truncated:
        marker = b"\n[log truncated at the configured byte limit]\n"
        data = data[: MAX_LOG_BYTES - len(marker)] + marker
    _write_artifact(report_dir, name, data)


async def _capture_stream(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    kept = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        remaining = limit - len(kept)
        if remaining > 0:
            kept.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(kept), truncated


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except asyncio.TimeoutError:
        pass


async def _remove_owned_container(docker: str, name: str, env: dict[str, str]) -> None:
    """Remove one named container only; never use broad Docker cleanup commands."""
    try:
        process = await asyncio.create_subprocess_exec(
            docker,
            "rm",
            "--force",
            name,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=CLEANUP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await _terminate_process_group(process)
    except (OSError, subprocess.SubprocessError):
        # Cleanup is best effort; the original command error remains authoritative.
        return


async def _run_docker(
    docker: str,
    args: list[str],
    *,
    env: dict[str, str],
    report_dir: Path,
    log_prefix: str,
    container_name: str,
    timeout: int,
    stdout_limit: int = MAX_LOG_BYTES,
) -> DockerResult:
    command = [docker, *args]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _write_log(report_dir, f"{log_prefix}.stdout.log", b"", False)
        _write_log(report_dir, f"{log_prefix}.stderr.log", b"", False)
        raise RuntimeError(f"Docker could not start {log_prefix} ({type(error).__name__}).") from None

    assert process.stdout is not None and process.stderr is not None
    stdout_task = asyncio.create_task(_capture_stream(process.stdout, stdout_limit))
    stderr_task = asyncio.create_task(_capture_stream(process.stderr, MAX_LOG_BYTES))
    timed_out = False
    cancelled = False
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await _terminate_process_group(process)
        except asyncio.CancelledError:
            cancelled = True
            await asyncio.shield(_terminate_process_group(process))
            raise
    finally:
        try:
            captured = await asyncio.shield(
                asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            )
            if isinstance(captured[0], tuple):
                stdout, stdout_truncated = captured[0]
            else:
                stdout, stdout_truncated = b"", True
            if isinstance(captured[1], tuple):
                stderr, stderr_truncated = captured[1]
            else:
                stderr, stderr_truncated = b"", True
            _write_log(
                report_dir,
                f"{log_prefix}.stdout.log",
                stdout,
                stdout_truncated or len(stdout) > MAX_LOG_BYTES,
            )
            _write_log(
                report_dir,
                f"{log_prefix}.stderr.log",
                stderr,
                stderr_truncated or len(stderr) > MAX_LOG_BYTES,
            )
        finally:
            if timed_out or cancelled:
                await asyncio.shield(_remove_owned_container(docker, container_name, env))
    return DockerResult(process.returncode, stdout, stdout_truncated, timed_out)


def _validate_directories(work_dir: Path, report_dir: Path) -> tuple[Path, Path]:
    if not isinstance(work_dir, Path) or not isinstance(report_dir, Path):
        raise ValueError("work_dir and report_dir must be Path objects.")
    if work_dir.is_symlink() or not work_dir.is_dir():
        raise ValueError("work_dir must be an existing, non-symlink directory.")
    work_root = work_dir.resolve(strict=True)
    report_requested = report_dir.expanduser()
    if report_requested.is_symlink():
        raise ValueError("report_dir must not be a symlink.")
    report_root = report_requested.resolve(strict=False)
    if (
        report_root == work_root
        or work_root in report_root.parents
        or report_root in work_root.parents
    ):
        raise ValueError("work_dir and report_dir must be separate, non-overlapping directories.")
    if any(work_root.iterdir()):
        raise ValueError("work_dir must be empty before package installation.")
    for path in (work_root, report_root):
        if any(character in str(path) for character in ("\x00", ",", "\n", "\r")):
            raise ValueError("Docker bind paths contain an unsupported character.")
    report_root.mkdir(parents=True, exist_ok=True)
    if report_root.is_symlink() or not report_root.is_dir():
        raise ValueError("report_dir must resolve to a directory.")
    return work_root, report_root.resolve(strict=True)


def _validate_package_and_version(package: str, version: str, binary: str | None) -> None:
    if (
        not isinstance(package, str)
        or len(package) > 214
        or not PACKAGE_RE.fullmatch(package)
    ):
        raise ValueError("package must be a normalized npm package name.")
    if not isinstance(version, str):
        raise ValueError("version must be a pinned semantic version.")
    match = VERSION_RE.fullmatch(version)
    if match is None:
        raise ValueError("version must be a pinned semantic version.")
    prerelease = match.group(1)
    if prerelease and any(
        part.isdigit() and len(part) > 1 and part.startswith("0")
        for part in prerelease.split(".")
    ):
        raise ValueError("version must be a pinned semantic version.")
    if binary is not None and (
        not isinstance(binary, str) or not NAME_RE.fullmatch(binary)
    ):
        raise ValueError("binary must be a package bin name or None.")


def _docker_environment(config_dir: Path, docker: str) -> dict[str, str]:
    # Preserve only the local daemon address, never registry credentials or the
    # caller's environment. This also supports macOS Docker/OrbStack contexts.
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        endpoint = subprocess.run(
            [docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    if not endpoint.startswith("unix:///") or any(ord(char) < 32 for char in endpoint):
        raise ValueError("MCP inspection requires a local Unix-socket Docker daemon.")
    return {
        "DOCKER_CONFIG": str(config_dir),
        "DOCKER_HOST": endpoint,
        "HOME": str(config_dir),
        "LANG": "C",
        "PATH": os.defpath,
    }


def _docker_install_args(
    work_dir: Path, container_name: str, command: list[str]
) -> list[str]:
    uid, gid = os.getuid(), os.getgid()
    return [
        "run",
        "--rm",
        "--name",
        container_name,
        "--network=bridge",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user",
        f"{uid}:{gid}",
        "--pids-limit=256",
        "--memory=2g",
        "--memory-swap=2g",
        "--cpus=2",
        "--ulimit=core=0",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=512m",
        "--mount",
        f"type=bind,source={work_dir},target=/work",
        "--workdir=/work",
        "--env=HOME=/tmp/npm-home",
        "--env=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--env=npm_config_userconfig=/dev/null",
        "--env=npm_config_globalconfig=/tmp/npm-global-config",
        "--env=npm_config_cache=/tmp/npm-cache",
        NODE_IMAGE,
        *command,
    ]


def _copy_lockfile(work_dir: Path, report_dir: Path, errors: list[str]) -> None:
    source = work_dir / "package-lock.json"
    if source.is_symlink() or not source.is_file():
        errors.append("npm did not produce a regular package-lock.json dependency lock.")
        return
    try:
        if source.stat().st_size > MAX_LOCK_BYTES:
            errors.append("package-lock.json exceeds the artifact size limit and was not copied.")
            return
        _write_artifact(report_dir, "package-lock.json", source.read_bytes())
    except OSError as error:
        errors.append(f"Could not preserve package-lock.json ({type(error).__name__}).")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _package_root(work_dir: Path, package: str) -> tuple[Path, Path]:
    node_modules = work_dir / "node_modules"
    if node_modules.is_symlink() or not node_modules.is_dir():
        raise RuntimeError("npm did not produce a regular node_modules directory.")
    node_modules_root = node_modules.resolve(strict=True)
    package_path = node_modules.joinpath(*package.split("/"))
    if package_path.is_symlink() and not package_path.exists():
        raise RuntimeError("The installed package source is unavailable.")
    try:
        package_root = package_path.resolve(strict=True)
    except OSError:
        raise RuntimeError("The installed package source is unavailable.") from None
    if (
        not package_root.is_dir()
        or package_root == node_modules_root
        or not package_root.is_relative_to(node_modules_root)
    ):
        raise RuntimeError("The installed package does not resolve inside node_modules.")
    return node_modules_root, package_root


def _load_manifest(package_root: Path) -> dict[str, Any]:
    path = package_root / "package.json"
    if path.is_symlink() or not path.is_file():
        raise PackageDefinitionError("package.json is missing or is a symlink.")
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise PackageDefinitionError("package.json exceeds the definition size limit.")
        parsed = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except PackageDefinitionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise PackageDefinitionError("package.json is not valid, unique-key JSON.") from None
    if not isinstance(parsed, dict):
        raise PackageDefinitionError("package.json must contain an object.")
    return parsed


def _resolve_binary(
    package_root: Path, package: str, manifest: dict[str, Any], binary: str | None
) -> Path:
    bin_field = manifest.get("bin")
    package_bin = package.rsplit("/", 1)[-1]
    if isinstance(bin_field, str):
        bin_entries = {package_bin: bin_field}
    elif isinstance(bin_field, dict):
        bin_entries = bin_field
    else:
        raise PackageDefinitionError("package.json does not define a usable bin entry.")
    if not bin_entries or any(
        not isinstance(name, str)
        or not NAME_RE.fullmatch(name)
        or not isinstance(path, str)
        for name, path in bin_entries.items()
    ):
        raise PackageDefinitionError("package.json contains an invalid bin definition.")

    if binary is not None:
        selected = binary
    elif package_bin in bin_entries:
        selected = package_bin
    elif len(bin_entries) == 1:
        selected = next(iter(bin_entries))
    elif len(set(bin_entries.values())) == 1:
        selected = next(iter(bin_entries))
    else:
        raise PackageDefinitionError("The default package binary is ambiguous.")
    raw_path = bin_entries.get(selected)
    if raw_path is None:
        raise PackageDefinitionError("The configured binary is not declared by the package.")
    if (
        not raw_path
        or "\\" in raw_path
        or any(ord(char) < 32 or ord(char) == 127 for char in raw_path)
    ):
        raise PackageDefinitionError("The package binary path is invalid.")
    relative = PurePosixPath(raw_path)
    parts = tuple(part for part in relative.parts if part not in ("", "."))
    if relative.is_absolute() or not parts or ".." in relative.parts:
        raise PackageDefinitionError("The package binary path must stay inside the package.")
    candidate = package_root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise PackageDefinitionError("The declared package binary does not exist.") from None
    if not resolved.is_relative_to(package_root):
        raise PackageDefinitionError("The package binary symlink escapes the package.")
    try:
        mode = resolved.stat().st_mode
    except OSError:
        raise PackageDefinitionError("The declared package binary is unavailable.") from None
    if not stat.S_ISREG(mode):
        raise PackageDefinitionError("The declared package binary is not a regular file.")
    return resolved


def _runtime_binary_args(
    node_modules_root: Path, package_root: Path, bin_path: Path
) -> list[str]:
    command_path = (
        f"/node_modules/{package_root.relative_to(node_modules_root).as_posix()}/"
        f"{bin_path.relative_to(package_root).as_posix()}"
    )
    try:
        mode = bin_path.stat().st_mode
    except OSError:
        raise PackageDefinitionError("The declared package binary is unavailable.") from None
    if mode & 0o111:
        return [command_path]
    if bin_path.suffix.lower() in {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"}:
        return ["node", command_path]
    try:
        with bin_path.open("rb") as binary_file:
            first_line = binary_file.readline(256)
    except OSError:
        raise PackageDefinitionError("The declared package binary cannot be read.") from None
    if first_line.startswith(b"#!") and any(
        part.rsplit(b"/", 1)[-1] == b"node"
        for part in first_line[2:].split()
    ):
        return ["node", command_path]
    raise PackageDefinitionError("The declared package binary is not executable.")


def _plain_model(item: Any) -> dict[str, Any]:
    if not hasattr(item, "model_dump"):
        raise SnapshotInspectionError("MCP list response contained an unsupported item.")
    value = item.model_dump(mode="json", by_alias=True, exclude_none=True)
    if not isinstance(value, dict):
        raise SnapshotInspectionError("MCP list response contained an unsupported item.")
    return value


async def _list_all(session: Any, method_name: str, result_key: str, params_type) -> list[dict[str, Any]]:
    method = getattr(session, method_name)
    cursor: str | None = None
    used_cursors: set[str] = set()
    seen_items: set[str] = set()
    collected: list[dict[str, Any]] = []
    serialized_size = 0

    for _ in range(MAX_PAGE_COUNT):
        if cursor is not None:
            if cursor in used_cursors:
                raise SnapshotInspectionError(f"MCP {result_key} listing repeated a cursor.")
            used_cursors.add(cursor)
        result = await method(params=params_type(cursor=cursor) if cursor is not None else None)
        page_items = getattr(result, result_key, None)
        if not isinstance(page_items, list):
            raise SnapshotInspectionError(f"MCP {result_key} listing returned an invalid page.")
        if len(collected) + len(page_items) > MAX_ITEMS_PER_LIST:
            raise SnapshotInspectionError(f"MCP {result_key} listing exceeded the item limit.")
        for item in page_items:
            plain = _plain_model(item)
            identity = plain.get("uri" if result_key == "resources" else "name")
            if not isinstance(identity, str) or not identity or identity in seen_items:
                raise SnapshotInspectionError(f"MCP {result_key} listing contains a missing or duplicate identity.")
            seen_items.add(identity)
            item_bytes = len(
                json.dumps(plain, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            )
            serialized_size += item_bytes
            if serialized_size > MAX_SNAPSHOT_BYTES:
                raise SnapshotInspectionError(f"MCP {result_key} listing exceeded the metadata size limit.")
            collected.append(plain)
        next_cursor = getattr(result, "next_cursor", None)
        if next_cursor is None:
            return collected
        if not isinstance(next_cursor, str) or not next_cursor:
            raise SnapshotInspectionError(f"MCP {result_key} listing returned an invalid cursor.")
        if next_cursor in used_cursors or next_cursor == cursor:
            raise SnapshotInspectionError(f"MCP {result_key} listing repeated a cursor.")
        cursor = next_cursor
    raise SnapshotInspectionError(f"MCP {result_key} listing exceeded the page limit.")


async def _drain_runtime_stderr(read_fd: int, report_dir: Path) -> None:
    kept = bytearray()
    truncated = False
    with os.fdopen(read_fd, "rb", buffering=0) as stream:
        while True:
            chunk = await asyncio.to_thread(stream.read, READ_CHUNK_BYTES)
            if not chunk:
                break
            remaining = MAX_LOG_BYTES - len(kept)
            if remaining > 0:
                kept.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated = True
    _write_log(report_dir, "mcp-runtime.stderr.log", bytes(kept), truncated)


async def _runtime_snapshot(
    docker: str,
    docker_env: dict[str, str],
    node_modules_root: Path,
    binary_command: list[str],
    report_dir: Path,
) -> dict[str, Any]:
    container_name = f"mcp-scan-{uuid.uuid4().hex}"
    args = [
        "run",
        "--rm",
        "--interactive",
        "--name",
        container_name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user=node",
        "--pids-limit=64",
        "--memory=512m",
        "--memory-swap=512m",
        "--cpus=1",
        "--ulimit=core=0",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount",
        f"type=bind,source={node_modules_root},target=/node_modules,readonly",
        "--workdir=/tmp",
        "--env=HOME=/tmp",
        "--env=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        NODE_IMAGE,
        *binary_command,
    ]
    read_fd, write_fd = os.pipe()
    stderr_task = asyncio.create_task(_drain_runtime_stderr(read_fd, report_dir))
    stderr_file = os.fdopen(write_fd, "w", encoding="utf-8", buffering=1)
    write_fd = -1
    session_env = {
        # stdio_client merges these over its small default environment. None of
        # the caller's credentials or other environment variables are inherited.
        "DOCKER_CONFIG": docker_env["DOCKER_CONFIG"],
        "DOCKER_HOST": docker_env["DOCKER_HOST"],
        "HOME": docker_env["HOME"],
        "LANG": "C",
        "LOGNAME": "scanner",
        "PATH": os.defpath,
        "SHELL": "/bin/sh",
        "TERM": "dumb",
        "USER": "scanner",
    }
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.types import PaginatedRequestParams

        server = StdioServerParameters(
            command=docker,
            args=args,
            env=session_env,
        )
        async with stdio_client(server, errlog=stderr_file) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                instructions = getattr(initialized, "instructions", None) or ""
                if not isinstance(instructions, str):
                    raise SnapshotInspectionError("MCP initialization returned invalid instructions.")
                capabilities = initialized.capabilities
                snapshot = {
                    "tools": await _list_all(session, "list_tools", "tools", PaginatedRequestParams) if capabilities.tools is not None else [],
                    "prompts": await _list_all(session, "list_prompts", "prompts", PaginatedRequestParams) if capabilities.prompts is not None else [],
                    "resources": await _list_all(session, "list_resources", "resources", PaginatedRequestParams) if capabilities.resources is not None else [],
                    "instructions": instructions,
                }
        encoded = json.dumps(snapshot, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"
        if len(encoded) > MAX_SNAPSHOT_BYTES:
            raise SnapshotInspectionError("MCP snapshot exceeded the artifact size limit.")
        _write_artifact(report_dir, "mcp-snapshot.json", encoded)
        return snapshot
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        if not stderr_file.closed:
            stderr_file.close()
        try:
            await stderr_task
        finally:
            await asyncio.shield(_remove_owned_container(docker, container_name, docker_env))


async def prepare_package(
    package: str,
    version: str,
    binary: str | None,
    work_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    """Install a pinned npm package without scripts, audit it, and inspect MCP metadata.

    The package source stays in ``work_dir/node_modules`` for the caller's static
    scanner. Audit, lockfile, snapshot, and bounded process logs are written only
    under ``report_dir``. Package install failures raise; audit, package-definition,
    and MCP failures are returned as errors without discarding usable source.
    """
    _validate_package_and_version(package, version, binary)
    work_root, reports = _validate_directories(work_dir, report_dir)
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker executable is unavailable.")

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="mcp-docker-config-") as config_temp:
        config_dir = Path(config_temp)
        docker_env = _docker_environment(config_dir, docker)
        install_name = f"mcp-scan-{uuid.uuid4().hex}"
        install_result = await _run_docker(
            docker,
            _docker_install_args(
                work_root,
                install_name,
                [
                    "npm",
                    "install",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "--save-exact",
                    "--package-lock=true",
                    f"--registry={REGISTRY}",
                    f"{package}@{version}",
                ],
            ),
            env=docker_env,
            report_dir=reports,
            log_prefix="npm-install",
            container_name=install_name,
            timeout=INSTALL_TIMEOUT_SECONDS,
        )
        _copy_lockfile(work_root, reports, errors)
        if install_result.timed_out:
            raise RuntimeError("npm install timed out; see npm-install logs.")
        if install_result.returncode != 0:
            raise RuntimeError(
                f"npm install failed with exit code {install_result.returncode}; see npm-install logs."
            )
        if install_result.stdout_truncated:
            errors.append("npm install stdout exceeded the log limit and was truncated.")

        audit_name = f"mcp-scan-{uuid.uuid4().hex}"
        audit: dict[str, Any] | None = None
        try:
            audit_result = await _run_docker(
                docker,
                _docker_install_args(
                    work_root,
                    audit_name,
                    ["npm", "audit", "--json", f"--registry={REGISTRY}"],
                ),
                env=docker_env,
                report_dir=reports,
                log_prefix="npm-audit",
                container_name=audit_name,
                timeout=AUDIT_TIMEOUT_SECONDS,
                stdout_limit=MAX_AUDIT_BYTES,
            )
        except Exception as error:
            errors.append(
                f"npm audit could not run ({type(error).__name__}); see npm-audit logs."
            )
        else:
            if audit_result.timed_out:
                errors.append("npm audit timed out; see npm-audit logs.")
            elif audit_result.stdout_truncated:
                errors.append("npm audit JSON exceeded the artifact limit and was truncated.")
            else:
                try:
                    parsed_audit = json.loads(
                        audit_result.stdout, object_pairs_hook=_unique_object
                    )
                except (UnicodeError, ValueError):
                    errors.append("npm audit did not return valid JSON; see npm-audit logs.")
                else:
                    try:
                        _write_artifact(reports, "npm-audit.json", audit_result.stdout)
                    except OSError as error:
                        errors.append(
                            f"Could not preserve npm audit JSON ({type(error).__name__})."
                        )
                    vulnerabilities = (
                        parsed_audit.get("vulnerabilities")
                        if isinstance(parsed_audit, dict)
                        else None
                    )
                    valid_vulnerabilities = isinstance(vulnerabilities, dict) and all(
                        isinstance(name, str)
                        and isinstance(item, dict)
                        and isinstance(item.get("severity"), str)
                        and item["severity"]
                        in {"info", "low", "moderate", "high", "critical"}
                        for name, item in vulnerabilities.items()
                    )
                    if (
                        not isinstance(parsed_audit, dict)
                        or not isinstance(parsed_audit.get("auditReportVersion"), int)
                        or isinstance(parsed_audit.get("auditReportVersion"), bool)
                        or not valid_vulnerabilities
                        or "error" in parsed_audit
                    ):
                        errors.append(
                            "npm audit returned an invalid or error report; see npm-audit logs."
                        )
                    else:
                        audit = parsed_audit
                        if audit_result.returncode not in (0, 1) or (
                            audit_result.returncode == 1 and not audit["vulnerabilities"]
                        ):
                            errors.append(
                                f"npm audit exited with code {audit_result.returncode}; "
                                "see npm-audit logs."
                            )
        node_modules_root, package_root = _package_root(work_root, package)
        try:
            manifest = _load_manifest(package_root)
        except PackageDefinitionError as error:
            errors.append(str(error))
            return {
                "package_root": str(package_root),
                "audit": audit,
                "snapshot": None,
                "errors": errors,
            }

        if manifest.get("name") != package:
            errors.append("Installed package name does not match the requested package.")
        if manifest.get("version") != version:
            errors.append("Installed package version does not match the exact requested version.")
        package_identity_mismatch = any(
            message.startswith("Installed package ") for message in errors
        )
        if package_identity_mismatch:
            return {
                "package_root": str(package_root),
                "audit": audit,
                "snapshot": None,
                "errors": errors,
            }

        try:
            bin_path = _resolve_binary(package_root, package, manifest, binary)
            binary_command = _runtime_binary_args(
                node_modules_root, package_root, bin_path
            )
        except PackageDefinitionError as error:
            errors.append(str(error))
            return {
                "package_root": str(package_root),
                "audit": audit,
                "snapshot": None,
                "errors": errors,
            }

        try:
            snapshot = await asyncio.wait_for(
                _runtime_snapshot(
                    docker,
                    docker_env,
                    node_modules_root,
                    binary_command,
                    reports,
                ),
                timeout=RUNTIME_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            errors.append("MCP runtime inspection timed out; see mcp-runtime.stderr.log.")
            snapshot = None
        except Exception as error:
            diagnostic = "".join(traceback.format_exception(error)).encode("utf-8")
            _write_log(reports, "mcp-runtime.exception.log", diagnostic, False)
            detail = (
                str(error)
                if isinstance(error, SnapshotInspectionError)
                else type(error).__name__
            )
            errors.append(
                f"MCP runtime inspection failed ({detail}); see mcp-runtime.exception.log and stderr log."
            )
            snapshot = None

        return {
            "package_root": str(package_root),
            "audit": audit,
            "snapshot": snapshot,
            "errors": errors,
        }
