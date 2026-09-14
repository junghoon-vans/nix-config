#!/usr/bin/env python3
"""Exercise the opt-in Home Manager backup cleanup command."""

import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


SCRIPT = Path(__file__).with_name("home-manager-backups-cleanup.sh")


class HomeManagerBackupsCleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.old_file = self.home / "config.json.pre-nix.20260801T000000.000000000Z"
        self.old_directory = self.home / ".omp.pre-nix.20260801T000000.000000000Z"
        self.old_nested_file = (
            self.home / ".config/nvim/init.lua.pre-nix.20260801T000000.000000000Z"
        )
        self.new_file = self.home / "config.json.pre-nix.20260914T000000.000000000Z"
        self.unmanaged_file = self.home / "notes.pre-nix.legacy"

        self.old_file.write_text("old backup")
        self.old_directory.mkdir()
        (self.old_directory / "contents").write_text("old directory backup")
        self.old_nested_file.parent.mkdir(parents=True)
        self.old_nested_file.write_text("old nested backup")
        self.new_file.write_text("new backup")
        self.unmanaged_file.write_text("unmanaged")

        old_timestamp = time.time() - 31 * 24 * 60 * 60
        os.utime(self.old_file, (old_timestamp, old_timestamp))
        os.utime(self.old_directory, (old_timestamp, old_timestamp))
        os.utime(self.unmanaged_file, (old_timestamp, old_timestamp))
        os.utime(self.old_nested_file, (old_timestamp, old_timestamp))

        self.env = dict(os.environ, HOME=str(self.home))

    def run_cleanup(self, **env):
        return subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=self.env | env,
            capture_output=True,
            text=True,
        )

    def test_dry_run_lists_only_expired_timestamped_backups(self):
        result = self.run_cleanup()

        self.assertEqual(result.returncode, 0)
        self.assertIn(str(self.old_file), result.stdout)
        self.assertIn(str(self.old_directory), result.stdout)
        self.assertIn(str(self.old_nested_file), result.stdout)
        self.assertNotIn(str(self.new_file), result.stdout)
        self.assertNotIn(str(self.unmanaged_file), result.stdout)
        self.assertTrue(self.old_file.exists())
        self.assertTrue(self.old_directory.exists())
        self.assertTrue(self.old_nested_file.exists())

    def test_confirmation_removes_only_expired_timestamped_backups(self):
        result = self.run_cleanup(CONFIRM="1")

        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.old_file.exists())
        self.assertFalse(self.old_directory.exists())
        self.assertFalse(self.old_nested_file.exists())
        self.assertTrue(self.new_file.exists())
        self.assertTrue(self.unmanaged_file.exists())

    def test_invalid_confirmation_never_removes_backups(self):
        result = self.run_cleanup(CONFIRM="yes")

        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.old_file.exists())
        self.assertTrue(self.old_directory.exists())


if __name__ == "__main__":
    unittest.main()
