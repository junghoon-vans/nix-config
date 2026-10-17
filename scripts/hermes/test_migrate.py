import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml


SPEC = importlib.util.spec_from_file_location("hermes_migrate", Path(__file__).with_name("migrate.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MigrationBehavior(unittest.TestCase):
    def test_cleanup_removes_hook_but_preserves_credentials_and_other_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            hermes = home / ".hermes"
            plugin = hermes / "plugins/orca-status"
            plugin.mkdir(parents=True)
            (plugin / "plugin.yaml").write_text("name: orca-status\n")
            config = hermes / "config.yaml"
            config.write_text("plugins:\n  enabled: [orca-status, platforms/slack]\nmodel:\n  provider: retained\n")
            auth = hermes / ".env"
            auth.write_text("PRIVATE_TEST_VALUE=retain\n")
            session = hermes / "state.db"
            session.write_bytes(b"runtime-state-sentinel")
            (home / "orca/workspaces").mkdir(parents=True)
            migration = MODULE.Migration(home)
            migration.clean(cleanup_only=True)
            current = yaml.safe_load(config.read_text())
            self.assertEqual(current["plugins"]["enabled"], ["platforms/slack"])
            self.assertEqual(current["model"]["provider"], "retained")
            self.assertEqual(auth.read_text(), "PRIVATE_TEST_VALUE=retain\n")
            self.assertEqual(session.read_bytes(), b"runtime-state-sentinel")
            self.assertFalse(plugin.exists())
            self.assertFalse((home / "orca").exists())
            self.assertEqual((migration.backup / ".hermes/plugins/orca-status/plugin.yaml").read_text(), "name: orca-status\n")
            self.assertEqual(migration.backup.stat().st_mode & 0o777, 0o700)
            second = MODULE.Migration(home)
            second.clean(cleanup_only=True)
            self.assertFalse(second.backup.exists())

    def test_nonempty_orca_workspace_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            workspace = home / "orca/workspaces/project"
            workspace.mkdir(parents=True)
            (workspace / "source.py").write_text("user source\n")
            MODULE.Migration(home).clean(cleanup_only=True)
            self.assertEqual((workspace / "source.py").read_text(), "user source\n")

    def test_symlinked_orca_parent_never_changes_external_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            home.mkdir()
            external = root / "external"
            (external / "workspaces").mkdir(parents=True)
            (home / "orca").symlink_to(external, target_is_directory=True)
            MODULE.Migration(home).clean(cleanup_only=True)
            self.assertTrue((home / "orca").is_symlink())
            self.assertTrue((external / "workspaces").is_dir())


if __name__ == "__main__":
    unittest.main()
