#!/usr/bin/env python3

"""Merge declared Aside preferences without managing authentication or runtime state."""

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


class Deferred(Exception):
    """An activation can continue, but Aside settings have not been applied."""


def aside_is_running():
    processes = subprocess.run(
        ["/bin/ps", "-U", str(os.getuid()), "-o", "comm="],
        check=True,
        capture_output=True,
        text=True,
    )
    return any(
        Path(command.strip()).name in {"Aside", "Aside Daemon", "aside"}
        or "/Aside.app/" in command
        or "/Aside CLI.app/" in command
        for command in processes.stdout.splitlines()
    )


def profile_directory(account):
    root = Path.home() / ".aside"
    users = root / "u"
    for directory in (root, users):
        if directory.is_symlink():
            raise ValueError(f"Refusing symlinked Aside directory: {directory}")
    if not users.is_dir():
        raise Deferred("No Aside profiles yet. Open Aside and connect ChatGPT first.")
    if account is not None:
        if not account.isascii() or not account.isdecimal():
            raise ValueError("--account must be a numeric local Aside account ID")
        profile = users / account
    else:
        profiles = sorted(p for p in users.iterdir() if p.name.isascii() and p.name.isdecimal())
        if len(profiles) != 1:
            raise Deferred("Expected one Aside profile; select one with apply-aside-settings --account ID.")
        profile = profiles[0]
    if profile.is_symlink():
        raise ValueError(f"Refusing symlinked Aside profile: {profile}")
    if not profile.is_dir():
        raise Deferred("Selected Aside profile does not exist. Open Aside and connect ChatGPT first.")
    return profile


def check_file(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.getuid():
        raise ValueError(f"Expected a regular, unshared file owned by the current user: {path}")


def merge(current, declared):
    for key, value in declared.items():
        if isinstance(value, dict):
            if key not in current:
                current[key] = {}
            if not isinstance(current[key], dict):
                raise ValueError(f"Expected an object at managed settings key: {key}")
            merge(current[key], value)
        else:
            current[key] = value


def apply_settings(declared, account, dry_run):
    profile = profile_directory(account)
    if aside_is_running():
        raise Deferred("Aside is running. Quit the browser and disconnect Aside CLI/MCP clients, then run apply-aside-settings.")
    settings_path = profile / "settings.json"
    if not settings_path.exists() and not settings_path.is_symlink():
        raise Deferred("Aside has not created settings.json yet. Initialize the profile in Aside first.")
    check_file(settings_path)
    models_path = profile / "models.json"
    has_models = models_path.exists() or models_path.is_symlink()
    if has_models:
        check_file(models_path)
    original = settings_path.read_bytes()
    try:
        current = json.loads(original)
    except (ValueError, UnicodeError):
        raise ValueError("Aside settings.json is not valid JSON; nothing was changed.") from None
    if not isinstance(current, dict):
        raise ValueError("Aside settings.json must contain an object")
    before = json.dumps(current, sort_keys=True)
    merge(current, declared)
    changed = before != json.dumps(current, sort_keys=True)
    if dry_run:
        print(f"Would {'merge' if changed else 'preserve'} {settings_path}; enforce 0600 on settings.json and existing models.json.")
        return
    if changed:
        backup = settings_path.with_name("settings.json.pre-nix")
        if backup.exists() or backup.is_symlink():
            check_file(backup)
            backup.chmod(0o600)
        else:
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(original)
        descriptor, temporary = tempfile.mkstemp(prefix=".settings-nix-", dir=profile)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(current, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            if aside_is_running() or settings_path.read_bytes() != original:
                raise Deferred("Aside started or settings changed during the merge; retry after closing Aside.")
            os.replace(temporary, settings_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    settings_path.chmod(0o600)
    if has_models:
        models_path.chmod(0o600)
    print(f"Aside settings {'updated' if changed else 'already match'}: {settings_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings", type=Path, help="Nix-generated nonsecret JSON policy")
    parser.add_argument("--account", help="Local numeric account ID; auto-selected only when exactly one exists")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without writing files or changing permissions")
    parser.add_argument("--activation", action="store_true", help="Report deferred application without failing Home Manager")
    args = parser.parse_args()
    try:
        declared = json.loads(args.settings.read_text())
        if not isinstance(declared, dict):
            raise ValueError("Declared settings must contain an object")
        apply_settings(declared, args.account, args.dry_run)
    except Deferred as error:
        print(f"Aside settings deferred: {error}", file=sys.stderr)
        return 0 if args.activation else 1
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Aside settings failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
