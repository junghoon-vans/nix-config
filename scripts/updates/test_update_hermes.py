import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "update_hermes", Path(__file__).with_name("update-hermes.py")
)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class HermesUpdateTests(unittest.TestCase):
    def run_update(self, root, latest):
        fake_script = root / "scripts/updates/update-hermes.py"
        fake_script.parent.mkdir(parents=True, exist_ok=True)
        with patch.object(updater, "__file__", str(fake_script)), \
             patch.object(updater.fixed_release, "github_json", return_value={"tag_name": latest}), \
             patch.object(updater.subprocess, "run") as run, \
             patch.object(sys, "argv", [str(fake_script)]):
            updater.main()
        return run

    def test_same_release_does_not_rewrite_flake_or_update_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flake = root / "flake.nix"
            original = (
                'inputs = { hermes-agent.url = "github:NousResearch/hermes-agent/v1.2.3"; '
                'other.url = "github:fixture/other/v1"; };\n'
            )
            flake.write_text(original)

            run = self.run_update(root, "v1.2.3")

            self.assertEqual(flake.read_text(), original)
            run.assert_not_called()

    def test_newer_release_updates_declared_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flake = root / "flake.nix"
            flake.write_text('hermes-agent.url = "github:NousResearch/hermes-agent/v1.2.3";\n')

            with patch.object(updater, "__file__", str(root / "scripts/updates/update-hermes.py")), \
                 patch.object(updater.fixed_release, "github_json", return_value={"tag_name": "v1.3.0"}), \
                 patch.object(updater.subprocess, "run"), \
                 patch.object(sys, "argv", ["update-hermes.py"]):
                updater.main()

            self.assertIn("hermes-agent/v1.3.0", flake.read_text())


if __name__ == "__main__":
    unittest.main()
