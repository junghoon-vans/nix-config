import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class HomebrewWorkflow(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        scripts = self.root / "scripts/homebrew"
        scripts.mkdir(parents=True)
        shutil.copy2(ROOT / "Makefile", self.root / "Makefile")
        shutil.copy2(ROOT / "scripts/homebrew/update.sh", scripts / "update.sh")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.environment = {**os.environ, "PATH": f"{self.bin}:{os.defpath}", "STATE": str(self.root)}
        self.command("nix", 'touch "$STATE/lock-updated"\nexit "${FAIL_NIX:-0}"')
        self.command("sudo", 'test "${FAIL_ACTIVATION:-0}" = 0 || exit 9\ntouch "$STATE/activated"')
        self.command("brew", '''test "$HOMEBREW_NO_AUTO_UPDATE" = 1 || exit 8
case "$1" in
  outdated) touch "$STATE/previewed" ;;
  upgrade) touch "$STATE/upgraded" ;;
  *) exit 7 ;;
esac''')

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)

    def run_make(self, *args, **environment):
        return subprocess.run(
            [shutil.which("make"), "--no-print-directory", *args],
            cwd=self.root, env={**self.environment, **environment},
            capture_output=True, text=True, check=False,
        )

    def test_missing_or_unsupported_host_cannot_change_pins_or_activate(self):
        for host in (None, "unsupported-host"):
            with self.subTest(host=host):
                arguments = ["brew-update"] + ([f"HOST={host}"] if host else [])
                self.assertNotEqual(self.run_make(*arguments).returncode, 0)
                self.assertFalse((self.root / "lock-updated").exists())
                self.assertFalse((self.root / "activated").exists())
                self.assertFalse((self.root / "previewed").exists())

    def test_failed_pin_update_prevents_activation_and_homebrew(self):
        result = self.run_make("brew-update", "HOST=junghoonui-MacBookAir", FAIL_NIX="5")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "activated").exists())
        self.assertFalse((self.root / "previewed").exists())
        self.assertFalse((self.root / "upgraded").exists())

    def test_failed_activation_prevents_homebrew(self):
        result = self.run_make("brew-update", "HOST=junghoonui-MacBookPro", FAIL_ACTIVATION="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "lock-updated").exists())
        self.assertFalse((self.root / "previewed").exists())
        self.assertFalse((self.root / "upgraded").exists())

    def test_explicit_upgrade_does_not_change_pins_or_activate(self):
        result = self.run_make("brew-upgrade", FAIL_NIX="5", FAIL_ACTIVATION="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "upgraded").exists())
        self.assertFalse((self.root / "lock-updated").exists())
        self.assertFalse((self.root / "activated").exists())

    def test_package_flags_and_package_lists_are_rejected_before_upgrade(self):
        for package in ("--force", "hermes-agent neovim"):
            with self.subTest(package=package):
                self.assertNotEqual(self.run_make("brew-upgrade", f"PACKAGE={package}").returncode, 0)
                self.assertFalse((self.root / "upgraded").exists())


if __name__ == "__main__":
    unittest.main()
