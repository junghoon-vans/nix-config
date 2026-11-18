#!/usr/bin/env python3

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def load_lock(path):
    return yaml.safe_load(path.read_text())


def apm_version(apm):
    result = subprocess.run([apm, "--version"], check=True, capture_output=True, text=True)
    output = result.stdout + result.stderr
    match = re.search(r"\bversion\s+(\d+)\.(\d+)\.(\d+)\b", output)
    assert match, f"Could not parse APM version from {output!r}"
    return tuple(map(int, match.groups()))


def check_deployment(repository, home, overrides=None):
    source = load_lock(repository / "apm.lock.yaml")
    overrides = overrides or {}
    # Verify the complete committed skill payload, not just CLI exit status.
    for dependency in source["dependencies"]:
        for relative, expected in dependency.get("deployed_file_hashes", {}).items():
            expected = overrides.get(relative, expected)
            path = home / relative
            assert path.is_file(), f"Missing deployed file: {relative}"
            actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == expected, f"Unexpected deployed content: {relative}"
    assert (home / ".apm/apm.lock.yaml").read_bytes() == (
        repository / "apm.lock.yaml"
    ).read_bytes(), "Install did not preserve the committed lock byte-for-byte"
    receipts = list((home / ".apm/deployment-receipts").glob("*.json"))
    assert receipts, "Global installation did not record deployment ownership"
    assert any(
        json.loads(path.read_text()).get("scope") == "user" for path in receipts
    ), "Global installation did not record user-scope ownership"
    for dependency in source["dependencies"]:
        if dependency.get("source") != "local":
            continue
        directory = repository / dependency["local_path"]
        for path in directory.rglob("*"):
            if path.is_file():
                deployed = home / ".agents/skills" / dependency["name"] / path.relative_to(directory)
                assert deployed.read_bytes() == path.read_bytes(), (
                    f"Authored skill asset was not deployed by APM: {deployed}"
                )


def simulate_remount(home):
    receipt = next((home / ".apm/deployment-receipts").glob("*.json"))
    data = json.loads(receipt.read_text())
    data["root_identity"][0] += 2
    receipt.write_text(json.dumps(data))
    return receipt


def check_rejected_inputs(repository, home, apm, environment):
    fixture = home / "invalid-inputs"
    fixture.mkdir()
    shutil.copytree(repository / "skills", fixture / "skills")
    manifest = (repository / "apm.yml").read_bytes()
    locked = (repository / "apm.lock.yaml").read_bytes()
    (fixture / "apm.yml").write_bytes(manifest)
    (fixture / "apm.lock.yaml").write_bytes(locked)
    local = fixture / "skills/jira-cloud-formatting/SKILL.md"
    original = local.read_bytes()

    def snapshot():
        paths = [home / ".agents", home / ".apm/deployment-receipts", home / ".apm/skills"]
        result = {
            str(path.relative_to(home)): path.read_bytes()
            for root in paths
            for path in root.rglob("*")
            if path.is_file()
        }
        for name in ("apm.yml", "apm.lock.yaml"):
            result[name] = (home / ".apm" / name).read_bytes()
        return result

    baseline = snapshot()
    for failure in ("missing lock", "manifest drift", "local content drift"):
        (fixture / "apm.yml").write_bytes(manifest)
        (fixture / "apm.lock.yaml").write_bytes(locked)
        local.write_bytes(original)
        if failure == "missing lock":
            (fixture / "apm.lock.yaml").unlink()
        elif failure == "manifest drift":
            data = yaml.safe_load(manifest)
            data["dependencies"]["apm"].append({"path": "./skills/not-locked"})
            (fixture / "apm.yml").write_text(yaml.safe_dump(data))
        else:
            local.write_bytes(original + b"\nUnreviewed skill change.\n")
        result = subprocess.run(
            ["bash", str(repository / "scripts/apm/setup-apm.sh"), str(fixture), apm],
            env=environment, capture_output=True, text=True,
        )
        assert result.returncode != 0, f"Accepted {failure}"
        assert snapshot() == baseline, f"Changed deployment or inputs after {failure}"
    shutil.rmtree(fixture)


