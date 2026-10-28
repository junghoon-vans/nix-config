import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
DETECTOR = REPOSITORY / ".github/scripts/detect-nix-config-changes"


class ConfigurationChangeDetection(unittest.TestCase):
    def test_release_pin_only_update_requires_full_configuration_checks(self):
        self.check_changed_path("release-pins.json")

    def test_packaged_integration_only_update_requires_full_configuration_checks(self):
        self.check_changed_path("tests/hermes/test_packaged_runtime.py")

    def check_changed_path(self, changed_path):
        with tempfile.TemporaryDirectory(prefix="configuration-ci-") as directory:
            root = Path(directory)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            environment.update({
                "HOME": str(root),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "CI test",
                "GIT_AUTHOR_EMAIL": "ci@example.invalid",
                "GIT_COMMITTER_NAME": "CI test",
                "GIT_COMMITTER_EMAIL": "ci@example.invalid",
                "GITHUB_OUTPUT": str(root / "workflow-output"),
            })

            def git(*arguments):
                return subprocess.run(
                    ["git", *arguments], cwd=root, env=environment,
                    check=True, capture_output=True, text=True,
                ).stdout.strip()

            validator = root / "scripts/validation/check-release-pins.py"
            validator.parent.mkdir(parents=True)
            shutil.copyfile(REPOSITORY / "scripts/validation/check-release-pins.py", validator)
            pins = json.loads((REPOSITORY / "release-pins.json").read_text())
            pin_path = root / "release-pins.json"
            pin_path.write_text(json.dumps(pins))
            git("init", "-q")
            git("add", ".")
            git("commit", "-qm", "Initial release pins")
            base = git("rev-parse", "HEAD")
            if changed_path == "release-pins.json":
                pins["apm"]["version"] = "0.0.0-ci-regression"
                pin_path.write_text(json.dumps(pins))
            else:
                integration_test = root / changed_path
                integration_test.parent.mkdir(parents=True)
                integration_test.write_text("# Packaged integration regression\n")
            git("add", changed_path)
            git("commit", "-qm", "Update only the tested configuration path")
            head = git("rev-parse", "HEAD")

            subprocess.run(
                ["bash", str(DETECTOR), base, head], cwd=root, env=environment,
                check=True, capture_output=True, text=True,
            )

            self.assertEqual((root / "workflow-output").read_text(), "configuration_changed=true\n")


if __name__ == "__main__":
    unittest.main()
