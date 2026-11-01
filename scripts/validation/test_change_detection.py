import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
DETECTOR = REPOSITORY / ".github/scripts/detect-nix-config-changes"
GATE = REPOSITORY / ".github/scripts/require-nix-validation"


class ConfigurationChangeDetection(unittest.TestCase):
    def test_classification(self):
        cases = [
            (["apm.yml"], True),
            (["apm.lock.yaml"], True),
            (["skills/local/SKILL.md"], True),
            (["apm.yml", "apm.lock.yaml", "docs/skills.md"], True),
            (["skills/local/SKILL.md", "modules/hermes.nix"], False),
            (["skills/local/SKILL.md", "README.md"], False),
            (["release-pins.json"], False),
            (["tests/hermes/test_packaged_runtime.py"], False),
            (["patches/kakaotalk/notification.patch"], False),
            ([".github/workflows/validate.yml"], False),
            ([".github/scripts/require-nix-validation"], False),
            (["scripts/validation/check.sh"], False),
            (["unknown-source"], False),
            ([], False),
        ]
        for paths, skills_only in cases:
            with self.subTest(paths=paths):
                self.check_paths(paths, skills_only)

    def test_deleted_skill_qualifies(self):
        self.check_paths(["skills/local/SKILL.md"], True, delete=True)

    def test_deleted_configuration_does_not_qualify(self):
        self.check_paths(["modules/hermes.nix"], False, delete=True)

    def test_configuration_moved_into_skills_does_not_qualify(self):
        self.check_paths(["modules/hermes.nix", "skills/local/SKILL.md"], False, rename=True)

    def check_paths(self, paths, skills_only, delete=False, rename=False):
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
            (root / "release-pins.json").write_text(json.dumps(pins))
            if delete or rename:
                path = root / paths[0]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Existing tracked content\n")
            git("init", "-q")
            git("add", ".")
            git("commit", "-qm", "Initial inputs")
            base = git("rev-parse", "HEAD")
            if delete:
                (root / paths[0]).unlink()
            elif rename:
                destination = root / paths[1]
                destination.parent.mkdir(parents=True, exist_ok=True)
                (root / paths[0]).rename(destination)
            else:
                for relative in paths:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if relative == "release-pins.json":
                        pins["apm"]["version"] = "0.0.0-ci-regression"
                        path.write_text(json.dumps(pins))
                    else:
                        path.write_text("Changed tracked content\n")
            git("add", "-A")
            git("commit", "--allow-empty", "-qm", "Change tested paths")
            head = git("rev-parse", "HEAD")
            subprocess.run(
                ["bash", str(DETECTOR), base, head], cwd=root, env=environment,
                check=True, capture_output=True, text=True,
            )
            outputs = dict(line.split("=", 1) for line in (root / "workflow-output").read_text().splitlines())
            self.assertEqual(outputs, {
                "skills_only": str(skills_only).lower(),
                "configuration_changed": str(not skills_only).lower(),
            })


class RequiredValidationGate(unittest.TestCase):
    def test_skills_only_requires_successful_apm(self):
        for result in ("success", "failure", "cancelled", "skipped"):
            with self.subTest(result=result):
                self.check_gate(result == "success", APM_RESULT=result)

    def test_full_validation_requires_both_jobs(self):
        for checks in ("success", "failure", "cancelled", "skipped"):
            for evaluate in ("success", "failure", "cancelled", "skipped"):
                with self.subTest(checks=checks, evaluate=evaluate):
                    self.check_gate(checks == evaluate == "success", SKILLS_ONLY="false",
                                    CONFIGURATION_CHANGED="true", CHECKS_RESULT=checks,
                                    EVALUATE_RESULT=evaluate)

    def test_failed_change_detection_cannot_pass(self):
        for result in ("failure", "cancelled", "skipped"):
            self.check_gate(False, CHANGES_RESULT=result)

    def test_inconsistent_or_missing_classification_cannot_pass(self):
        self.check_gate(False, CONFIGURATION_CHANGED="true")
        self.check_gate(False, SKILLS_ONLY="")
        self.check_gate(False, SKILLS_ONLY="unexpected")

    def check_gate(self, expected, **overrides):
        environment = dict(os.environ, CHANGES_RESULT="success", SKILLS_ONLY="true",
                           CONFIGURATION_CHANGED="false", APM_RESULT="success",
                           CHECKS_RESULT="skipped", EVALUATE_RESULT="skipped")
        environment.update(overrides)
        result = subprocess.run(["bash", str(GATE)], env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
