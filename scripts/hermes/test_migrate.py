import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("hermes_migrate", Path(__file__).with_name("migrate.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MigrationBehavior(unittest.TestCase):
    def setUp(self):
        self.original_nix_store = MODULE.NIX_STORE

    def tearDown(self):
        MODULE.NIX_STORE = self.original_nix_store

    def test_normal_migration_archives_managed_plugin_link_and_preserves_user_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            home.mkdir()
            store = root / "nix/store"
            MODULE.NIX_STORE = store
            store_plugin = store / "abc123-omp-acp-old"
            store_plugin.mkdir(parents=True)
            (store_plugin / "plugin.yaml").write_text("name: omp-worker\n")

            hermes = home / ".hermes"
            plugin = hermes / "plugins/omp-worker"
            plugin.parent.mkdir(parents=True)
            plugin.symlink_to(store_plugin, target_is_directory=True)
            task = hermes / "omp-worker/tasks/task.json"
            task.parent.mkdir(parents=True)
            task.write_text('{"task":"keep"}\n')
            env = hermes / ".env"
            env.write_text("PRIVATE_TEST_VALUE=retain\n")
            auth = hermes / "auth.json"
            auth.write_text('{"token":"retain"}\n')
            session = hermes / "state.db"
            session.write_bytes(b"session-state-sentinel")

            migration = MODULE.Migration(home)
            migration.clean()

            archived_plugin = migration.backup / ".hermes/plugins/omp-worker"
            self.assertFalse(plugin.is_symlink())
            self.assertTrue(archived_plugin.is_symlink())
            self.assertEqual(archived_plugin.readlink(), store_plugin)
            self.assertEqual(task.read_text(), '{"task":"keep"}\n')
            self.assertEqual(env.read_text(), "PRIVATE_TEST_VALUE=retain\n")
            self.assertEqual(auth.read_text(), '{"token":"retain"}\n')
            self.assertEqual(session.read_bytes(), b"session-state-sentinel")
            self.assertEqual((store_plugin / "plugin.yaml").read_text(), "name: omp-worker\n")

            second = MODULE.Migration(home)
            second.clean()
            self.assertFalse(second.backup.exists())
            self.assertEqual(
                list((home / ".local/state/hermes-migration").iterdir()),
                [migration.backup],
            )

    def test_dangling_nix_store_plugin_link_is_archived_without_following_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            home.mkdir()
            MODULE.NIX_STORE = root / "nix/store"
            missing_store_path = MODULE.NIX_STORE / "missing-omp-acp"
            plugin = home / ".hermes/plugins/omp-worker"
            plugin.parent.mkdir(parents=True)
            plugin.symlink_to(missing_store_path, target_is_directory=True)

            migration = MODULE.Migration(home)
            migration.clean()

            archived_plugin = migration.backup / ".hermes/plugins/omp-worker"
            self.assertFalse(plugin.is_symlink())
            self.assertTrue(archived_plugin.is_symlink())
            self.assertFalse(archived_plugin.exists())
            self.assertEqual(archived_plugin.readlink(), missing_store_path)

    def test_cleanup_only_does_not_retire_managed_plugin_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            home.mkdir()
            MODULE.NIX_STORE = root / "nix/store"
            plugin = home / ".hermes/plugins/omp-worker"
            plugin.parent.mkdir(parents=True)
            plugin.symlink_to(MODULE.NIX_STORE / "old-plugin", target_is_directory=True)

            migration = MODULE.Migration(home)
            migration.clean(cleanup_only=True)

            self.assertTrue(plugin.is_symlink())
            self.assertFalse(migration.backup.exists())

    def test_non_managed_plugin_paths_are_not_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            MODULE.NIX_STORE = root / "nix/store"

            clone_home = root / "clone-home"
            clone = clone_home / ".hermes/plugins/omp-worker"
            clone.mkdir(parents=True)
            (clone / "plugin.yaml").write_text("name: user-clone\n")
            MODULE.Migration(clone_home).clean()
            self.assertEqual((clone / "plugin.yaml").read_text(), "name: user-clone\n")
            self.assertFalse((clone_home / ".local/state/hermes-migration").exists())

            external_home = root / "external-home"
            external = root / "user-plugin"
            external.mkdir()
            (external / "plugin.yaml").write_text("name: external\n")
            external_link = external_home / ".hermes/plugins/omp-worker"
            external_link.parent.mkdir(parents=True)
            external_link.symlink_to(external, target_is_directory=True)
            MODULE.Migration(external_home).clean()
            self.assertTrue(external_link.is_symlink())
            self.assertEqual(external_link.readlink(), external)
            self.assertEqual((external / "plugin.yaml").read_text(), "name: external\n")
            self.assertFalse((external_home / ".local/state/hermes-migration").exists())

    def test_symlinked_plugin_directory_does_not_retire_external_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            hermes = home / ".hermes"
            hermes.mkdir(parents=True)
            external = root / "shared-plugins"
            external.mkdir()
            (hermes / "plugins").symlink_to(external, target_is_directory=True)
            MODULE.NIX_STORE = root / "nix/store"
            plugin = external / "omp-worker"
            target = MODULE.NIX_STORE / "retained-plugin"
            plugin.symlink_to(target, target_is_directory=True)

            migration = MODULE.Migration(home)
            migration.clean()

            self.assertTrue(plugin.is_symlink())
            self.assertEqual(plugin.readlink(), target)
            self.assertTrue((hermes / "plugins").is_symlink())
            self.assertFalse(migration.backup.exists())


if __name__ == "__main__":
    unittest.main()
