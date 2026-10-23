import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import yaml


SPEC = importlib.util.spec_from_file_location("hermes_config", Path(__file__).with_name("prepare-config.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesRuntimeConfig(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / ".hermes"
        self.home.mkdir(mode=0o700)
        self.store = self.root / "nix-store"
        self.store.mkdir()
        self.defaults_path = self.store / "hermes-config.yaml"
        self.defaults = {
            "model": {"provider": "openai-codex", "default": "openai/gpt-6.1-sol"},
            "approvals": {"mode": "manual", "unattended_mode": "deny"},
            "plugins": {"enabled": ["omp-acp-delegator"]},
        }
        self.defaults_path.write_text(yaml.safe_dump(self.defaults, sort_keys=False))
        self.runtime = self.home / "config.yaml"

    def check(self):
        MODULE.prepare_runtime_config(self.home, self.defaults_path)

    def write_defaults(self, path, values):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(values, sort_keys=False))

    def test_preparation_converts_private_config_and_preserves_only_native_allowlist(self):
        source_content = self.defaults_path.read_bytes()
        self.runtime.write_text(
            "model:\n  provider: stale-provider\napi_key: private-old-secret\n"
            "command_allowlist:\n  - 'rm -rf *'\n  - 'git clean *'\n"
        )
        self.runtime.chmod(0o600)

        self.check()

        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o600)
        self.assertEqual(self.runtime.stat().st_uid, os.getuid())
        self.assertEqual(
            yaml.safe_load(self.runtime.read_text()),
            {
                **self.defaults,
                "command_allowlist": ["rm -rf *", "git clean *"],
            },
        )
        self.assertNotIn("api_key", yaml.safe_load(self.runtime.read_text()))
        self.assertEqual(self.defaults_path.read_bytes(), source_content)

    def test_allowlist_survives_repeated_checks_and_changed_defaults(self):
        self.runtime.write_text("command_allowlist:\n  - 'git status'\n")
        self.runtime.chmod(0o600)
        self.check()
        first = self.runtime.stat()

        self.check()

        repeated = self.runtime.stat()
        self.assertEqual(repeated.st_ino, first.st_ino)
        self.assertEqual(repeated.st_mtime_ns, first.st_mtime_ns)

        next_defaults_path = self.store / "next-generation" / "hermes-config.yaml"
        next_defaults = {
            "model": {"provider": "new-provider", "default": "new-model"},
            "approvals": {"mode": "manual", "unattended_mode": "deny"},
            "plugins": {"enabled": ["omp-acp-delegator"]},
        }
        self.write_defaults(next_defaults_path, next_defaults)
        self.defaults_path = next_defaults_path
        self.check()

        self.assertEqual(
            yaml.safe_load(self.runtime.read_text()),
            {**next_defaults, "command_allowlist": ["git status"]},
        )

    def test_legacy_nix_store_symlink_is_replaced_without_touching_target(self):
        legacy_path = self.store / "previous-config.yaml"
        legacy_content = b"model:\n  provider: old\ncommand_allowlist:\n  - old command\n"
        legacy_path.write_bytes(legacy_content)
        self.runtime.symlink_to(legacy_path)

        with patch.object(MODULE, "NIX_STORE_ROOT", self.store):
            self.check()

        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual(legacy_path.read_bytes(), legacy_content)
        self.assertEqual(yaml.safe_load(self.runtime.read_text()), self.defaults)

    def test_non_store_runtime_symlink_is_refused(self):
        external = self.root / "external.yaml"
        external.write_text("command_allowlist:\n  - 'allow everything'\n")
        self.runtime.symlink_to(external)

        with self.assertRaisesRegex(RuntimeError, "outside the Nix store"):
            self.check()

        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual(external.read_text(), "command_allowlist:\n  - 'allow everything'\n")

    def test_external_symlink_alias_to_store_is_still_refused(self):
        legacy = self.store / "legacy.yaml"
        legacy.write_text("command_allowlist: []\n")
        alias = self.root / "external-alias.yaml"
        alias.symlink_to(legacy)
        self.runtime.symlink_to(alias)

        with patch.object(MODULE, "NIX_STORE_ROOT", self.store):
            with self.assertRaisesRegex(RuntimeError, "outside the Nix store"):
                self.check()

        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual(legacy.read_text(), "command_allowlist: []\n")

    def test_malformed_native_allowlist_fails_closed(self):
        original = "command_allowlist:\n  - 'valid entry'\n  - {pattern: '*'}\n"
        self.runtime.write_text(original)
        self.runtime.chmod(0o600)

        with self.assertRaisesRegex(RuntimeError, "list of non-empty strings"):
            self.check()

        self.assertEqual(self.runtime.read_text(), original)

    def test_world_readable_runtime_config_is_refused(self):
        self.runtime.write_text("command_allowlist: []\n")
        self.runtime.chmod(0o644)

        with self.assertRaisesRegex(RuntimeError, "group or other users"):
            self.check()

    def test_missing_runtime_config_materializes_private_defaults(self):
        source_content = self.defaults_path.read_bytes()

        self.check()

        self.assertTrue(self.runtime.is_file())
        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o600)
        self.assertEqual(yaml.safe_load(self.runtime.read_text()), self.defaults)
        self.assertEqual(self.defaults_path.read_bytes(), source_content)


if __name__ == "__main__":
    unittest.main()
