#!/usr/bin/env python3

import hashlib
import json
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


def simulate_remount(home):
    receipt = next((home / ".apm/deployment-receipts").glob("*.json"))
    data = json.loads(receipt.read_text())
    data["root_identity"][0] += 2
    receipt.write_text(json.dumps(data))
    return receipt


def main():
    repository, home, apm = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    environment = dict(os.environ, HOME=str(home))
    command = ["bash", str(repository / "scripts/apm/setup-apm.sh"), str(repository), apm]
    subprocess.run(command, env=environment, check=True)
    baseline = check_deployment(repository, home)
    simulate_remount(home)
    subprocess.run(command, env=environment, check=True)
    check_deployment(repository, home)
    skill = home / ".agents/skills/documentation/SKILL.md"
    edited = skill.read_bytes() + b"\nLocal user note.\n"
    skill.write_bytes(edited)
    unrelated = home / ".agents/skills/local-only/SKILL.md"
    unrelated.parent.mkdir()
    unrelated.write_text("User-owned skill.\n")
    simulate_remount(home)
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
    # Device changes are recoverable, but a different installation or directory
    # must still fail closed without rewriting evidence or deployed user edits.
    receipt = simulate_remount(home)
    valid = json.loads(receipt.read_text())
    for field, value in (
        ("installation", "0" * 32),
        ("root_identity", [valid["root_identity"][0], home.stat().st_ino + 1]),
    ):
        invalid = dict(valid)
        invalid[field] = value
        contents = json.dumps(invalid)
        receipt.write_text(contents)
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        assert result.returncode != 0, f"Accepted mismatched {field}"
        assert receipt.read_text() == contents, f"Rewrote mismatched {field}"
        assert skill.read_bytes() == edited, f"Changed local edits with mismatched {field}"
    receipt.write_text(json.dumps(valid))
    subprocess.run(command, env=environment, check=True)
    check_deployment(repository, home, {relative: "sha256:" + hashlib.sha256(edited).hexdigest()})
    print("Global deployment verified: remount recovery, invalid bindings refused, local edits preserved.")


if __name__ == "__main__":
    main()
