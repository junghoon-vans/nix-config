import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("report-dependabot-versions.py")
REPOSITORY = "junghoon-vans/nix-config"
PR_NUMBER = 7
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
ACTION_FILE = ".github/workflows/validate.yml"
MOCK_GH = r'''#!/usr/bin/env python3
import base64
import copy
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlsplit

args = sys.argv[1:]
endpoint = next((arg for arg in args if arg.startswith("repos/")), "")
fixture_path = Path(os.environ["REPORT_FIXTURE"])
fixture = json.loads(fixture_path.read_text())

if "/pulls/7/files?" in endpoint:
    print(json.dumps(fixture["file_pages"]))
elif "/contents/" in endpoint:
    split = urlsplit(endpoint)
    path = unquote(split.path.split("/contents/", 1)[1])
    revision = parse_qs(split.query)["ref"][0]
    content = fixture["contents"][revision][path]
    print(json.dumps({
        "type": "file", "encoding": "base64",
        "content": base64.b64encode(content.encode()).decode(),
    }))
elif endpoint.endswith("/pulls/7"):
    fixture["pr_reads"] = fixture.get("pr_reads", 0) + 1
    response = copy.deepcopy(fixture["pr"])
    if fixture.get("stale_on_final_read") and fixture["pr_reads"] > 1:
        response["head"]["sha"] = "3" * 40
    fixture_path.write_text(json.dumps(fixture))
    print(json.dumps(response))
elif endpoint.endswith("/issues/7") and "PATCH" in args:
    payload = json.loads(sys.stdin.read())
    Path(os.environ["GH_PATCH_LOG"]).open("a").write(json.dumps(payload) + "\n")
    fixture["pr"]["body"] = payload["body"]
    fixture_path.write_text(json.dumps(fixture))
    print(json.dumps({"body": payload["body"]}))
else:
    print("unexpected mocked GitHub API request", file=sys.stderr)
    sys.exit(91)
'''


