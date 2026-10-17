#!/usr/bin/env python3
"""Launch the Nix-owned gateway without putting credentials in a derivation."""

import json
import os
from pathlib import Path
import stat
import sys


def validate_environment(config, version):
    from dotenv import load_dotenv

    if version != config["expected_version"]:
        raise RuntimeError(
            f"Hermes {version} does not match the declared API version "
            f"{config['expected_version']}; reconcile the Nix pin before starting."
        )
    path = Path(config["environment_file"])
    if path.resolve() != (Path(config["home"]) / ".env").resolve():
        raise RuntimeError("Validate the same .env file that Hermes loads at startup.")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("The Hermes environment file must be user-owned and mode 0600.")
    managed = {key: os.environ.get(key) for key in ("OMP_WORKER_CONFIG", "HERMES_HOME")}
    load_dotenv(path, override=True)
    for key, expected in managed.items():
        if key == "HERMES_HOME":
            expected = config["home"]
        if os.environ.get(key) not in (None, expected):
            raise RuntimeError(f"The private .env must not override Nix-owned {key}.")
    for key in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USERS"):
        if not os.environ.get(key, "").strip():
            raise RuntimeError(f"Missing private runtime setting: {key}")
    allowed = [value.strip() for value in os.environ["SLACK_ALLOWED_USERS"].split(",")]
    if not allowed or any(not value or value[0] not in "UW" or not value.isalnum() for value in allowed):
        raise RuntimeError("SLACK_ALLOWED_USERS must be comma-separated explicit Slack user IDs.")
    if os.environ.get("SLACK_ALLOW_ALL_USERS", "").lower() in ("1", "true", "yes"):
        raise RuntimeError("SLACK_ALLOW_ALL_USERS is not permitted for the coding gateway.")
    os.environ["HERMES_HOME"] = config["home"]
    os.umask(0o077)
    Path(config["home"], "logs").mkdir(parents=True, exist_ok=True)


def check(config):
    from hermes_cli import __version__

    validate_environment(config, __version__)
    home = Path(config["home"])
    resources = {
        "config.yaml": config["managed_config"],
        "plugins/omp-worker": config["plugin_source"],
    }
    for relative, source in resources.items():
        if (home / relative).resolve() != Path(source).resolve():
            raise RuntimeError(f"{relative} is not the declared Nix resource; apply the Nix configuration.")


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    check(config)
    if sys.argv[2:] == ["--check"]:
        print("Hermes version and private Slack configuration are ready.")
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
