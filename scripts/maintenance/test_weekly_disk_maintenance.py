#!/usr/bin/env python3
"""Exercise weekly disk maintenance without invoking real cleanup tools."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "home/.local/bin/weekly-disk-maintenance"


class WeeklyDiskMaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.log_dir = self.root / "logs"
        self.calls = self.root / "cleanup-calls"

        self.write_stub(
            "df",
            "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n"
            "stub 100 90 10 90%% /\\n'\n",
        )
        self.write_stub("mole", 'printf "mole %s\\n" "$*" >>"$CALL_LOG"\n')
        self.write_stub("docker", 'printf "docker %s\\n" "$*" >>"$CALL_LOG"\n')

        self.env = dict(
            os.environ,
            HOME=str(self.home),
            PATH=f"{self.bin_dir}:/usr/bin:/bin",
            CALL_LOG=str(self.calls),
            WEEKLY_DISK_LOG_DIR=str(self.log_dir),
            WEEKLY_DISK_THRESHOLD_PERCENT="85",
        )
        self.env.pop("WEEKLY_DISK_DRY_RUN", None)

    def write_stub(self, name, body):
        path = self.bin_dir / name
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_maintenance(self, *args, **env):
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), *args],
            env=self.env | env,
            capture_output=True,
            text=True,
        )

    def test_invalid_values_fail_before_any_side_effects(self):
        for value in ("true", ""):
            with self.subTest(value=value):
                result = self.run_maintenance(
                    "--mole-clean", "--docker-prune", WEEKLY_DISK_DRY_RUN=value
                )

                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.log_dir.exists())
                self.assertFalse(self.calls.exists())

    def test_dry_run_never_executes_opted_in_cleanup(self):
        result = self.run_maintenance(
            "--mole-clean",
            "--docker-prune",
            WEEKLY_DISK_DRY_RUN="1",
        )

        self.assertEqual(result.returncode, 0)
        calls = self.calls.read_text() if self.calls.exists() else ""
        self.assertNotIn("mole clean", calls)
        for command in (
            "docker builder prune --force",
            "docker image prune --all --force",
            "docker container prune --force",
        ):
            self.assertNotIn(command, calls)

    def test_zero_runs_only_opted_in_cleanup_stub(self):
        result = self.run_maintenance("--mole-clean", WEEKLY_DISK_DRY_RUN="0")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls.read_text(), "mole clean\n")

    def test_unset_dry_run_defaults_to_zero(self):
        result = self.run_maintenance("--mole-clean")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls.read_text(), "mole clean\n")

    def test_without_opt_in_no_cleanup_runs(self):
        result = self.run_maintenance(WEEKLY_DISK_DRY_RUN="0")

        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
