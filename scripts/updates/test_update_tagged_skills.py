import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

SPEC = importlib.util.spec_from_file_location(
    "update_tagged_skills", Path(__file__).with_name("update-tagged-skills.py")
)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


@unittest.skipUnless(os.environ.get("APM_TEST_APM"), "set APM_TEST_APM to the pinned APM executable")
class TaggedSkillsDeploymentTests(unittest.TestCase):
    def test_tag_update_refreshes_attestation_without_adopting_local_edits(self):
        apm = os.environ["APM_TEST_APM"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "skills").mkdir()
            manifest = {
                "name": "updater-regression", "version": "1.0.0",
                "dependencies": {"apm": [{
                    "git": "https://github.com/mattpocock/skills.git",
                    "path": "skills/engineering/diagnosing-bugs", "ref": "v1.3.1",
                }]},
            }
            (root / "apm.yml").write_text(yaml.safe_dump(manifest))
            home = root / "home"
            home.mkdir()
            environment = dict(os.environ, HOME=str(home))
            subprocess.run(
                [apm, "install", "--target", "agent-skills", "--only", "apm"],
                cwd=root, env=environment, check=True, capture_output=True,
            )
            relative = ".agents/skills/diagnosing-bugs/SKILL.md"
            deployed = root / relative
            local_edit = deployed.read_bytes() + b"Local user note.\n"
            deployed.write_bytes(local_edit)
            manifest["dependencies"]["apm"][0]["ref"] = "v1.3.2"
            (root / "apm.yml").write_text(yaml.safe_dump(manifest))
            home_before = {
                str(path.relative_to(home)): path.read_bytes()
                for path in home.rglob("*") if path.is_file()
            }
            with patch.dict(os.environ, HOME=str(home)):
                updater.regenerate_lock(root, apm)
            lock = yaml.safe_load((root / "apm.lock.yaml").read_text())
            # Published v1.3.2 payload, independently observed in the original CI replay.
            expected = "sha256:849198df88cdb65fd0d97236604c1fca7ff2f22d2f705f9724a800d0266b118d"
            self.assertEqual(lock["dependencies"][0]["deployed_file_hashes"][relative], expected)
            rows = [row for row in lock["deployments"] if row["value"] == relative]
            self.assertEqual([row["content_hash"] for row in rows], [expected])
            self.assertEqual(deployed.read_bytes(), local_edit)
            self.assertEqual({
                str(path.relative_to(home)): path.read_bytes()
                for path in home.rglob("*") if path.is_file()
            }, home_before)


class TaggedSkillsRefUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fake_script = self.root / "scripts/updates/update-tagged-skills.py"
        self.fake_script.parent.mkdir(parents=True)
        self.manifest_path = self.root / "apm.yml"

    def write_manifest(self, dependencies):
        self.manifest_path.write_text(yaml.safe_dump({
            "name": "updater-fixture",
            "version": "1.0.0",
            "dependencies": {"apm": dependencies},
        }, sort_keys=False))

    def run_update(self):
        with patch.object(updater, "__file__", str(self.fake_script)), \
             patch.object(sys, "argv", ["update-tagged-skills.py", "--apm", "/pinned/apm"]):
            updater.main()

    def test_current_tags_do_not_rewrite_manifest_or_regenerate_lock(self):
        self.write_manifest([
            {"git": "https://github.com/owner/skills.git", "path": "skills/one", "ref": "v1.2.3"},
            {"git": "https://github.com/owner/skills.git", "path": "skills/two", "ref": "v1.2.3"},
        ])
        original = self.manifest_path.read_text()
        with patch.object(updater, "github_tags", return_value=["v1.2.3", "v1.2.2"]) as tags, \
             patch.object(updater, "regenerate_lock") as regenerate:
            self.run_update()

        self.assertEqual(self.manifest_path.read_text(), original)
        tags.assert_called_once_with("owner/skills")
        regenerate.assert_not_called()

    def test_grouped_tag_updates_preserve_each_dependency_tag_policy(self):
        self.write_manifest([
            {"git": "https://github.com/owner/semver.git", "path": "skills/one", "ref": "v1.0.0"},
            {"git": "https://github.com/owner/semver.git", "path": "skills/two", "ref": "v2.0.0"},
            {"git": "https://github.com/owner/generated.git", "path": "skills/three",
             "ref": "agent-skills-" + "a" * 40},
        ])
        tags_by_repository = {
            "owner/semver": ["v2.1.0", "v2.0.0", "v1.0.0"],
            "owner/generated": ["agent-skills-" + "b" * 40, "agent-skills-" + "a" * 40],
        }
        with patch.object(updater, "github_tags", side_effect=tags_by_repository.get), \
             patch.object(updater, "regenerate_lock"):
            self.run_update()

        refs = [entry["ref"] for entry in yaml.safe_load(self.manifest_path.read_text())["dependencies"]["apm"]]
        self.assertEqual(refs, ["v2.1.0", "v2.1.0", "agent-skills-" + "b" * 40])


if __name__ == "__main__":
    unittest.main()
