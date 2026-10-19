import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("hermes_omp_worker", ROOT / "omp-worker/__init__.py")
PLUGIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PLUGIN
SPEC.loader.exec_module(PLUGIN)
Worker = sys.modules["hermes_omp_worker.worker"].Worker


class WorkerBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Worker test")
        self.git("config", "user.email", "worker@example.invalid")
        (self.repository / "original.txt").write_text("preserve\n")
        self.git("add", "original.txt")
        self.git("commit", "-qm", "initial")
        self.original_branch = self.git("branch", "--show-current")
        self.config = {
            "command": str(ROOT / "fixtures/acp_peer.py"), "git": shutil.which("git"),
            "state_dir": str(self.root / "state"), "allowed_roots": [str(self.repository)],
            "approval_config": str(self.root / "policy.yaml"), "timeout": 10,
        }
        Path(self.config["approval_config"]).write_text("tools:\n  approvalMode: always-ask\n")
        self.worker = Worker(self.config)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repository), *args], text=True).strip()

    def run_task(self, prompt, **kwargs):
        return self.worker.run("slack-conversation", str(self.repository), prompt, approve=lambda _: True, cancelled=lambda: False, **kwargs)

    def test_follow_up_reloads_session_and_preserves_original_checkout(self):
        (self.repository / "original.txt").write_text("user's uncommitted work\n")
        first = self.run_task("first change")
        second = self.run_task("follow-up change")
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["session_id"], first["session_id"])
        self.assertEqual(second["worktree"], first["worktree"])
        self.assertEqual((Path(second["worktree"]) / "result.txt").read_text(), "1:first change\n2:follow-up change\n")
        self.assertEqual((self.repository / "original.txt").read_text(), "user's uncommitted work\n")
        self.assertFalse((self.repository / "result.txt").exists())
        self.assertEqual(second["tool_calls"][0]["rawOutput"]["exit_code"], 0)
        self.assertEqual(self.git("branch", "--show-current"), self.original_branch)

    def test_completed_history_limit_does_not_block_new_action_approval(self):
        result = self.run_task("history-limit")
        self.assertEqual((Path(result["worktree"]) / "result.txt").read_text(), "1:history-limit\n")
        self.assertEqual(result["tool_calls"][-1]["rawOutput"]["exit_code"], 0)

    def test_ambiguous_form_cannot_authorize_either_live_operation(self):
        result = self.run_task("ambiguous")
        self.assertFalse((Path(result["worktree"]) / "result.txt").exists())
        self.assertIn("Permission denied", result["response"])

    def test_unrecognized_form_is_not_silently_approved(self):
        result = self.run_task("unknown-form")
        self.assertFalse((Path(result["worktree"]) / "result.txt").exists())
        self.assertEqual(result["changes"], "")
        self.assertIn("Permission denied", result["response"])

    def test_denied_action_does_not_mutate_worktree(self):
        result = self.worker.run("denied", str(self.repository), "write", approve=lambda _: False, cancelled=lambda: False)
        self.assertFalse((Path(result["worktree"]) / "result.txt").exists())
        self.assertEqual(result["changes"], "")
        self.assertIn("Permission denied", result["response"])

    def test_symlink_escape_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.repository / "escape"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.worker.status("owner", str(link))
        self.assertEqual(list((self.root / "state").glob("*.json")), [])

    def test_crash_is_retained_and_not_blindly_retried(self):
        result = self.run_task("crash")
        self.assertEqual(result["status"], "failed")
        self.assertIn("exited", result["error"])
        with self.assertRaisesRegex(RuntimeError, "explicit user continuation"):
            self.run_task("write")
        continued = self.run_task("recover", resume_interrupted=True)
        self.assertEqual(continued["session_id"], result["session_id"])
        self.assertEqual((Path(continued["worktree"]) / "result.txt").read_text(), "1:recover\n")

    def test_nonterminal_stop_reason_is_not_success(self):
        result = self.run_task("bad-stop")
        self.assertEqual(result["status"], "failed")
        self.assertIn("max_tokens", result["error"])

    def test_cancellation_kills_shell_child_and_retains_state(self):
        def cancelled():
            return any((self.root / "state/worktrees").glob("*/child.pid"))

        result = self.worker.run("cancel", str(self.repository), "sleep", approve=lambda _: True, cancelled=cancelled)
        self.assertEqual(result["status"], "cancelled")
        worktree = Path(result["worktree"])
        pid = int((worktree / "child.pid").read_text())
        state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], text=True, capture_output=True)
        self.assertTrue(state.returncode != 0 or state.stdout.strip().startswith("Z"), state.stdout)
        self.assertFalse((worktree / "escaped").exists())
        retained = self.worker.status("cancel", str(self.repository))
        self.assertEqual(retained["status"], "cancelled")
        self.assertEqual(retained["session_id"], result["session_id"])

    def test_conversations_do_not_share_worktree_or_session(self):
        first = self.run_task("first")
        second = self.worker.run("another-thread", str(self.repository), "second", approve=lambda _: True, cancelled=lambda: False)
        self.assertNotEqual(first["worktree"], second["worktree"])
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual((Path(first["worktree"]) / "result.txt").read_text(), "1:first\n")


if __name__ == "__main__":
    unittest.main()
