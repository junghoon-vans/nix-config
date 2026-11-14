from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts/ego/check-migration.sh"
HELPER = "Contents/Frameworks/ego Framework.framework/Versions/Current/Helpers/ego-browser"


class EgoMigrationTests(unittest.TestCase):
    def test_managed_app_is_not_retired_until_an_external_app_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            applications = Path(directory) / "Applications"
            old = applications / "Nix Apps/ego lite.app"
            old.mkdir(parents=True)
            marker = old / "preserved"
            marker.write_text("existing app")
            command = ["bash", str(CHECK), str(home), str(applications)]
            blocked = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("before activating", blocked.stderr)
            self.assertEqual(marker.read_text(), "existing app")
            for app in [home / "Applications/ego lite.app", applications / "ego lite.app"]:
                helper = app / HELPER
                helper.parent.mkdir(parents=True)
                helper.touch(mode=0o755)
                allowed = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                helper.unlink()
            self.assertEqual(marker.read_text(), "existing app")

    def test_link_to_managed_app_is_not_an_independent_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            applications = Path(directory) / "Applications"
            old = applications / "Nix Apps/ego lite.app"
            helper = old / HELPER
            helper.parent.mkdir(parents=True)
            helper.touch(mode=0o755)
            external = home / "Applications/ego lite.app"
            external.parent.mkdir(parents=True)
            external.symlink_to(old, target_is_directory=True)
            result = subprocess.run(["bash", str(CHECK), str(home), str(applications)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(helper.exists())

    def test_fresh_machine_does_not_require_gui_for_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["bash", str(CHECK), directory, directory],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