def check_project_scope(repository, home, apm, environment):
    project = home / "project"
    project.mkdir()
    shutil.copytree(repository / "skills", project / "skills")
    (project / "apm.yml").write_text(yaml.safe_dump({
        "name": "project-skills",
        "version": "1.0.0",
        "dependencies": {"apm": [{"path": "./skills/jira-cloud-formatting"}]},
    }))
    global_inputs = {
        name: (home / ".apm" / name).read_bytes()
        for name in ("apm.yml", "apm.lock.yaml")
    }
    command = [apm, "install", "--target", "agent-skills", "--only", "apm"]
    subprocess.run(command, cwd=project, env=environment, check=True)
    lock = (project / "apm.lock.yaml").read_bytes()
    subprocess.run(command + ["--frozen"], cwd=project, env=environment, check=True)
    assert (project / "apm.lock.yaml").read_bytes() == lock, "Project frozen install changed lock"
    assert (project / ".agents/skills/jira-cloud-formatting/SKILL.md").read_bytes() == (
        repository / "skills/jira-cloud-formatting/SKILL.md"
    ).read_bytes(), "Project did not materialize its authored skill"
    for name, content in global_inputs.items():
        assert (home / ".apm" / name).read_bytes() == content, "Project replaced global inputs"


def main():
    repository, home, apm = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    environment = dict(os.environ, HOME=str(home))
    command = ["bash", str(repository / "scripts/apm/setup-apm.sh"), str(repository), apm]
    frozen_checks_hashes = apm_version(apm) >= (0, 36, 0)
    # An old machine lock must never override reviewed repository resolutions.
    (home / ".apm").mkdir(exist_ok=True)
    (home / ".apm/apm.lock.yaml").write_text("lockfile_version: '1'\ndependencies: []\n")
    subprocess.run(command, env=environment, check=True)
    check_deployment(repository, home)
    simulate_remount(home)
    subprocess.run(command, env=environment, check=True)
    check_deployment(repository, home)
    skill = home / ".agents/skills/documentation/SKILL.md"
    relative = ".agents/skills/documentation/SKILL.md"
    original_skill = skill.read_bytes()
    edited = original_skill + b"\nLocal user note.\n"
    skill.write_bytes(edited)
    unrelated = home / ".agents/skills/local-only/SKILL.md"
    unrelated.parent.mkdir()
    unrelated.write_text("User-owned skill.\n")
    simulate_remount(home)
    lock_before_edit_check = (home / ".apm/apm.lock.yaml").read_bytes()
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if frozen_checks_hashes:
        assert result.returncode != 0, "APM 0.36+ accepted an edited file in a frozen install"
        assert "--frozen" in output and relative in output, (
            f"APM 0.36+ failed for a reason other than the edited locked file:\n{output}"
        )
        assert (home / ".apm/apm.lock.yaml").read_bytes() == lock_before_edit_check, (
            "Rejected frozen install changed the user lock"
        )
    else:
        assert result.returncode == 0, output
    assert skill.read_bytes() == edited, "Reinstall overwrote a user-edited skill"
    assert unrelated.read_text() == "User-owned skill.\n", "Reinstall removed a user-owned skill"
    check_deployment(
        repository, home, {relative: "sha256:" + hashlib.sha256(edited).hexdigest()}
    )
    if frozen_checks_hashes:
        # APM 0.36+ correctly refuses the edited file; restore the committed bytes
        # before proving a valid frozen install and testing receipt rejection.
        skill.write_bytes(original_skill)
        subprocess.run(command, env=environment, check=True)
        check_deployment(repository, home)
        protected_skill = skill.read_bytes()
    else:
        protected_skill = edited
    # Device changes are recoverable, but a different installation or directory
    # must still fail closed without rewriting evidence or deployed skill content.
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
        assert skill.read_bytes() == protected_skill, "Changed deployed skill with mismatched receipt"
    receipt.write_text(json.dumps(valid))
    subprocess.run(command, env=environment, check=True)
    if frozen_checks_hashes:
        check_deployment(repository, home)
        edit_policy = "edited frozen hashes refused without writes"
    else:
        check_deployment(
            repository, home, {relative: "sha256:" + hashlib.sha256(edited).hexdigest()}
        )
        edit_policy = "edited skills preserved"
    check_rejected_inputs(repository, home, apm, environment)
    check_project_scope(repository, home, apm, environment)
    assert not (home / ".agents/skills/officecli").exists(), "Common setup deployed a host-only skill"
    print("Global frozen deployment verified: tracked lock, authored skill, repeat install, "
          f"remount recovery, {edit_policy}, invalid bindings and inputs refused, project scope isolated.")


if __name__ == "__main__":
    main()
