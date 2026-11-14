import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/ego/ego-browser.sh"
HELPER = "Contents/Frameworks/ego Framework.framework/Versions/Current/Helpers/ego-browser"


class EgoBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.env = dict(os.environ, HOME=str(self.home))
        self.env.pop("EGO_LITE_APP", None)

    def app(self, path, status=0):
        helper = path / HELPER
        helper.parent.mkdir(parents=True)
        helper.write_text('#!/bin/bash\nprintf "<%s>\\n" "$@"\nexit ' + str(status) + '\n')
        helper.chmod(0o755)
        return path

    def run_cli(self, *args):
        return subprocess.run(["bash", str(WRAPPER), *args], env=self.env,
                              capture_output=True, text=True)

    def test_explicit_versionless_app_forwards_arguments_and_exit_status(self):
        app = self.app(self.home / "custom app.app", status=23)
        self.env["EGO_LITE_APP"] = str(app)
        result = self.run_cli("--help", "two words", "", "*")
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(result.stdout, "<--help>\n<two words>\n<>\n<*>\n")

    def test_user_app_is_available_without_system_installation(self):
        self.app(self.home / "Applications/ego lite.app")
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "<--help>\n")

    def test_invalid_explicit_app_fails_without_fallback_or_install(self):
        self.app(self.home / "Applications/ego lite.app")
        self.env["EGO_LITE_APP"] = str(self.home / "missing.app")
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 127)
        self.assertIn("EGO_LITE_APP", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(Path(self.env["EGO_LITE_APP"]).exists())


if __name__ == "__main__":
    unittest.main()
