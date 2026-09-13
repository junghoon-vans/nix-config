import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("apply_settings", Path(__file__).with_name("apply-settings.py"))
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class ApplySettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.profile = self.home / ".aside/u/7"
        self.profile.mkdir(parents=True)
        self.path = self.profile / "settings.json"
        self.original = {
            "permission": {"rules": {"default": "allow", "deny": ["private-tool"]}},
            "memory": {"enabled": True, "dreamingMinSessions": 5},
            "unknown": {"preserve": [1, 2]},
        }
        self.path.write_text(json.dumps(self.original))
        self.original_bytes = self.path.read_bytes()
        self.models = self.profile / "models.json"
        self.models.write_text('{"accountCatalog": "local-only"}')
        self.models.chmod(0o644)
        self.credentials = self.profile / "credentials.json"
        self.credentials.write_text("synthetic-auth-state")
        self.credentials.chmod(0o600)
        self.policy = {"permission": {"rules": {"default": "ask"}}, "memory": {"episodicRetentionDays": 30}}
        self.enterContext(patch.dict(os.environ, {"HOME": str(self.home)}))
        self.running = self.enterContext(patch.object(settings, "aside_is_running", return_value=False))

    def apply(self, **kwargs):
        settings.apply_settings(self.policy, kwargs.get("account"), kwargs.get("dry_run", False))

    def test_merge_preserves_unmanaged_state_and_first_backup_across_reapplication(self):
        self.apply()
        expected = self.original | {"memory": {"enabled": True, "dreamingMinSessions": 5, "episodicRetentionDays": 30}}
        expected["permission"] = {"rules": {"default": "ask", "deny": ["private-tool"]}}
        self.assertEqual(json.loads(self.path.read_text()), expected)
        self.assertEqual(self.models.read_text(), '{"accountCatalog": "local-only"}')
        self.assertEqual(self.credentials.read_text(), "synthetic-auth-state")
        backup = self.profile / "settings.json.pre-nix"
        self.assertEqual(backup.read_bytes(), self.original_bytes)
        for path in (self.path, self.models, backup):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        timestamp = self.path.stat().st_mtime_ns
        self.apply()
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)
        self.policy["memory"]["episodicRetentionDays"] = 90
        self.apply()
        self.assertEqual(backup.read_bytes(), self.original_bytes)
        self.assertEqual(json.loads(self.path.read_text())["memory"]["episodicRetentionDays"], 90)

    def test_dry_run_does_not_write_or_harden_files(self):
        self.apply(dry_run=True)
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(self.models.stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.profile / "settings.json.pre-nix").exists())

    def test_running_aside_defers_without_touching_profile(self):
        self.running.return_value = True
        with self.assertRaises(settings.Deferred):
            self.apply()
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(self.models.stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.profile / "settings.json.pre-nix").exists())

    def test_concurrent_settings_change_is_not_overwritten(self):
        def start_edit():
            self.path.write_text('{"concurrent": true}')
            return False

        self.running.side_effect = lambda: start_edit() if self.running.call_count == 2 else False
        with self.assertRaises(settings.Deferred):
            self.apply()
        self.assertEqual(json.loads(self.path.read_text()), {"concurrent": True})
        self.assertEqual(list(self.profile.glob(".settings-nix-*")), [])

    def test_invalid_json_or_managed_subtree_leaves_original_untouched(self):
        for raw in (b"{invalid", b'{"permission": null}'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertEqual(self.path.read_bytes(), raw)
                self.assertFalse((self.profile / "settings.json.pre-nix").exists())

    def test_multiple_profiles_require_explicit_selection(self):
        second = self.profile.parent / "11"
        second.mkdir()
        other = second / "settings.json"
        other.write_text("{}")
        with self.assertRaises(settings.Deferred):
            self.apply()
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.apply(account="7")
        self.assertEqual(other.read_text(), "{}")
        self.assertEqual(json.loads(self.path.read_text())["permission"]["rules"]["default"], "ask")

    def test_symlinked_models_cannot_change_an_unrelated_file(self):
        target = self.home / "unrelated"
        target.write_text("untouched")
        target.chmod(0o644)
        self.models.unlink()
        self.models.symlink_to(target)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(target.read_text(), "untouched")
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.path.read_bytes(), self.original_bytes)


if __name__ == "__main__":
    unittest.main()
