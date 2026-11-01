import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("kakaotalk_update", Path(__file__).with_name("update-kakaotalk-patcher.py"))
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / updater.PACKAGE
        self.path.parent.mkdir()
        self.original = (updater.ROOT / updater.PACKAGE).read_text()
        self.path.write_text(self.original)
        self.old = updater.pin(self.original, "rev")
        self.new = "a" * 40
        self.sources = []
        for name in ("old", "new"):
            source = self.root / name
            source.mkdir()
            (source / "patch_kakaotalk.py").write_text("TARGET = TargetSpec(version='26.9.0', build='2006', original_sha256='reviewed')\n")
            self.sources.append(source)
        self.root_patch = patch.object(updater, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def run_update(self, *, revision=None, status="ahead", failure=None, old_hash=None):
        responses = [{"default_branch": "main"}, {"sha": revision or self.new}, {"status": status}]
        with patch.object(updater.fixed_release, "github_json", side_effect=responses), patch.object(
            updater, "prefetch", side_effect=[(old_hash or updater.pin(self.original, "hash"), self.sources[0]), ("sha256-" + "B" * 43 + "=", self.sources[1])]
        ), patch.object(updater, "check_candidate", side_effect=failure) as check:
            updater.update()
            return check

    def test_publishes_exact_revision_hash_only_after_success(self):
        def build_staged_candidate(content):
            self.assertEqual(self.path.read_text(), self.original)

        self.run_update(failure=build_staged_candidate)
        content = self.path.read_text()
        self.assertEqual(updater.pin(content, "rev"), self.new)
        self.assertEqual(updater.pin(content, "hash"), "sha256-" + "B" * 43 + "=")
        self.assertEqual(updater.pin(content, "version"), "26.9.0-2006-aaaaaaa")

    def test_build_failure_leaves_reviewed_pins_unchanged(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_update(failure=subprocess.CalledProcessError(1, "nix build"))
        self.assertEqual(self.path.read_text(), self.original)

    def test_reviewed_hash_mismatch_leaves_pins_unchanged(self):
        with self.assertRaisesRegex(ValueError, "Reviewed source hash"):
            self.run_update(old_hash="sha256-" + "C" * 43 + "=")
        self.assertEqual(self.path.read_text(), self.original)

    def test_changed_binary_contract_requires_manual_integration(self):
        for field in ("version", "build", "original_sha256"):
            with self.subTest(field=field):
                text = (self.sources[0] / "patch_kakaotalk.py").read_text()
                (self.sources[1] / "patch_kakaotalk.py").write_text(text.replace(field + "='", field + "='changed-"))
                with self.assertRaisesRegex(ValueError, "manual adapter integration"):
                    self.run_update()
                self.assertEqual(self.path.read_text(), self.original)

    def test_noop_does_not_build_or_rewrite(self):
        check = self.run_update(revision=self.old)
        check.assert_not_called()
        self.assertEqual(self.path.read_text(), self.original)

    def test_divergence_and_invalid_revisions_leave_pins_unchanged(self):
        for options in ({"status": "diverged"}, {"revision": "main"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_update(**options)
            self.assertEqual(self.path.read_text(), self.original)

    def test_missing_target_is_not_treated_as_compatible(self):
        (self.sources[1] / "patch_kakaotalk.py").write_text("OTHER = 1\n")
        with self.assertRaisesRegex(ValueError, "manual integration"):
            self.run_update()
        self.assertEqual(self.path.read_text(), self.original)


if __name__ == "__main__":
    unittest.main()
