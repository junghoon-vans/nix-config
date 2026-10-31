import importlib.util
import os
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
