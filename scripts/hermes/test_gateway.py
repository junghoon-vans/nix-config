import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml


SPEC = importlib.util.spec_from_file_location("hermes_gateway", Path(__file__).with_name("gateway.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GatewayEnvironment(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home / ".env"
        self.config = {"home": str(self.home), "environment_file": str(self.path)}
        self.addCleanup(os.umask, os.umask(0o077))
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def settings(self, users="U123,U456", extra=""):
        self.path.write_text(f"SLACK_BOT_TOKEN=private-test-bot\nSLACK_APP_TOKEN=private-test-app\nSLACK_ALLOWED_USERS={users}\n{extra}")
        self.path.chmod(0o600)

    def test_actual_dotenv_wins_over_inherited_authorization(self):
        os.environ["SLACK_ALLOW_ALL_USERS"] = "false"
        self.settings(extra="SLACK_ALLOW_ALL_USERS=true\n")
        with self.assertRaisesRegex(RuntimeError, "not permitted"):
            MODULE.validate_environment(self.config)

    def test_whitespace_allowlist_does_not_pass_a_comma_only_consumer(self):
        self.settings(users="U123 U456")
        with self.assertRaisesRegex(RuntimeError, "comma-separated"):
            MODULE.validate_environment(self.config)


    def test_private_file_is_the_runtime_token_and_allowlist_source(self):
        os.environ["SLACK_BOT_TOKEN"] = "old-test-bot"
        os.environ["SLACK_ALLOWED_USERS"] = "U999"
        self.settings()
        MODULE.validate_environment(self.config)
        self.assertEqual(os.environ["SLACK_BOT_TOKEN"], "private-test-bot")
        self.assertEqual(os.environ["SLACK_ALLOWED_USERS"], "U123,U456")
        self.assertEqual(os.environ["HERMES_HOME"], str(self.home))


class GatewayRuntimeConfig(unittest.TestCase):
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
            "plugins": {"enabled": ["omp-worker"]},
        }
        self.defaults_path.write_text(yaml.safe_dump(self.defaults, sort_keys=False))
        self.managed_config = self.home / "config.nix.yaml"
        self.managed_config.symlink_to(self.defaults_path)
        self.plugin_source = self.root / "omp-worker"
        self.plugin_source.mkdir()
        plugin_link = self.home / "plugins" / "omp-worker"
        plugin_link.parent.mkdir()
        plugin_link.symlink_to(self.plugin_source, target_is_directory=True)
        self.runtime = self.home / "config.yaml"
        self.config = {
            "home": str(self.home),
            "environment_file": str(self.home / ".env"),
            "config_defaults": str(self.defaults_path),
            "plugin_source": str(self.plugin_source),
        }

    def native_modules(self):
        return {
            "acp.client": SimpleNamespace(ClientSideConnection=object),
            "slack_bolt.async_app": SimpleNamespace(AsyncApp=object),
            "slack_bolt.adapter.socket_mode.async_handler": SimpleNamespace(AsyncSocketModeHandler=object),
            "slack_sdk.web.async_client": SimpleNamespace(AsyncWebClient=object),
        }

    def check(self, modules=None):
        with patch.dict(sys.modules, self.native_modules() if modules is None else modules):
            with patch.object(MODULE, "validate_environment"), patch.object(
                MODULE, "check_runtime", side_effect=lambda _: MODULE.validate_runtime()
            ):
                MODULE.check(self.config)

    def test_missing_slack_sdk_prevents_config_materialization(self):
        modules = self.native_modules()
        modules["slack_bolt.async_app"] = None
        with self.assertRaisesRegex(RuntimeError, "Slack runtime dependencies"):
            self.check(modules)
        self.assertFalse(self.runtime.exists())


    def write_defaults(self, path, values):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(values, sort_keys=False))

    def test_check_converts_private_config_and_preserves_only_native_allowlist(self):
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
            "plugins": {"enabled": ["omp-worker"]},
        }
        self.write_defaults(next_defaults_path, next_defaults)
        self.managed_config.unlink()
        self.managed_config.symlink_to(next_defaults_path)
        self.config["config_defaults"] = str(next_defaults_path)
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

    def test_plugin_must_resolve_to_declared_source(self):
        other_plugin = self.root / "other-plugin"
        other_plugin.mkdir()
        self.config["plugin_source"] = str(other_plugin)

        with self.assertRaisesRegex(
            RuntimeError, "plugins/omp-worker is not the declared Nix resource"
        ):
            self.check()

        self.assertFalse(self.runtime.exists())


class RuntimeDependencyIsolation(unittest.TestCase):
    def test_native_preflight_does_not_require_support_python_packages(self):
        runner = """
import importlib, importlib.util, runpy, sys
from types import SimpleNamespace
assert importlib.util.find_spec("yaml") is None
assert importlib.util.find_spec("dotenv") is None
modules = {
    "acp.client": SimpleNamespace(ClientSideConnection=object),
    "slack_bolt.async_app": SimpleNamespace(AsyncApp=object),
    "slack_bolt.adapter.socket_mode.async_handler": SimpleNamespace(AsyncSocketModeHandler=object),
    "slack_sdk.web.async_client": SimpleNamespace(AsyncWebClient=object),
}
original_import = importlib.import_module
importlib.import_module = lambda name: modules[name] if name in modules else original_import(name)
sys.argv = [sys.argv[1], "--runtime-check"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
        result = subprocess.run(
            [sys.executable, "-S", "-c", runner, str(Path(__file__).with_name("gateway.py"))],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
