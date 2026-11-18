import json
import sys
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
      list)
        case "$*" in
          *"--json labels"*) printf '%s\\n' "${GH_PR_HELD:-false}" ;;
          *) printf '%s\\n' "${GH_OPEN_PR:-}" ;;
        esac
        ;;
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

    def test_collector_successor_validation_report_and_manual_publication_pipeline(self):
        scripts = HELPER.parent

        def write(relative, content):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

        write(MODEL_PATHS[0], "modelRoles:\n  default: openai-codex/gpt-6-sol:high\n")
        write(MODEL_PATHS[1], '{"daemon":{"agentProfiles":[{"id":"main","provider":"omp","model":"openai-codex/gpt-6-sol:low"}]}}')
        write(MODEL_PATHS[2], "")
        write(MODEL_PATHS[3], "")
        pins = '{"omp":{"version":"18.22.1","hash":"preserve"}}'
        write("release-pins.json", pins)
        write("flake.lock", json.dumps({"nodes": {"hermes-agent": {"locked": {
            "type": "github", "owner": "NousResearch", "repo": "hermes-agent", "rev": "a" * 40,
        }}}}))
        compact = {
            "version": 1, "keys": [], "booleanShapes": [[]],
            "nodes": [[0, [], 0, []]],
            "providers": [["openai-codex", [0], [["gpt-6-sol", [0]]]]],
        }
        write("fixtures/omp/packages/catalog/src/models.json", json.dumps(compact))
        write("fixtures/omp/packages/catalog/src/compat/rules/providers/openai-codex.kdl",
              'provider "openai-codex" { models "gpt-6.2-sol" {} }')
        write("fixtures/hermes/hermes_cli/codex_models.py",
              'DEFAULT_CODEX_MODELS = ["gpt-6-sol"]')
        self.git(self.repo, "add", "--all")
        self.git(self.repo, "commit", "-m", "structured model fixture")
        evidence = self.root / "evidence.json"
        collect = subprocess.run([
            sys.executable, "-B", str(scripts / "collect-model-support.py"),
            "--root", str(self.repo), "--fixture-dir", str(self.repo / "fixtures"),
            "--output", str(evidence),
        ], capture_output=True, text=True, timeout=10)
        self.assertEqual(collect.returncode, 0, collect.stderr)
        command = [
            sys.executable, "-B", str(scripts / "update-models.py"),
            "--root", str(self.repo), "--evidence", str(evidence),
            "--body-file", str(self.body_file),
        ]
        refused = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("NONPRODUCTION", refused.stderr)
        selected = subprocess.run(command + ["--test-only-fixtures"],
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(selected.returncode, 0, selected.stderr)
        check = subprocess.run(
            command + ["--test-only-fixtures", "--check", "--base-ref", "HEAD",
                       "--body-file", str(self.root / "check.md")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        published = self.run_helper(self.helper_env())
        self.assertEqual(published.returncode, 0, published.stderr)
        for path, effort in ((MODEL_PATHS[0], "high"), (MODEL_PATHS[1], "low")):
            remote = self.git(self.root, f"--git-dir={self.origin}", "show", f"{BRANCH}:{path}")
            self.assertIn(f"openai-codex/gpt-6.2-sol:{effort}", remote)
            self.assertNotIn("gpt-6-sol:", remote)
        self.assertEqual(self.git(self.root, f"--git-dir={self.origin}", "show",
                                 f"{BRANCH}:release-pins.json"), pins)
        calls = self.gh_log.read_text()
        self.assertIn("pr create --base main --head " + BRANCH, calls)
        self.assertIn("NOT VERIFIED", calls)
        self.assertNotIn("auto-merge", calls.lower())

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

    def test_held_model_pr_preserves_remote_repair_without_publication(self):
        self.git(self.repo, "switch", "-c", BRANCH)
        (self.repo / MODEL_PATHS[0]).write_text("model pin: repaired\n")
        self.git(self.repo, "add", MODEL_PATHS[0])
        self.git(self.repo, "commit", "-m", "manual model CI repair")
        repaired = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "push", "origin", BRANCH)
        self.git(self.repo, "switch", "main")
        (self.repo / MODEL_PATHS[0]).write_text("model pin: new upstream\n")

        result = self.run_helper(self.helper_env(GH_PR_HELD="true", GH_OPEN_PR="42"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ci-repair/manual-review", result.stdout)
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.repo, "rev-parse", BRANCH), repaired)
        self.assertEqual(
            self.git(self.root, f"--git-dir={self.origin}", "rev-parse", BRANCH), repaired,
        )
        self.assertNotIn("pr edit", self.gh_log.read_text())
        self.assertNotIn("pr create", self.gh_log.read_text())

    def test_unreadable_hold_status_never_publishes_model_update(self):
        (self.repo / MODEL_PATHS[0]).write_text("model pin: new upstream\n")
        result = self.run_helper(self.helper_env(GH_PR_HELD="invalid"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(
            self.git(self.root, f"--git-dir={self.origin}", "branch", "--list", BRANCH), "",
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