def pull_request(branch="dependabot/github_actions/github-actions-abcdef0123", body="Original PR details"):
    return {
        "number": PR_NUMBER,
        "state": "open",
        "draft": False,
        "merged": False,
        "user": {"login": "dependabot[bot]", "id": 49699333, "type": "Bot"},
        "base": {
            "ref": "main", "sha": BASE_SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "head": {
            "ref": branch, "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "changed_files": 1,
        "body": body,
    }


def workflow(contents):
    return "name: fixture\njobs:\n  test:\n    steps:\n" + contents


def lockfile(rev_direct, rev_transitive):
    return json.dumps({
        "nodes": {
            "root": {"inputs": {"direct": "direct"}},
            "direct": {
                "inputs": {"deep": "transitive"},
                "locked": {
                    "lastModified": 1, "narHash": "sha256-direct",
                    "owner": "fixture", "repo": "direct", "rev": rev_direct,
                    "type": "github",
                },
                "original": {"owner": "fixture", "repo": "direct", "type": "github"},
            },
            "transitive": {
                "locked": {
                    "lastModified": 2, "narHash": "sha256-transitive",
                    "owner": "fixture", "repo": "transitive", "rev": rev_transitive,
                    "type": "github",
                },
                "original": {"owner": "fixture", "repo": "transitive", "type": "github"},
            },
        },
        "root": "root",
        "version": 7,
    })


class DependabotVersionReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(MOCK_GH)
        gh.chmod(0o755)
        self.fixture_path = self.root / "fixture.json"
        self.patch_log = self.root / "patches.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, pr, files, contents, **options):
        value = {
            "pr": pr,
            "file_pages": [files],
            "contents": contents,
            **options,
        }
        self.fixture_path.write_text(json.dumps(value))

    def run_report(self, expected_head=HEAD_SHA):
        env = os.environ.copy()
        env.update({
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
            "GH_TOKEN": "offline-test-token",
            "PR_NUMBER": str(PR_NUMBER),
            "PR_HEAD": expected_head,
            "REPORT_FIXTURE": str(self.fixture_path),
            "GH_PATCH_LOG": str(self.patch_log),
        })
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.root,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def patches(self):
        if not self.patch_log.exists():
            return []
        return [json.loads(line) for line in self.patch_log.read_text().splitlines()]

    def test_action_updates_additions_removals_and_pin_metadata_are_patched(self):
        old_checkout = "a" * 40
        new_checkout = "b" * 40
        removed_revision = "c" * 40
        added_revision = "d" * 40
        before = workflow(
            f"      - uses: actions/checkout@{old_checkout} # v1.0.0\n"
            f"      - uses: fixture/removed-action@{removed_revision}\n"
        )
        after = workflow(
            f"      - uses: actions/checkout@{new_checkout} # v2.0.0 | untrusted\n"
            f"      - uses: fixture/added-action@{added_revision}\n"
        )
        pr = pull_request()
        self.fixture(pr, [{"filename": ACTION_FILE, "status": "modified"}], {
            BASE_SHA: {ACTION_FILE: before},
            HEAD_SHA: {ACTION_FILE: after},
        })

        result = self.run_report()

        self.assertEqual(result.returncode, 0, result.stderr)
        patches = self.patches()
        self.assertEqual(len(patches), 1)
        body = patches[0]["body"]
        self.assertIn("Original PR details", body)
        self.assertIn("<!-- dependabot-version-report:start -->", body)
        self.assertIn("<!-- dependabot-version-report:end -->", body)
        self.assertIn(old_checkout, body)
        self.assertIn(new_checkout, body)
        self.assertIn("v1.0.0", body)
        self.assertIn("v2.0.0 &#124; untrusted", body)
        self.assertIn("Action revision updated", body)
        self.assertIn("Action reference added", body)
        self.assertIn("Action reference removed", body)
        self.assertIn(added_revision, body)
        self.assertIn(removed_revision, body)

    def test_noop_report_is_idempotent_and_keeps_existing_body(self):
        content = workflow(f"      - uses: actions/checkout@{'a' * 40}\n")
        self.fixture(
            pull_request(),
            [{"filename": ACTION_FILE, "status": "modified"}],
            {BASE_SHA: {ACTION_FILE: content}, HEAD_SHA: {ACTION_FILE: content}},
        )

        first = self.run_report()
        second = self.run_report()

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        patches = self.patches()
        self.assertEqual(len(patches), 1)
        body = patches[0]["body"]
        self.assertIn("Original PR details", body)
        self.assertIn("No dependency changes were detected.", body)
        self.assertEqual(body.count("<!-- dependabot-version-report:start -->"), 1)

    def test_action_comment_only_change_is_not_reported_as_dependency_change(self):
        revision = "a" * 40
        before = workflow(f"      - uses: actions/checkout@{revision} # v1.0.0\n")
        after = workflow(f"      - uses: actions/checkout@{revision} # v1.0.1\n")
        self.fixture(
            pull_request(),
            [{"filename": ACTION_FILE, "status": "modified"}],
            {BASE_SHA: {ACTION_FILE: before}, HEAD_SHA: {ACTION_FILE: after}},
        )

        result = self.run_report()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.patches()), 1)
        body = self.patches()[0]["body"]
        self.assertIn("No dependency changes were detected.", body)
        self.assertNotIn("Action pin metadata updated", body)
        self.assertNotIn(revision, body)

    def test_stale_head_is_refused_before_body_patch(self):
        before = workflow(f"      - uses: actions/checkout@{'a' * 40}\n")
        after = workflow(f"      - uses: actions/checkout@{'b' * 40}\n")
        self.fixture(
            pull_request(),
            [{"filename": ACTION_FILE, "status": "modified"}],
            {BASE_SHA: {ACTION_FILE: before}, HEAD_SHA: {ACTION_FILE: after}},
            stale_on_final_read=True,
        )

        result = self.run_report()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.patches(), [])

    def test_untrusted_dependabot_identity_is_refused_before_body_patch(self):
        pr = pull_request()
        pr["user"]["id"] = 123
        self.fixture(pr, [], {BASE_SHA: {}, HEAD_SHA: {}})

        result = self.run_report()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.patches(), [])

    def test_nix_report_uses_shared_comparison_for_transitive_lock_pins(self):
        old_direct, new_direct = "a" * 40, "b" * 40
        old_transitive, new_transitive = "c" * 40, "d" * 40
        pr = pull_request("dependabot/nix/flake-inputs-abcdef0123")
        self.fixture(pr, [{"filename": "flake.lock", "status": "modified"}], {
            BASE_SHA: {"flake.lock": lockfile(old_direct, old_transitive)},
            HEAD_SHA: {"flake.lock": lockfile(new_direct, new_transitive)},
        })

        result = self.run_report()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.patches()), 1)
        body = self.patches()[0]["body"]
        self.assertIn(old_direct, body)
        self.assertIn(new_direct, body)
        self.assertIn(old_transitive, body)
        self.assertIn(new_transitive, body)


if __name__ == "__main__":
    unittest.main()
