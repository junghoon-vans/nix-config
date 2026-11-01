#!/usr/bin/env python3
"""Overlay Nix-owned settings onto the writable Hermes configuration."""

import os
from pathlib import Path
import stat
import sys
import tempfile



NIX_STORE_ROOT = Path("/nix/store")
RUNTIME_CONFIG_NAME = "config.yaml"


def _signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _legacy_store_target(path, target):
    destination = Path(target)
    if not destination.is_absolute():
        destination = path.parent / destination
    lexical_store = Path(os.path.abspath(NIX_STORE_ROOT))
    lexical_destination = Path(os.path.abspath(destination))
    if lexical_destination == lexical_store or not lexical_destination.is_relative_to(lexical_store):
        return False
    try:
        store = NIX_STORE_ROOT.resolve()
        resolved = destination.resolve()
    except OSError:
        return False
    return resolved != store and resolved.is_relative_to(store)


def _runtime_state(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    target = os.readlink(path) if stat.S_ISLNK(info.st_mode) else None
    return (_signature(info), target)


def _read_runtime_config(path):
    state = _runtime_state(path)
    if state is None:
        return state, None, None

    info = path.lstat()
    if _signature(info) != state[0]:
        raise RuntimeError("The Hermes runtime config changed while it was being inspected.")
    if stat.S_ISLNK(info.st_mode):
        if os.readlink(path) != state[1]:
            raise RuntimeError("The Hermes runtime config changed while it was being inspected.")
        if info.st_uid != os.getuid():
            raise RuntimeError("The Hermes runtime config symlink must be user-owned.")
        if not _legacy_store_target(path, state[1]):
            raise RuntimeError("Refusing to replace a runtime config symlink outside the Nix store.")
        return state, None, None
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("The Hermes runtime config must be a regular file or legacy Nix-store symlink.")
    if info.st_uid != os.getuid():
        raise RuntimeError("The Hermes runtime config must be user-owned.")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077 or mode & 0o7000:
        raise RuntimeError("The Hermes runtime config must not be accessible by group or other users.")

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _signature(opened) != state[0]:
            raise RuntimeError("The Hermes runtime config changed while it was being read.")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return state, content, mode


def _load_config(content, description):
    import yaml

    try:
        value = yaml.safe_load(content.decode("utf-8")) if content is not None else {}
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise RuntimeError(f"Could not parse {description}: {error}") from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{description} must contain a YAML mapping.")
    return value


def _managed_mcp_names(config):
    names = config.get("nix_managed_mcp_servers", [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise RuntimeError("nix_managed_mcp_servers must be a list of server names.")
    return names


def _replace_managed_mcp(previous, defaults):
    # Remember the previous generation's ownership, not its credentials. The
    # historical names also migrate profiles prepared before bookkeeping existed.
    names = set(_managed_mcp_names(previous)) | set(_managed_mcp_names(defaults))
    names.update(("notion", "github"))
    result = dict(previous)
    servers = previous.get("mcp_servers")
    if isinstance(servers, dict):
        result["mcp_servers"] = {
            name: value for name, value in servers.items() if name not in names
        }
    return result


def _overlay_config(previous, overrides):
    result = dict(previous) if isinstance(previous, dict) else {}
    for key, value in overrides.items():
        if isinstance(value, dict):
            result[key] = _overlay_config(result.get(key), value)
        else:
            result[key] = value
    return result


def _replace_runtime_config(path, content, prior_state):
    if _runtime_state(path) != prior_state:
        raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
    descriptor, temporary = tempfile.mkstemp(prefix=".config.yaml.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if _runtime_state(path) != prior_state:
            raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
        os.replace(temporary, path)
        temporary = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            os.unlink(temporary)


def prepare_runtime_config(home, defaults_path):
    import yaml

    runtime_path = Path(home) / RUNTIME_CONFIG_NAME
    state, previous_content, previous_mode = _read_runtime_config(runtime_path)
    defaults_path = Path(defaults_path)
    if not defaults_path.is_file():
        raise RuntimeError("The declared Nix Hermes config defaults are unavailable.")
    defaults = _load_config(defaults_path.read_bytes(), "the declared Nix Hermes config defaults")
    previous = _load_config(previous_content, "the existing Hermes runtime config")
    result = _overlay_config(_replace_managed_mcp(previous, defaults), defaults)
    if "nix_managed_mcp_servers" in previous or "nix_managed_mcp_servers" in defaults:
        result["nix_managed_mcp_servers"] = _managed_mcp_names(defaults)
    # External skill roots are additive; unlike route lists, Nix must not hide
    # user-declared skills when connecting the shared provider resources.
    previous_skills = previous.get("skills", {})
    declared_skills = defaults.get("skills", {})
    if isinstance(previous_skills, dict) and isinstance(declared_skills, dict):
        previous_dirs = previous_skills.get("external_dirs", [])
        declared_dirs = declared_skills.get("external_dirs")
        if isinstance(previous_dirs, list) and isinstance(declared_dirs, list):
            result["skills"]["external_dirs"] = list(dict.fromkeys([*previous_dirs, *declared_dirs]))
    content = yaml.safe_dump(result, sort_keys=False, allow_unicode=True).encode("utf-8")
    if previous_content == content and previous_mode == 0o600:
        if _runtime_state(runtime_path) != state:
            raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
        return runtime_path
    _replace_runtime_config(runtime_path, content, state)
    return runtime_path


def main():
    if len(sys.argv) != 3:
        raise RuntimeError("Usage: prepare-config.py PROFILE_HOME DEFAULTS")
    home = Path(sys.argv[1])
    info = home.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise RuntimeError("The Hermes home must be a user-owned directory not writable by others.")
    prepare_runtime_config(home, sys.argv[2])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Hermes configuration: {error}", file=sys.stderr)
        sys.exit(1)
