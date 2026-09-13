#!/usr/bin/env python3
"""Exercise bootstrap with temporary files; never invoke real sudo or Nix."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


BOOTSTRAP = Path(__file__).with_name("bootstrap.sh")


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for name in ("flake.nix", "flake.lock"):
            (self.repo / name).touch()
        self.conf = self.root / "nix.conf"
        self.original = "experimental-features = ca-derivations # keep\nmax-jobs = 4\n"
        self.conf.write_text(self.original)
        self.conf.chmod(0o640)
        self.log = self.root / "calls"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        commands = {
            "nix": '#!/bin/bash\necho "nix $*" >> "$CALL_LOG"\ncase " $* " in *" eval "*) exit "${EVAL_STATUS:-0}";; esac\nexit "${RUN_STATUS:-0}"\n',
            "sudo": '#!/bin/bash\necho "sudo $*" >> "$CALL_LOG"\n[[ "$1" != -H ]] || shift\nif [[ "$1" == /bin/mv && "${FAIL_RENAME:-0}" == 1 ]]; then exit 1; fi\nexec "$@"\n',
        }
        for name, content in commands.items():
            path = bin_dir / name
            path.write_text(content)
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", NIX_CONF=str(self.conf), CALL_LOG=str(self.log))

    def run_bootstrap(self, host="junghoonui-MacBookAir", repo=None, **env):
        return subprocess.run(["/bin/bash", str(BOOTSTRAP), host, str(repo or self.repo)], env=self.env | env, capture_output=True, text=True)

    def test_preflight_failure_never_invokes_sudo_or_changes_config(self):
        for kwargs in ({"host": "unknown"}, {"repo": self.root / "missing"}, {"EVAL_STATUS": "1"}):
            with self.subTest(kwargs=kwargs):
                self.log.unlink(missing_ok=True)
                result = self.run_bootstrap(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.conf.read_text(), self.original)
                self.assertNotIn("sudo ", self.log.read_text() if self.log.exists() else "")
                self.assertEqual(list(self.root.glob("nix.conf.*")), [])

    def test_success_preserves_backup_metadata_and_is_idempotent(self):
        self.assertEqual(self.run_bootstrap().returncode, 0)
        self.assertEqual(self.conf.read_text(), "experimental-features = ca-derivations nix-command flakes # keep\nmax-jobs = 4\n")
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o640)
        backups = list(self.root.glob("nix.conf.backup.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.original)
        self.assertEqual(self.run_bootstrap(host="junghoonui-MacBookPro").returncode, 0)
        self.assertEqual(list(self.root.glob("nix.conf.backup.*")), backups)
        self.assertEqual(list(self.root.glob("nix.conf.tmp.*")), [])

    def test_failed_replace_preserves_original_and_does_not_activate(self):
        self.assertNotEqual(self.run_bootstrap(FAIL_RENAME="1").returncode, 0)
        self.assertEqual(self.conf.read_text(), self.original)
        self.assertNotIn(" run ", self.log.read_text())
        self.assertEqual(list(self.root.glob("nix.conf.tmp.*")), [])

    def test_missing_config_and_activation_failure(self):
        self.conf.unlink()
        self.assertEqual(self.run_bootstrap(RUN_STATUS="7").returncode, 7)
        self.assertEqual(self.conf.read_text(), "experimental-features = nix-command flakes\n")
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o644)

    def test_symlink_is_not_replaced(self):
        target = self.root / "managed.conf"
        self.conf.rename(target)
        self.conf.symlink_to(target)
        self.assertNotEqual(self.run_bootstrap().returncode, 0)
        self.assertTrue(self.conf.is_symlink())
        self.assertEqual(target.read_text(), self.original)
        self.assertNotIn("sudo ", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
