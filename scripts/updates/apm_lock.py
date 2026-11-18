import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml


def _identity(dependency):
    return (
        dependency["repo_url"],
        dependency.get("virtual_path"),
        dependency.get("alias"),
        dependency.get("local_path"),
    )


def _dependencies(lock):
    dependencies = {_identity(dependency): dependency for dependency in lock["dependencies"]}
    if len(dependencies) != len(lock["dependencies"]):
        raise ValueError("APM lock contains duplicate dependency identities")
    return dependencies


def _assert_same_dependencies(before, after):
    previous = _dependencies(before)
    current = _dependencies(after)
    if previous.keys() != current.keys():
        raise ValueError("APM lock resolution changed dependency identities without --update")
    for identity, dependency in previous.items():
        if dependency.get("source") != "local" and (
            dependency.get("resolved_commit") != current[identity].get("resolved_commit")
        ):
            raise ValueError(f"APM lock resolution changed dependency commit for {identity[0]}")


def _assert_apm_version(apm, expected_version, *, cwd, env):
    if expected_version is None:
        return
    result = subprocess.run(
        [apm, "--version"], cwd=cwd, env=env, check=True,
        capture_output=True, text=True,
    )
    match = re.fullmatch(
        r"Agent Package Manager \(APM\) CLI version (\S+)(?: \([^)]+\))?",
        result.stdout.strip(),
    )
    if match is None or match[1] != expected_version:
        raise ValueError(
            f"APM executable reports {result.stdout.strip()!r}, expected {expected_version}"
        )


def regenerate_lock(
    root: Path,
    apm: str,
    *,
    update_dependencies: bool = True,
    expected_apm_version: str | None = None,
) -> None:
    """Regenerate deployment hashes without adopting local edits or receipts.

    CLI-only refreshes use the global install layout used by setup-apm.sh and
    never ask APM to update manifest refs. Tagged-skill refreshes retain their
    existing project-scope update behavior.
    """
    root = Path(root)
    original = yaml.safe_load((root / "apm.lock.yaml").read_text())
    with tempfile.TemporaryDirectory(prefix=".apm-update-", dir=root) as directory:
        home = Path(directory)
        staging = home / ("project" if update_dependencies else ".apm")
        staging.mkdir(parents=True)
        for name in ("apm.yml", "apm.lock.yaml"):
            shutil.copy2(root / name, staging / name)
        shutil.copytree(root / "skills", staging / "skills")
        environment = dict(os.environ, HOME=str(home))
        # apm_version records the last lock producer, not necessarily this CLI:
        # upstream preserves it when resolution/deployment is a semantic no-op.
        _assert_apm_version(apm, expected_apm_version, cwd=staging, env=environment)
        lock_command = [apm, "lock"]
        if update_dependencies:
            lock_command.append("--update")
        subprocess.run(lock_command, cwd=staging, env=environment, check=True)
        resolved = yaml.safe_load((staging / "apm.lock.yaml").read_text())
        if not update_dependencies:
            _assert_same_dependencies(original, resolved)

        install_command = [apm, "install"]
        if not update_dependencies:
            # This is the production global install layout; project installs
            # apply different executable approval semantics in APM 0.36.
            install_command.append("--global")
        install_command.extend(
            ["--target", "agent-skills", "--only", "apm", "--trust-bin"]
        )
        subprocess.run(install_command, cwd=staging, env=environment, check=True)
        materialized = yaml.safe_load((staging / "apm.lock.yaml").read_text())
        if not update_dependencies:
            _assert_same_dependencies(original, materialized)

        # Preserve user-scope authored content and approval state from the
        # committed lock. Tagged updates instead preserve state from lock-only
        # resolution, which may include their intentionally changed refs.
        preserved = resolved if update_dependencies else original
        prior = _dependencies(preserved)
        local_owners = {
            dependency["local_path"]
            for dependency in preserved["dependencies"]
            if dependency.get("source") == "local"
        }
        for index, dependency in enumerate(materialized["dependencies"]):
            previous = prior[_identity(dependency)]
            if dependency.get("source") == "local":
                materialized["dependencies"][index] = previous
            elif "exec_status" in previous:
                dependency["exec_status"] = previous["exec_status"]
            else:
                dependency.pop("exec_status", None)
        materialized["deployments"] = [
            row for row in materialized.get("deployments", [])
            if not local_owners.intersection(row.get("owners", []))
        ] + [
            row for row in preserved.get("deployments", [])
            if local_owners.intersection(row.get("owners", []))
        ]
        (root / "apm.lock.yaml").write_text(
            yaml.safe_dump(materialized, sort_keys=False, allow_unicode=True)
        )
