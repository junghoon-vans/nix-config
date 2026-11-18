import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import apm_lock


class APMReleaseLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "skills/local-skill").mkdir(parents=True)
        self.manifest = b"name: updater-regression\nversion: 1.0.0\n"
        (self.root / "apm.yml").write_bytes(self.manifest)
        (self.root / "skills/local-skill/SKILL.md").write_text("authored locally\n")
        self.remote = {
            "repo_url": "example/remote",
            "name": "remote-skill",
            "resolved_commit": "a" * 40,
            "resolved_ref": "v1.0.0",
            "exec_status": {"approved": True},
            "deployed_file_hashes": {
                ".agents/skills/remote-skill/SKILL.md": "sha256:remote-old"
            },
        }
        self.local = {
            "repo_url": "_local/local-skill",
            "name": "local-skill",
            "source": "local",
            "local_path": "./skills/local-skill",
            "content_hash": "sha256:local-attestation",
            "deployed_file_hashes": {
                ".agents/skills/local-skill/SKILL.md": "sha256:local-attestation"
            },
        }
        self.local_row = {
            "value": ".agents/skills/local-skill/SKILL.md",
            "owners": ["./skills/local-skill"],
            "content_hash": "sha256:local-attestation",
        }
        self.remote_row = {
            "value": ".agents/skills/remote-skill/SKILL.md",
            "owners": ["remote-skill"],
            "content_hash": "sha256:remote-old",
        }
        self.original_lock = {
            "lockfile_version": "1",
            "apm_version": "0.35.1",
            "dependencies": [self.remote.copy(), self.local.copy()],
            "deployments": [self.remote_row.copy(), self.local_row.copy()],
        }
        self.write_lock(self.original_lock)

    def write_lock(self, lock):
        (self.root / "apm.lock.yaml").write_text(yaml.safe_dump(lock, sort_keys=False))

    def fake_apm(self, *, changed_commit=False, installed_version="0.36.0", global_install=True):
        commands = []

        def run(command, *, cwd, env, check):
            commands.append((command, cwd, env, check))
            lock_path = Path(cwd) / "apm.lock.yaml"
            lock = yaml.safe_load(lock_path.read_text())
            if command[1] == "lock":
                lock["apm_version"] = installed_version
                if changed_commit:
                    lock["dependencies"][0]["resolved_commit"] = "b" * 40
            else:
                expected = ["/selected/apm", "install"]
                if global_install:
                    expected.append("--global")
                expected.extend(["--target", "agent-skills", "--only", "apm", "--trust-bin"])
                self.assertEqual(command, expected)
                lock["dependencies"][0]["exec_status"] = {"approved": False}
                lock["dependencies"][0]["deployed_file_hashes"][
                    ".agents/skills/remote-skill/LICENSE"
                ] = "sha256:new-license"
                lock["dependencies"][1]["content_hash"] = "sha256:changed-local"
                lock["dependencies"][1]["deployed_file_hashes"][
                    ".agents/skills/local-skill/SKILL.md"
                ] = "sha256:changed-local"
                lock["deployments"] = [
                    self.remote_row | {"content_hash": "sha256:new-remote"},
                    self.local_row | {"content_hash": "sha256:changed-local"},
                ]
            lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
            return SimpleNamespace(returncode=0)

        return commands, run

    def test_cli_only_refresh_uses_global_lock_without_moving_dependency_commits(self):
        commands, fake_run = self.fake_apm()
        with patch.object(apm_lock.subprocess, "run", side_effect=fake_run):
            apm_lock.regenerate_lock(
                self.root,
                "/selected/apm",
                update_dependencies=False,
                expected_apm_version="0.36.0",
            )

        self.assertEqual([command for command, *_ in commands], [
            ["/selected/apm", "lock"],
            ["/selected/apm", "install", "--global", "--target", "agent-skills",
             "--only", "apm", "--trust-bin"],
        ])
        self.assertTrue(all(Path(cwd).name == ".apm" for _, cwd, *_ in commands))
        self.assertTrue(all(Path(env["HOME"]) == Path(cwd).parent for _, cwd, env, _ in commands))
        lock = yaml.safe_load((self.root / "apm.lock.yaml").read_text())
        remote, local = lock["dependencies"]
        self.assertEqual(lock["apm_version"], "0.36.0")
        self.assertEqual(remote["resolved_commit"], "a" * 40)
        self.assertEqual(remote["exec_status"], {"approved": True})
        self.assertEqual(
            remote["deployed_file_hashes"][".agents/skills/remote-skill/LICENSE"],
            "sha256:new-license",
        )
        self.assertEqual(local, self.local)
        self.assertIn(self.local_row, lock["deployments"])
        self.assertIn(
            self.remote_row | {"content_hash": "sha256:new-remote"},
            lock["deployments"],
        )
        self.assertEqual((self.root / "apm.yml").read_bytes(), self.manifest)
        self.assertEqual(
            (self.root / "skills/local-skill/SKILL.md").read_text(), "authored locally\n"
        )

    def test_tagged_refresh_keeps_updating_refs_in_project_scope(self):
        commands, fake_run = self.fake_apm(changed_commit=True, global_install=False)
        with patch.object(apm_lock.subprocess, "run", side_effect=fake_run):
            apm_lock.regenerate_lock(self.root, "/selected/apm")

        self.assertEqual([command for command, *_ in commands], [
            ["/selected/apm", "lock", "--update"],
            ["/selected/apm", "install", "--target", "agent-skills",
             "--only", "apm", "--trust-bin"],
        ])
        lock = yaml.safe_load((self.root / "apm.lock.yaml").read_text())
        self.assertEqual(lock["dependencies"][0]["resolved_commit"], "b" * 40)
        self.assertEqual(lock["dependencies"][0]["exec_status"], {"approved": True})
        self.assertEqual(lock["dependencies"][1], self.local)
        self.assertIn(self.local_row, lock["deployments"])

    def test_cli_only_refresh_refuses_dependency_commit_drift_without_publishing(self):
        before = (self.root / "apm.lock.yaml").read_bytes()
        commands, fake_run = self.fake_apm(changed_commit=True)
        with patch.object(apm_lock.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "changed dependency commit"):
                apm_lock.regenerate_lock(
                    self.root,
                    "/selected/apm",
                    update_dependencies=False,
                    expected_apm_version="0.36.0",
                )
        self.assertEqual(len(commands), 1)
        self.assertEqual((self.root / "apm.lock.yaml").read_bytes(), before)

    def test_cli_only_refresh_requires_the_selected_apm_version(self):
        before = (self.root / "apm.lock.yaml").read_bytes()
        commands, fake_run = self.fake_apm(installed_version="0.37.0")
        with patch.object(apm_lock.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "expected 0.36.0"):
                apm_lock.regenerate_lock(
                    self.root,
                    "/selected/apm",
                    update_dependencies=False,
                    expected_apm_version="0.36.0",
                )
        self.assertEqual(len(commands), 1)
        self.assertEqual((self.root / "apm.lock.yaml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
