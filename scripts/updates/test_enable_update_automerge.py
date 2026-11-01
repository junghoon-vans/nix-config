import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).with_name("enable-update-automerge.py")
HEAD = "a" * 40
REPO = "junghoon-vans/nix-config"
PR = {
    "node_id": "PR_fixture", "state": "open", "draft": False, "merged": False,
    "user": {"login": "nix-config-dependabot[bot]", "type": "Bot"},
    "base": {"ref": "main", "repo": {"full_name": REPO}},
    "head": {"ref": "automation/update-paseo-plugins", "sha": HEAD,
             "repo": {"full_name": REPO}},
    "changed_files": 1, "auto_merge": None,
    "mergeable_state": "clean",
}
# A subprocess fixture at the gh API boundary. It never contacts GitHub.
MOCK_GH = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
fixture = json.loads(Path(os.environ["GH_AUTOMERGE_FIXTURE"]).read_text())
pr = fixture["pr"]
if fixture.get("local_head"):
    pr["head"]["sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
mutation_log = Path(os.environ["GH_MUTATION_LOG"])
if "graphql" in args:
    query = next(arg[6:] for arg in args if arg.startswith("query="))
    if query.startswith("mutation"):
        with mutation_log.open("a") as output:
            output.write(json.dumps(args) + "\\n")
        if fixture.get("mutation_failure"):
            print("simulated schema/permission/head mismatch rejection", file=sys.stderr)
            sys.exit(42)
        if fixture.get("graphql_errors"):
            print(json.dumps({"errors": [{"message": "head changed"}], "data": None}))
            sys.exit(0)
        result = {"id": pr["node_id"], "headRefOid": pr["head"]["sha"],
                  "autoMergeRequest": {"mergeMethod": "SQUASH"}}
        if fixture.get("bad_response"):
            result["headRefOid"] = "b" * 40
        response = {"data": {"enablePullRequestAutoMerge": {"pullRequest": result}}}
    else:
        fields = [] if fixture.get("missing_expected_head") else [
            {"name": "expectedHeadOid", "type": {"name": "GitObjectID", "kind": "SCALAR"}}
        ]
        response = {"data": {"__type": {"inputFields": fields}}}
elif any("/files?" in arg for arg in args):
    response = fixture["pages"]
else:
    if fixture.get("read_failure"):
        sys.exit(43)
    if fixture.get("head_race"):
        counter = Path(os.environ["GH_AUTOMERGE_FIXTURE"] + ".reads")
        if counter.exists():
            pr["head"]["sha"] = "b" * 40
        counter.write_text("read")
    if mutation_log.exists() and not fixture.get("bad_readback"):
        pr["auto_merge"] = {"merge_method": "squash"}
    response = pr
print(json.dumps(response))
'''


class EnableUpdateAutomergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        gh = self.root / "gh"
        gh.write_text(MOCK_GH)
        gh.chmod(0o755)
        self.fixture_path = self.root / "fixture.json"
        self.log = self.root / "mutations.jsonl"
        self.fixture = {
            "pr": copy.deepcopy(PR),
            "pages": [[{"filename": "modules/paseo-plugins.json", "status": "modified"}]],
        }

    def run_helper(self, branch=None, head=HEAD, source="updater"):
        self.fixture_path.write_text(json.dumps(self.fixture))
        env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                   GH_AUTOMERGE_FIXTURE=str(self.fixture_path), GH_MUTATION_LOG=str(self.log))
        return subprocess.run(
            ["python3", "-B", str(HELPER), "--number", "7", "--branch",
             branch or self.fixture["pr"]["head"]["ref"], "--head", head, "--source", source],
            env=env, text=True, capture_output=True,
        )

    def assert_refused(self, **kwargs):
        result = self.run_helper(**kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Auto-merge refused", result.stderr)
        self.assertFalse(self.log.exists(), result.stderr)

    def test_all_real_updaters_enable_only_exact_head_squash(self):
        cases = {
            "homebrew": ["flake.lock"],
            "apm": ["release-pins.json"], "bun": ["release-pins.json"],
            "gnomcp": ["release-pins.json"], "omp": ["release-pins.json"],
            "paseo": ["release-pins.json"], "gno": ["modules/languages/gno.nix"],
            "hermes": ["flake.nix", "flake.lock"],
            "apm-skills": ["apm.yml", "apm.lock.yaml", "docs/skills.md"],
            "npm-mcps": ["home/.omp/agent/mcp.json"],
            "paseo-plugins": ["modules/paseo-plugins.json"],
        }
        for updater, paths in cases.items():
            with self.subTest(updater=updater):
                self.fixture["pr"]["head"]["ref"] = f"automation/update-{updater}"
                self.fixture["pr"]["changed_files"] = len(paths)
                # Separate pages prove the full returned file set is considered.
                self.fixture["pages"] = [[{"filename": path, "status": "modified"}] for path in paths]
                result = self.run_helper()
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = [json.loads(line) for line in self.log.read_text().splitlines()]
                self.assertEqual(len(calls), 1)
                query = next(arg for arg in calls[0] if arg.startswith("query="))
                self.assertIn("enablePullRequestAutoMerge", query)
                self.assertIn("expectedHeadOid: $head", query)
                self.assertIn("mergeMethod: SQUASH", query)
                self.assertNotIn("mergePullRequest", query)
                self.assertIn(f"head={HEAD}", calls[0])
                self.log.unlink()

    def test_untrusted_identity_state_repository_and_head_never_mutate(self):
        cases = [
            ("user", "login", "dependabot[bot]"), ("user", "login", "human"),
            ("user", "type", "User"), ("base", "ref", "other"),
            ("base", "repo", {"full_name": "attacker/nix-config"}),
            ("head", "repo", {"full_name": "attacker/nix-config"}),
            ("head", "repo", None), ("head", "sha", "b" * 40),
        ]
        for section, key, value in cases:
            with self.subTest(section=section, key=key, value=value):
                self.fixture["pr"] = copy.deepcopy(PR)
                self.fixture["pr"][section][key] = value
                self.assert_refused()
        for key, value in [("draft", True), ("state", "closed"), ("merged", True)]:
            with self.subTest(key=key):
                self.fixture["pr"] = copy.deepcopy(PR)
                self.fixture["pr"][key] = value
                self.assert_refused()

    def test_unknown_or_mismatched_branch_and_invalid_head_never_mutate(self):
        for branch in ["automation/update-paseo-plugins-extra", "dependabot/npm/x", "automation/update-homebrew"]:
            with self.subTest(branch=branch):
                self.assert_refused(branch=branch)
        self.assert_refused(head="not-a-sha")

    def test_out_of_scope_empty_incomplete_and_non_modified_files_never_mutate(self):
        cases = [
            [], [{"filename": "flake.lock", "status": "modified"}],
            [{"filename": ".github/workflows/validate.yml", "status": "modified"}],
            [{"filename": "modules/paseo-plugins.json", "status": "removed"}],
            [{"filename": "modules/paseo-plugins.json", "status": "added"}],
            [{"filename": "modules/paseo-plugins.json", "status": "renamed", "previous_filename": "evil"}],
            [{"filename": "modules/paseo-plugins.json", "status": "modified"},
             {"filename": "evil", "status": "modified"}],
        ]
        for files in cases:
            with self.subTest(files=files):
                self.fixture["pages"] = [files]
                self.assert_refused()
        self.fixture["pages"] = [[{"filename": "modules/paseo-plugins.json", "status": "modified"}]]
        self.fixture["pr"]["changed_files"] = 2
        self.assert_refused()

    def test_missing_atomic_api_support_or_read_failure_never_mutates(self):
        for flag in ["missing_expected_head", "read_failure"]:
            with self.subTest(flag=flag):
                self.fixture[flag] = True
                self.assert_refused()
                del self.fixture[flag]

    def test_head_change_during_file_listing_never_mutates(self):
        self.fixture["head_race"] = True
        self.assert_refused()

    def test_existing_squash_is_idempotent_but_wrong_method_is_refused(self):
        self.fixture["pr"]["auto_merge"] = {"merge_method": "squash"}
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already enabled", result.stdout)
        self.assertFalse(self.log.exists())
        self.fixture["pr"]["auto_merge"] = {"merge_method": "merge"}
        self.assert_refused()

    def test_mutation_rejections_and_unconfirmed_results_never_fallback_or_retry(self):
        for flag in ["mutation_failure", "graphql_errors", "bad_response", "bad_readback"]:
            with self.subTest(flag=flag):
                self.fixture[flag] = True
                result = self.run_helper()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Auto-merge refused", result.stderr)
                self.assertEqual(len(self.log.read_text().splitlines()), 1)
                self.log.unlink()
                del self.fixture[flag]

    def dependabot_fixture(self, ecosystem="nix"):
        self.fixture["pr"]["user"] = {
            "login": "dependabot[bot]", "id": 49699333, "type": "Bot",
        }
        if ecosystem == "nix":
            branch = "dependabot/nix/flake-inputs-9d3459cedb"
            paths = ["flake.nix", "flake.lock"]
        else:
            branch = "dependabot/github_actions/github-actions-d87422eef0"
            paths = [".github/workflows/mcp-security.yml",
                     ".github/workflows/update-dependencies.yml",
                     ".github/workflows/validate.yml",
                     ".github/workflows/dependabot-automerge.yml"]
        self.fixture["pr"]["head"]["ref"] = branch
        self.fixture["pr"]["changed_files"] = len(paths)
        self.fixture["pages"] = [[{"filename": path, "status": "modified"}] for path in paths]

    def test_dependabot_grouped_nix_and_actions_updates_enable(self):
        for ecosystem in ("nix", "github_actions"):
            with self.subTest(ecosystem=ecosystem):
                self.dependabot_fixture(ecosystem)
                result = self.run_helper(source="dependabot")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Enabled SQUASH auto-merge", result.stdout)
                self.log.unlink()

    def test_dependabot_rejects_spoofed_identity_and_untrusted_metadata(self):
        changes = [
            ("user", "id", 1), ("user", "login", "human"),
            ("user", "type", "User"),
            ("head", "repo", {"full_name": "attacker/nix-config"}),
            ("base", "ref", "other"), ("head", "sha", "b" * 40),
        ]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                self.dependabot_fixture()
                self.fixture["pr"][section][key] = value
                self.assert_refused(source="dependabot")
                self.fixture["pr"] = copy.deepcopy(PR)
        for key, value in (("draft", True), ("state", "closed"), ("merged", True)):
            with self.subTest(key=key):
                self.dependabot_fixture()
                self.fixture["pr"][key] = value
                self.assert_refused(source="dependabot")
                self.fixture["pr"] = copy.deepcopy(PR)

    def test_dependabot_requires_matching_ecosystem_branch_paths_and_complete_modifications(self):
        for ecosystem, path in (
            ("nix", ".github/workflows/validate.yml"),
            ("github_actions", "flake.lock"),
            ("github_actions", ".github/workflows/attacker.yml"),
            ("github_actions", ".github/dependabot.yml"),
            ("nix", "scripts/updates/enable-update-automerge.py"),
        ):
            with self.subTest(ecosystem=ecosystem, path=path):
                self.dependabot_fixture(ecosystem)
                self.fixture["pages"][0][0]["filename"] = path
                self.assert_refused(source="dependabot")
        for status in ("added", "removed", "renamed"):
            with self.subTest(status=status):
                self.dependabot_fixture()
                self.fixture["pages"][0][0]["status"] = status
                self.assert_refused(source="dependabot")
        self.dependabot_fixture()
        self.fixture["pages"].pop()
        self.assert_refused(source="dependabot")
        self.dependabot_fixture()
        self.assert_refused(source="dependabot", branch="dependabot/nix/flake-inputs-bad")
        self.assert_refused(source="dependabot", branch="dependabot/npm/x")
        self.assert_refused()  # Dependabot cannot enter the CI updater trust domain.
        self.fixture["pr"] = copy.deepcopy(PR)
        self.assert_refused(source="dependabot")  # Nor can the CI App enter Dependabot's.

    def test_dependabot_head_race_never_mutates(self):
        self.dependabot_fixture()
        self.fixture["head_race"] = True
        self.assert_refused(source="dependabot")


if __name__ == "__main__":
    unittest.main()
