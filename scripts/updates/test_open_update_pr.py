import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_enable_update_automerge import MOCK_GH as AUTOMERGE_GH, PR
import copy
import json


HELPER = Path(__file__).resolve().with_name("open-update-pr.sh")
BRANCH = "automation/update-paseo-plugins"
TARGET = "modules/paseo-plugins.json"


def plugin_source(revision):
    return json.dumps({"example": {"repository": "owner/plugin", "revision": revision, "hash": "sha256-test"}})

MOCK_GH = """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$GH_TEST_LOG"
case "$1" in
  api)
    case "$2" in
      users/*) ;;
      *) exec "$GH_AUTOMERGE_MOCK" "$@" ;;
    esac
    if [ "${GH_FAIL_API:-0}" = 1 ]; then
      printf '%s\\n' 'simulated GitHub API failure' >&2
      exit 42
    fi
    printf '%s\\n' '12345'
    ;;
  pr)
    case "$2" in
      list) printf '%s\\n' "${GH_PR_COUNT:-0}" ;;
      view) printf '%s\\n' '7' ;;
      edit|create) ;;
      *) exit 91 ;;
    esac
    ;;
  *) exit 90 ;;
esac
"""


class OpenUpdatePRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
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
        self.automerge_gh = self.gh_bin / "automerge-gh"
        self.automerge_gh.write_text(AUTOMERGE_GH)
        self.automerge_gh.chmod(0o755)
        self.automerge_fixture = self.root / "automerge.json"
        pr = copy.deepcopy(PR)
        pr["head"]["ref"] = BRANCH
        self.automerge_fixture.write_text(json.dumps({
            "pr": pr, "local_head": True,
            "pages": [[{"filename": TARGET, "status": "modified"}]],
        }))

        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.origin))
        self.git(self.root, "init", "--initial-branch=main", str(self.repo))
        self.git(self.repo, "config", "user.name", "Test User")
        self.git(self.repo, "config", "user.email", "test@example.invalid")
        target = self.repo / TARGET
        target.parent.mkdir(parents=True)
        target.write_text(plugin_source("old"))
        self.git(self.repo, "add", TARGET)
        self.git(self.repo, "commit", "-m", "initial")
        self.git(self.repo, "remote", "add", "origin", str(self.origin))
        self.git(self.repo, "push", "--set-upstream", "origin", "main")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, cwd, *args):
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=self.git_env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def helper_env(self, **overrides):
        env = self.git_env.copy()
        env["PATH"] = str(self.gh_bin) + os.pathsep + env["PATH"]
        env["GH_TEST_LOG"] = str(self.gh_log)
        env["GH_AUTOMERGE_MOCK"] = str(self.automerge_gh)
        env["GH_AUTOMERGE_FIXTURE"] = str(self.automerge_fixture)
        env["GH_MUTATION_LOG"] = str(self.root / "mutations.jsonl")
        env.update(overrides)
        return env

    def run_helper(self, env):
        return subprocess.run(
            ["bash", str(HELPER), BRANCH, "chore(deps): update plugins", "automated update", TARGET],
            cwd=self.repo, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def test_no_change_exits_without_calling_github(self):
        result = self.run_helper(self.helper_env())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.gh_log.exists())
        self.assertEqual(self.git(self.repo, "branch", "--list", BRANCH), "")

    def test_new_pr_body_preserves_context_and_contains_before_after_pins(self):
        (self.repo / TARGET).write_text(plugin_source("new"))
        result = self.run_helper(self.helper_env(GH_APP_SLUG="dependency-updates"))
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_log.read_text()
        self.assertIn("pr create --base main", calls)
        self.assertIn("automated update", calls)
        self.assertIn("revision: old", calls)
        self.assertIn("revision: new", calls)
        self.assertIn("https://github.com/owner/plugin/compare/old...new", calls)

    def test_invalid_metadata_stops_before_github_branch_or_push(self):
        (self.repo / TARGET).write_text("not json")
        result = self.run_helper(self.helper_env(GH_APP_SLUG="dependency-updates"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.gh_log.exists())
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.repo, "branch", "--list", BRANCH), "")

    def test_existing_remote_branch_updates_open_pr_without_creating_another(self):
        target = self.repo / TARGET
        self.git(self.repo, "switch", "-c", BRANCH)
        target.write_text(plugin_source("previous-update"))
        self.git(self.repo, "add", TARGET)
        self.git(self.repo, "commit", "-m", "previous update")
        self.git(self.repo, "push", "--set-upstream", "origin", BRANCH)
        self.git(self.repo, "switch", "main")
        self.git(
            self.repo, "fetch", "origin",
            f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}",
        )
        self.git(self.repo, "branch", "-D", BRANCH)
        previous_remote_commit = self.git(
            self.root, f"--git-dir={self.origin}", "rev-parse", f"refs/heads/{BRANCH}",
        )
        target.write_text(plugin_source("current-update"))

        result = self.run_helper(self.helper_env(GH_APP_SLUG="dependency-updates", GH_PR_COUNT="1"))

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.gh_log.read_text().splitlines()
        self.assertTrue(any(call.startswith("pr edit ") for call in calls), calls)
        self.assertFalse(any(call.startswith("pr create ") for call in calls), calls)
        updated_remote_commit = self.git(
            self.root, f"--git-dir={self.origin}", "rev-parse", f"refs/heads/{BRANCH}",
        )
        self.assertNotEqual(updated_remote_commit, previous_remote_commit)
        updated_source = self.git(
            self.root, f"--git-dir={self.origin}", "show", f"refs/heads/{BRANCH}:{TARGET}",
        )
        self.assertEqual(json.loads(updated_source)["example"]["revision"], "current-update")
        creation = self.gh_log.read_text()
        self.assertIn("| example |", creation)
        self.assertIn("revision: old", creation)
        self.assertIn("revision: current-update", creation)

    def test_github_api_failure_stops_before_branch_or_push(self):
        (self.repo / TARGET).write_text(plugin_source("changed"))

        result = self.run_helper(
            self.helper_env(GH_APP_SLUG="dependency-updates", GH_FAIL_API="1"),
        )

        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.repo, "branch", "--list", BRANCH), "")
        self.assertEqual(self.git(self.root, f"--git-dir={self.origin}", "branch", "--list", BRANCH), "")


if __name__ == "__main__":
    unittest.main()
