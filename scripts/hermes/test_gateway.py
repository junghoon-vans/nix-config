import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("hermes_gateway", Path(__file__).with_name("gateway.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GatewayEnvironment(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home / ".env"
        self.config = {"home": str(self.home), "environment_file": str(self.path), "expected_version": "0.21.0"}
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
            MODULE.validate_environment(self.config, "0.21.0")

    def test_whitespace_allowlist_does_not_pass_a_comma_only_consumer(self):
        self.settings(users="U123 U456")
        with self.assertRaisesRegex(RuntimeError, "comma-separated"):
            MODULE.validate_environment(self.config, "0.21.0")

    def test_managed_worker_policy_cannot_be_overridden_by_private_env(self):
        os.environ["OMP_WORKER_CONFIG"] = "/nix/store/declared-worker.json"
        self.settings(extra="OMP_WORKER_CONFIG=/tmp/old-experiment.json\n")
        with self.assertRaisesRegex(RuntimeError, "Nix-owned OMP_WORKER_CONFIG"):
            MODULE.validate_environment(self.config, "0.21.0")

    def test_private_file_is_the_runtime_token_and_allowlist_source(self):
        os.environ["SLACK_BOT_TOKEN"] = "old-test-bot"
        os.environ["SLACK_ALLOWED_USERS"] = "U999"
        self.settings()
        MODULE.validate_environment(self.config, "0.21.0")
        self.assertEqual(os.environ["SLACK_BOT_TOKEN"], "private-test-bot")
        self.assertEqual(os.environ["SLACK_ALLOWED_USERS"], "U123,U456")
        self.assertEqual(os.environ["HERMES_HOME"], str(self.home))


if __name__ == "__main__":
    unittest.main()
