import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).resolve().with_name("publish-model-update.sh")
BRANCH = "automation/update-openai-models"
MODEL_PATHS = (
    "home/.omp/agent/config.yml",
    "home/.paseo/config.json",
    "modules/aside.nix",
    "modules/hermes.nix",
)

MOCK_GH = """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$GH_TEST_LOG"
case "$1" in
  api)
    case "$2" in
      users/*)
        if [ "${GH_FAIL_API:-0}" = 1 ]; then
          printf '%s\\n' 'simulated GitHub API failure' >&2
          exit 42
        fi
        printf '%s\\n' '12345'
        ;;
      *) exit 91 ;;
    esac
    ;;
  pr)
    case "$2" in
      list) printf '%s\\n' "${GH_OPEN_PR:-}" ;;
      edit|create) ;;
      *) exit 92 ;;
    esac
    ;;
  *) exit 90 ;;
esac
"""


class ModelUpdateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        home = self.root / "home"
        home.mkdir()
        self.git_env = os.environ.copy()
        self.git_env.update({
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
        })
        self.repo = self.root / "repo"
        self.origin = self.root / "origin.git"
        self.gh_bin = self.root / "bin"
        self.gh_bin.mkdir()
        gh = self.gh_bin / "gh"
        gh.write_text(MOCK_GH)
        gh.chmod(0o755)
        self.gh_log = self.root / "gh.log"
        self.body_file = self.root / "model-update.md"
        self.body_file.write_text("Static client evidence; manual merge required.\n")

        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.origin))
        self.git(self.root, "init", "--initial-branch=main", str(self.repo))
        self.git(self.repo, "config", "user.name", "Test User")
        self.git(self.repo, "config", "user.email", "test@example.invalid")
        for path in MODEL_PATHS:
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"model pin: original for {path}\n")
        (self.repo / "release-pins.json").write_text('{"package":"old"}\n')
        self.git(self.repo, "add", "--all")
        self.git(self.repo, "commit", "-m", "initial")
        self.git(self.repo, "remote", "add", "origin", str(self.origin))
        self.git(self.repo, "push", "--set-upstream", "origin", "main")

    def git(self, cwd, *args):
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=self.git_env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def helper_env(self, **overrides):
        env = self.git_env.copy()
        env.update({
            "PATH": str(self.gh_bin) + os.pathsep + env["PATH"],
            "GH_APP_SLUG": "dependency-updates",
            "GH_TEST_LOG": str(self.gh_log),
        })
        env.update(overrides)
        return env

    def run_helper(self, env):
        return subprocess.run(
            ["bash", str(HELPER), BRANCH, str(self.body_file)],
            cwd=self.repo, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def test_no_model_changes_leave_branch_and_github_untouched(self):
        result = self.run_helper(self.helper_env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No supported OpenAI model pin changes", result.stdout)
        self.assertFalse(self.gh_log.exists())
        self.assertEqual(self.git(self.repo, "branch", "--list", BRANCH), "")

    def test_model_change_opens_manual_pr_without_staging_package_pins(self):
        (self.repo / MODEL_PATHS[0]).write_text("model pin: updated\n")
        (self.repo / "release-pins.json").write_text('{"package":"new"}\n')

        result = self.run_helper(self.helper_env())

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_log.read_text()
        self.assertIn("pr create --base main --head " + BRANCH, calls)
        self.assertIn("Static client evidence; manual merge required.", calls)
        self.assertNotIn("auto-merge", calls.lower())
        self.assertNotIn("enable-update-automerge.py", calls)
        self.assertEqual(
            self.git(self.root, f"--git-dir={self.origin}", "show", f"{BRANCH}:release-pins.json"),
            '{"package":"old"}',
        )
        self.assertEqual(
            self.git(self.root, f"--git-dir={self.origin}", "show", f"{BRANCH}:{MODEL_PATHS[0]}"),
            "model pin: updated",
        )

    def test_existing_open_pr_is_updated_instead_of_duplicated(self):
        target = self.repo / MODEL_PATHS[0]
        self.git(self.repo, "switch", "-c", BRANCH)
        target.write_text("model pin: previous\n")
        self.git(self.repo, "add", MODEL_PATHS[0])
        self.git(self.repo, "commit", "-m", "previous model update")
        self.git(self.repo, "push", "--set-upstream", "origin", BRANCH)
        self.git(self.repo, "switch", "main")
        self.git(
            self.repo, "fetch", "origin",
            f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}",
        )
        self.git(self.repo, "branch", "-D", BRANCH)
        target.write_text("model pin: current\n")

        result = self.run_helper(self.helper_env(GH_OPEN_PR="42"))

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_log.read_text()
        self.assertIn("pr edit 42", calls)
        self.assertNotIn("pr create", calls)
        self.assertEqual(
            self.git(self.root, f"--git-dir={self.origin}", "show", f"{BRANCH}:{MODEL_PATHS[0]}"),
            "model pin: current",
        )

    def test_deleted_remote_branch_does_not_block_model_publication(self):
        self.git(self.repo, "push", "origin", f"HEAD:refs/heads/{BRANCH}")
        self.git(self.repo, "fetch", "origin")
        self.git(self.root, f"--git-dir={self.origin}", "update-ref", "-d", f"refs/heads/{BRANCH}")
        (self.repo / MODEL_PATHS[0]).write_text("model pin: current\n")

        result = self.run_helper(self.helper_env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.git(self.root, f"--git-dir={self.origin}", "show", f"{BRANCH}:{MODEL_PATHS[0]}"),
            "model pin: current",
        )

    def test_github_identity_failure_does_not_switch_or_push_branch(self):
        (self.repo / MODEL_PATHS[0]).write_text("model pin: updated\n")

        result = self.run_helper(self.helper_env(GH_FAIL_API="1"))

        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.repo, "branch", "--list", BRANCH), "")
        self.assertEqual(self.git(self.root, f"--git-dir={self.origin}", "branch", "--list", BRANCH), "")


if __name__ == "__main__":
    unittest.main()
