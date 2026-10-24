#!/usr/bin/env python3

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import yaml


def load_lock(path):
    return yaml.safe_load(path.read_text())


def check_deployment(repository, home, overrides=None):
    source = load_lock(repository / "apm.lock.yaml")
    installed = load_lock(home / ".apm/apm.lock.yaml")
    overrides = overrides or {}
    # Verify the complete committed skill payload, not just CLI exit status.
    for dependency in source["dependencies"]:
        for relative, expected in dependency.get("deployed_file_hashes", {}).items():
            expected = overrides.get(relative, expected)
            path = home / relative
            assert path.is_file(), f"Missing deployed file: {relative}"
            actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == expected, f"Unexpected deployed content: {relative}"
    records = installed.get("deployments", [])
    assert records, "Global installation did not record deployment ownership"
    return installed


def main():
    repository, home, apm = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    environment = dict(os.environ, HOME=str(home))
    command = ["bash", str(repository / "scripts/apm/setup-apm.sh"), str(repository), apm]
    subprocess.run(command, env=environment, check=True)
    baseline = check_deployment(repository, home)
    subprocess.run(command, env=environment, check=True)
    check_deployment(repository, home)
    skill = home / ".agents/skills/documentation/SKILL.md"
    edited = skill.read_bytes() + b"\nLocal user note.\n"
    skill.write_bytes(edited)
    unrelated = home / ".agents/skills/local-only/SKILL.md"
    unrelated.parent.mkdir()
    unrelated.write_text("User-owned skill.\n")
    subprocess.run(command, env=environment, check=True)
    assert skill.read_bytes() == edited, "Reinstall overwrote a user-edited skill"
    assert unrelated.read_text() == "User-owned skill.\n", "Reinstall removed a user-owned skill"
    relative = ".agents/skills/documentation/SKILL.md"
    installed = check_deployment(
        repository, home, {relative: "sha256:" + hashlib.sha256(edited).hexdigest()}
    )
    before = [row for row in baseline["deployments"] if row["value"] == relative]
    after = [row for row in installed["deployments"] if row["value"] == relative]
    assert before and after == before, "Reinstall replaced the original deployment baseline"
    print("Global deployment verified: complete payload, deployment receipts, local edits preserved.")


if __name__ == "__main__":
    main()
