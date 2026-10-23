#!/usr/bin/env python3
"""Archive local Hermes experiments, preserving authentication and task history."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import uuid

import yaml


NIX_STORE = Path("/nix/store")


def _is_nix_store_plugin_link(path, home):
    if not path.is_symlink():
        return False
    for parent in path.parents:
        if parent == home:
            break
        if parent.is_symlink():
            return False
    try:
        target = Path(os.readlink(path))
    except OSError:
        return False
    if not target.is_absolute():
        return False
    store = Path(os.path.abspath(NIX_STORE))
    target = Path(os.path.abspath(target))
    try:
        relative_target = target.relative_to(store)
    except ValueError:
        return False
    return bool(relative_target.parts)


class Migration:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.backup = self.home / ".local/state/hermes-migration" / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        )

    def archive(self, path, *, move=False):
        self.backup.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.backup, 0o700)
        target = self.backup / path.relative_to(self.home)
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if move:
            shutil.move(str(path), str(target))
        elif path.is_dir():
            shutil.copytree(path, target, symlinks=True)
        else:
            shutil.copy2(path, target, follow_symlinks=True)
            target.chmod(0o600)
        print(f"Archived {path.relative_to(self.home)} to {self.backup}")

    def clean(self, *, cleanup_only=False):
        config = self.home / ".hermes/config.yaml"
        if config.exists() and not (config.is_symlink() and str(config.resolve()).startswith("/nix/store/")):
            data = yaml.safe_load(config.read_text()) or {}
            plugins = data.get("plugins", {})
            enabled = plugins.get("enabled", [])
            has_orca = isinstance(enabled, list) and "orca-status" in enabled
            if not cleanup_only or has_orca:
                self.archive(config)
            if has_orca:
                plugins["enabled"] = [name for name in enabled if name != "orca-status"]
                config.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
                config.chmod(0o600)
                print("Disabled the Orca lifecycle hook.")

        plugin = self.home / ".hermes/plugins/orca-status"
        if plugin.exists() or plugin.is_symlink():
            self.archive(plugin, move=True)

        legacy_plugin = self.home / ".hermes/plugins/omp-worker"
        if not cleanup_only and _is_nix_store_plugin_link(legacy_plugin, self.home):
            self.archive(legacy_plugin, move=True)

        agents = self.home / "Library/LaunchAgents"
        # Only this known Hermes deployment is retired. Other Fleetra projects
        # and their services are deliberately outside the migration boundary.
        for path in agents.glob("*fleetra*.plist"):
            data = plistlib.loads(path.read_bytes())
            if data.get("Label") not in ("dev.fleetra.junghoon-hermes", "dev.fleetra.hermes"):
                continue
            label = data["Label"]
            domain = f"gui/{os.getuid()}/{label}"
            loaded = subprocess.run(["/bin/launchctl", "print", domain], capture_output=True)
            if loaded.returncode == 0:
                subprocess.run(["/bin/launchctl", "bootout", domain], check=True)
            self.archive(path, move=True)

        legacy_plist = agents / "ai.hermes.gateway.plist"
        if not cleanup_only and legacy_plist.is_file():
            data = plistlib.loads(legacy_plist.read_bytes())
            if not any("/nix/store/" in str(arg) for arg in data.get("ProgramArguments", [])):
                self.archive(legacy_plist)

        orca = self.home / "orca"
        if not orca.is_symlink():
            for path in (orca / "workspaces", orca):
                if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                    path.rmdir()
                    print(f"Removed empty experiment directory {path.relative_to(self.home)}")
        (self.home / ".hermes/logs").mkdir(parents=True, mode=0o700, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("home", type=Path)
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    if args.home.resolve() != Path.home().resolve():
        raise SystemExit("Run this migration as the target user, not as root.")
    os.umask(0o077)
    Migration(args.home).clean(cleanup_only=args.cleanup_only)


if __name__ == "__main__":
    main()
