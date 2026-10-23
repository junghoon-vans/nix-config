#!/usr/bin/env python3
"""Launch the Nix-owned gateway without putting credentials in a derivation."""

import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile



NIX_STORE_ROOT = Path("/nix/store")
RUNTIME_CONFIG_NAME = "config.yaml"
MANAGED_CONFIG_NAME = "config.nix.yaml"


def validate_environment(config):
    from dotenv import load_dotenv

    path = Path(config["environment_file"])
    if path.resolve() != (Path(config["home"]) / ".env").resolve():
        raise RuntimeError("Validate the same .env file that Hermes loads at startup.")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("The Hermes environment file must be user-owned and mode 0600.")
    load_dotenv(path, override=True)
    if os.environ.get("HERMES_HOME") not in (None, config["home"]):
        raise RuntimeError("The private .env must not override Nix-owned HERMES_HOME.")
    for key in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
        if not os.environ.get(key, "").strip():
            raise RuntimeError(f"Missing private runtime setting: {key}")
    os.environ["HERMES_HOME"] = config["home"]
    os.umask(0o077)
    Path(config["home"], "logs").mkdir(parents=True, exist_ok=True)


def validate_runtime():
    try:
        connection = importlib.import_module("acp.client").ClientSideConnection
        if not callable(connection):
            raise TypeError("ClientSideConnection is not callable")
    except (ImportError, AttributeError, TypeError) as error:
        raise RuntimeError(
            f"Hermes ACP SDK runtime dependency unavailable: acp.client.ClientSideConnection: {error}"
        ) from error

    try:
        context = importlib.import_module("hermes_cli.plugins").PluginContext
        if not callable(context):
            raise TypeError("PluginContext is not callable")
        plugin_data_dir = importlib.import_module("plugins.plugin_storage").plugin_data_dir
        if not callable(plugin_data_dir):
            raise TypeError("plugin_data_dir is not callable")
    except (ImportError, AttributeError, TypeError) as error:
        raise RuntimeError(f"Hermes plugin runtime API unavailable: {error}") from error

    for module_name, name in (
        ("slack_bolt.async_app", "AsyncApp"),
        ("slack_bolt.adapter.socket_mode.async_handler", "AsyncSocketModeHandler"),
        ("slack_sdk.web.async_client", "AsyncWebClient"),
    ):
        try:
            getattr(importlib.import_module(module_name), name)
        except (ImportError, AttributeError) as error:
            raise RuntimeError(f"Slack runtime dependencies unavailable: {module_name}.{name}: {error}") from error


def check_runtime(config):
    result = subprocess.run([config["runtime_python"], __file__, "--runtime-check"], check=False)
    if result.returncode:
        raise RuntimeError("Hermes ACP/plugin runtime preflight failed; see the runtime error above.")


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


def _preserved_allowlist(previous):
    if "command_allowlist" not in previous:
        return None
    allowlist = previous["command_allowlist"]
    if not isinstance(allowlist, list) or any(
        not isinstance(pattern, str) or not pattern.strip() for pattern in allowlist
    ):
        raise RuntimeError("The runtime command_allowlist must be a list of non-empty strings.")
    return allowlist


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
    allowlist = _preserved_allowlist(previous)
    result = dict(defaults)
    if allowlist is not None:
        result["command_allowlist"] = allowlist
    content = yaml.safe_dump(result, sort_keys=False, allow_unicode=True).encode("utf-8")
    if previous_content == content and previous_mode == 0o600:
        if _runtime_state(runtime_path) != state:
            raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
        return runtime_path
    _replace_runtime_config(runtime_path, content, state)
    return runtime_path


def check(config):
    home = Path(config["home"])
    home_info = home.lstat()
    if (
        not stat.S_ISDIR(home_info.st_mode)
        or home_info.st_uid != os.getuid()
        or stat.S_IMODE(home_info.st_mode) & 0o022
    ):
        raise RuntimeError("The Hermes home must be a user-owned directory not writable by others.")
    validate_environment(config)
    check_runtime(config)
    defaults = Path(config["config_defaults"])
    resources = {
        MANAGED_CONFIG_NAME: defaults,
        "plugins/omp-acp-delegator": Path(config["plugin_source"]),
    }
    for relative, source in resources.items():
        target = home / relative
        if not source.exists() or target.resolve() != source.resolve():
            raise RuntimeError(f"{relative} is not the declared Nix resource; apply the Nix configuration.")
    prepare_runtime_config(home, defaults)
    return None


def main():
    if sys.argv[1:] == ["--runtime-check"]:
        validate_runtime()
        print("Hermes ACP SDK, plugin context/storage, and Slack dependencies are available.")
        return
    config = json.loads(Path(sys.argv[1]).read_text())
    check(config)
    if sys.argv[2:] == ["--check"]:
        print("Hermes plugin runtime and private Slack configuration are ready.")
        return
    if sys.argv[2:]:
        raise RuntimeError("Only --check is supported.")
    os.execv(config["hermes"], [config["hermes"], "gateway", "run", "--external-supervisor"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Hermes gateway: {error}", file=sys.stderr)
        sys.exit(1)
