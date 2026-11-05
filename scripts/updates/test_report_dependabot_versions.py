import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("report-dependabot-versions.py")
REAL_MIXED_FIXTURE = Path(__file__).with_name("fixtures") / "dependabot-mixed-344.json"
REPOSITORY = "junghoon-vans/nix-config"
PR_NUMBER = 7
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
ACTION_FILE = ".github/workflows/validate.yml"
MIXED_PATHS = ("flake.lock", "release-pins.json")
MIXED_HEAD = "5ebea26b470f70c9f78863d2648ec23c5efa75d9"
MIXED_BASE = "1406520b31eb0ffed0cd33b5bcbc63c90440fe5e"
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
number = fixture["pr"]["number"]
api_log = os.environ.get("GH_API_LOG")
if api_log:
    with Path(api_log).open("a") as output:
        output.write(json.dumps(args) + "\n")

failure = fixture.get("api_failure")
if failure and (failure == "all" or failure in endpoint):
    print("simulated GitHub API failure", file=sys.stderr)
    sys.exit(92)

if f"/pulls/{number}/files?" in endpoint:
    print(json.dumps(fixture["file_pages"]))
elif "/contents/" in endpoint:
    split = urlsplit(endpoint)
    path = unquote(split.path.split("/contents/", 1)[1])
    revision = parse_qs(split.query)["ref"][0]
    content = fixture["contents"][revision][path]
    if not isinstance(content, str):
        content = json.dumps(content)
    print(json.dumps({
        "type": "file", "encoding": "base64",
        "content": base64.b64encode(content.encode()).decode(),
    }))
elif endpoint.endswith(f"/pulls/{number}"):
    fixture["pr_reads"] = fixture.get("pr_reads", 0) + 1
    response = copy.deepcopy(fixture["pr"])
    if fixture.get("stale_on_final_read") and fixture["pr_reads"] > 1:
        response["head"]["sha"] = "3" * 40
    fixture_path.write_text(json.dumps(fixture))
    print(json.dumps(response))
elif endpoint.endswith(f"/issues/{number}") and "PATCH" in args:
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
        self.api_log = self.root / "api.jsonl"
        self.output_path = self.root / "github-output"

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

    def use_real_mixed_fixture(self):
        value = json.loads(REAL_MIXED_FIXTURE.read_text())
        self.fixture_path.write_text(json.dumps(value))
        return value

    def run_report(
        self, expected_head=HEAD_SHA, number=PR_NUMBER, output=True, renderer_failure=False
    ):
        for path in (self.output_path, self.api_log):
            if path.exists():
                path.unlink()
        env = os.environ.copy()
        env.update({
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
            "GH_TOKEN": "offline-test-token",
            "PR_NUMBER": str(number),
            "PR_HEAD": expected_head,
            "REPORT_FIXTURE": str(self.fixture_path),
            "GH_PATCH_LOG": str(self.patch_log),
            "GH_API_LOG": str(self.api_log),
        })
        if output:
            env["GITHUB_OUTPUT"] = str(self.output_path)
        else:
            env.pop("GITHUB_OUTPUT", None)
        if renderer_failure:
            sitecustomize = self.root / "sitecustomize.py"
            sitecustomize.write_text(
                "import os, sys, types\n"
                "if os.environ.get('REPORT_RENDERER_FAILURE') == '1':\n"
                "    renderer = types.ModuleType('version_table')\n"
                "    def render_table(rows):\n"
                "        raise ValueError('simulated version table renderer failure')\n"
                "    renderer.render_table = render_table\n"
                "    sys.modules['version_table'] = renderer\n"
            )
            env["PYTHONPATH"] = str(self.root) + os.pathsep + env.get("PYTHONPATH", "")
            env["REPORT_RENDERER_FAILURE"] = "1"
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

    def api_calls(self):
        if not self.api_log.exists():
            return []
        return [json.loads(line) for line in self.api_log.read_text().splitlines()]

    def output(self):
        return self.output_path.read_text() if self.output_path.exists() else ""

    def assert_no_true_output(self):
        self.assertNotIn("auto_merge_eligible=true", self.output())

    def assert_no_content_reads_or_patches(self):
        calls = [" ".join(args) for args in self.api_calls()]
        self.assertFalse(any("/contents/" in call for call in calls), calls)
        self.assertFalse(any("PATCH" in call for call in calls), calls)
        self.assertEqual(self.patches(), [])

    def assert_only_pr_validation_was_attempted(self):
        calls = [" ".join(args) for args in self.api_calls()]
        self.assertTrue(calls, "expected a mocked GitHub API request")
        self.assertFalse(any("/files?" in call or "/contents/" in call for call in calls), calls)
        self.assertFalse(any("PATCH" in call for call in calls), calls)
        self.assertEqual(self.patches(), [])

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
        self.assertEqual(self.output().strip(), "auto_merge_eligible=true")
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

    def test_action_mixed_report_keeps_real_pin_changes_and_omits_unchanged(self):
        old_revision, new_revision = "a" * 40, "b" * 40
        unchanged_revision = "c" * 40
        metadata_revision = "d" * 40
        before = workflow(
            f"      - uses: actions/checkout@{old_revision} # v4.0.0\n"
            f"      - uses: actions/cache@{metadata_revision} # v3.0.0\n"
            f"      - uses: actions/setup-node@{unchanged_revision} # v4.0.0\n"
        )
        after = workflow(
            f"      - uses: actions/checkout@{new_revision} # v4.0.0\n"
            f"      - uses: actions/cache@{metadata_revision} # v3.0.1\n"
            f"      - uses: actions/setup-node@{unchanged_revision} # v4.0.0\n"
        )
        self.fixture(pull_request(), [{"filename": ACTION_FILE, "status": "modified"}], {
            BASE_SHA: {ACTION_FILE: before},
            HEAD_SHA: {ACTION_FILE: after},
        })

        result = self.run_report()

        self.assertEqual(result.returncode, 0, result.stderr)
        patches = self.patches()
        self.assertEqual(len(patches), 1)
        body = patches[0]["body"]
        section = body.split("<!-- dependabot-version-report:start -->", 1)[1].split(
            "<!-- dependabot-version-report:end -->", 1
        )[0]
        self.assertIn(old_revision, section)
        self.assertIn(new_revision, section)
        self.assertEqual(section.count("v4.0.0"), 2)
        self.assertIn("Action revision updated", section)
        self.assertIn("Action pin metadata updated", section)
        self.assertIn("actions/checkout", section)
        self.assertIn("actions/cache", section)
        self.assertIn("v3.0.0", section)
        self.assertIn("v3.0.1", section)
        self.assertNotIn("actions/setup-node", section)
        self.assertNotIn("| Unchanged |", section)
        self.assertEqual(sum(line.startswith("| ") for line in section.splitlines()), 4)

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
        self.assertEqual(self.output().strip(), "auto_merge_eligible=true")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.output().strip(), "auto_merge_eligible=true")
        patches = self.patches()
        self.assertEqual(len(patches), 1)
        body = patches[0]["body"]
        self.assertIn("Original PR details", body)
        self.assertIn("No dependency pin changes.", body)
        self.assertNotIn("No dependency changes were detected.", body)
        self.assertNotIn("| Dependency |", body)
        self.assertEqual(body.count("No dependency pin changes."), 1)
        self.assertEqual(body.count("<!-- dependabot-version-report:start -->"), 1)

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

        self.assert_no_true_output()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.patches(), [])

    def test_untrusted_dependabot_identity_is_refused_before_body_patch(self):
        pr = pull_request()
        pr["user"]["id"] = 123
        self.fixture(pr, [], {BASE_SHA: {}, HEAD_SHA: {}})

        result = self.run_report()

        self.assert_no_true_output()
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
        self.assertEqual(self.output().strip(), "auto_merge_eligible=true")
        self.assertEqual(len(self.patches()), 1)
        body = self.patches()[0]["body"]
        self.assertIn(old_direct, body)
        self.assertIn(new_direct, body)
        self.assertIn(old_transitive, body)
        self.assertIn(new_transitive, body)

    def test_nix_mixed_report_keeps_exact_pin_change_and_omits_unchanged_input(self):
        old_direct, new_direct = "a" * 40, "b" * 40
        unchanged_transitive = "c" * 40
        before = json.loads(lockfile(old_direct, unchanged_transitive))
        after = json.loads(lockfile(new_direct, unchanged_transitive))
        before["nodes"]["direct"]["locked"]["narHash"] = "sha256-old-direct"
        after["nodes"]["direct"]["locked"]["narHash"] = "sha256-new-direct"
        before["nodes"]["direct"]["original"]["ref"] = "v1.2.3"
        after["nodes"]["direct"]["original"]["ref"] = "v1.2.3"
        pr = pull_request("dependabot/nix/flake-inputs-abcdef0123")
        self.fixture(pr, [{"filename": "flake.lock", "status": "modified"}], {
            BASE_SHA: {"flake.lock": json.dumps(before)},
            HEAD_SHA: {"flake.lock": json.dumps(after)},
        })

        result = self.run_report()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.patches()), 1)
        body = self.patches()[0]["body"]
        section = body.split("<!-- dependabot-version-report:start -->", 1)[1].split(
            "<!-- dependabot-version-report:end -->", 1
        )[0]
        self.assertIn(old_direct, section)
        self.assertIn(new_direct, section)
        self.assertIn("narHash: sha256-old-direct", section)
        self.assertIn("narHash: sha256-new-direct", section)
        self.assertIn("flake input direct", section)
        self.assertNotIn("flake input transitive", section)
        self.assertNotIn("| Unchanged |", section)
        self.assertNotIn("No dependency pin changes.", section)
        self.assertEqual(sum(line.startswith("| ") for line in section.splitlines()), 3)

    def test_nix_noop_report_has_no_empty_dependency_row(self):
        content = lockfile("a" * 40, "c" * 40)
        pr = pull_request("dependabot/nix/flake-inputs-abcdef0123")
        self.fixture(pr, [{"filename": "flake.lock", "status": "modified"}], {
            BASE_SHA: {"flake.lock": content},
            HEAD_SHA: {"flake.lock": content},
        })

        result = self.run_report()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.patches()), 1)
        body = self.patches()[0]["body"]
        section = body.split("<!-- dependabot-version-report:start -->", 1)[1].split(
            "<!-- dependabot-version-report:end -->", 1
        )[0]
        self.assertEqual(section.strip(), "### Dependency version changes\n\nNo dependency pin changes.")
        self.assertNotIn("| Dependency |", section)

    def assert_mixed_rejected(self, fixture):
        self.fixture_path.write_text(json.dumps(fixture))
        result = self.run_report(expected_head=MIXED_HEAD, number=344)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_no_true_output()
        self.assert_no_content_reads_or_patches()

    def test_real_pr344_mixed_update_skips_reporting_and_auto_merge_eligibility(self):
        fixture = self.use_real_mixed_fixture()

        self.assertEqual(fixture["pr"]["number"], 344)
        self.assertEqual(fixture["pr"]["head"]["sha"], MIXED_HEAD)
        self.assertEqual(fixture["pr"]["base"]["sha"], MIXED_BASE)
        self.assertEqual(
            [item["filename"] for item in fixture["file_pages"][0]],
            list(MIXED_PATHS),
        )

        result = self.run_report(expected_head=MIXED_HEAD, number=344)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manual", result.stderr.lower())
        self.assertEqual(self.output().strip(), "auto_merge_eligible=false")
        self.assert_no_content_reads_or_patches()
        calls = [" ".join(args) for args in self.api_calls()]
        self.assertTrue(any("/pulls/344/files?" in call for call in calls), calls)

    def test_mixed_paths_with_nonhash_version_or_url_changes_stay_manual(self):
        for field in ("version", "url"):
            with self.subTest(field=field):
                fixture = self.use_real_mixed_fixture()
                before = copy.deepcopy(
                    fixture["contents"][MIXED_BASE]["release-pins.json"]
                )
                after = copy.deepcopy(before)
                if field == "version":
                    after["agent-desktop"]["version"] = "1.0.3"
                else:
                    before["agent-desktop"]["url"] = "https://example.com/old"
                    after["agent-desktop"]["url"] = "https://example.com/new"
                fixture["contents"][MIXED_BASE]["release-pins.json"] = before
                fixture["contents"][MIXED_HEAD]["release-pins.json"] = after
                self.fixture_path.write_text(json.dumps(fixture))

                result = self.run_report(expected_head=MIXED_HEAD, number=344)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("manual", result.stderr.lower())
                self.assertEqual(self.output().strip(), "auto_merge_eligible=false")
                self.assert_no_content_reads_or_patches()

    def test_mixed_nix_update_allows_optional_flake_nix_but_stays_manual(self):
        fixture = self.use_real_mixed_fixture()
        fixture["file_pages"][0].append({
            "filename": "flake.nix", "status": "modified",
        })
        fixture["pr"]["changed_files"] = 3
        self.fixture_path.write_text(json.dumps(fixture))

        result = self.run_report(expected_head=MIXED_HEAD, number=344)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("manual", result.stderr.lower())
        self.assertEqual(self.output().strip(), "auto_merge_eligible=false")
        self.assert_no_content_reads_or_patches()

    def test_mixed_update_rejects_unexpected_duplicate_incomplete_and_malformed_files(self):
        def fixture_with_files():
            fixture = self.use_real_mixed_fixture()
            return fixture, copy.deepcopy(fixture["file_pages"][0])

        fixture, files = fixture_with_files()
        files.append({"filename": "rogue.txt", "status": "modified"})
        fixture["file_pages"] = [files]
        fixture["pr"]["changed_files"] = 3
        cases = [("unexpected extra path", fixture)]

        fixture, files = fixture_with_files()
        fixture["file_pages"] = [
            [files[0]],
            [copy.deepcopy(files[0]), files[1]],
        ]
        fixture["pr"]["changed_files"] = 3
        cases.append(("duplicate path across pages", fixture))

        fixture, files = fixture_with_files()
        files.append(copy.deepcopy(files[1]))
        fixture["file_pages"] = [files]
        fixture["pr"]["changed_files"] = 3
        cases.append(("duplicate path", fixture))

        fixture, _ = fixture_with_files()
        fixture["pr"]["changed_files"] = 3
        cases.append(("incomplete pagination", fixture))

        fixture, files = fixture_with_files()
        fixture["file_pages"] = [files[0], files[1]]
        cases.append(("malformed page", fixture))

        fixture, files = fixture_with_files()
        files[0] = "flake.lock"
        fixture["file_pages"] = [files]
        cases.append(("malformed file entry", fixture))

        for filename in ("", None, []):
            fixture, files = fixture_with_files()
            files[0]["filename"] = filename
            fixture["file_pages"] = [files]
            cases.append((f"malformed filename {filename!r}", fixture))

        fixture, files = fixture_with_files()
        files[0]["previous_filename"] = "flake.lock"
        fixture["file_pages"] = [files]
        cases.append(("previous filename on modified entry", fixture))

        for status in ("renamed", "removed", "added"):
            fixture, files = fixture_with_files()
            files[0]["status"] = status
            if status == "renamed":
                files[0]["previous_filename"] = "flake.nix"
            fixture["file_pages"] = [files]
            cases.append((f"{status} path", fixture))

        for name, fixture in cases:
            with self.subTest(case=name):
                self.assert_mixed_rejected(fixture)

    def test_untrusted_pr_metadata_fails_before_mixed_paths_can_be_skipped(self):
        changes = [
            ("bot id", ("user", "id", 1)),
            ("bot login", ("user", "login", "human")),
            ("bot type", ("user", "type", "User")),
            ("fork head repository", (
                "head", "repo", {"full_name": "attacker/nix-config"},
            )),
            ("wrong base branch", ("base", "ref", "release")),
            ("fork base repository", (
                "base", "repo", {"full_name": "attacker/nix-config"},
            )),
            ("invalid base SHA", ("base", "sha", "not-a-sha")),
            ("unsupported branch", (
                "head", "ref", "dependabot/nix/flake-inputs-invalid",
            )),
            ("wrong head SHA", ("head", "sha", "3" * 40)),
        ]
        for name, (section, key, value) in changes:
            with self.subTest(case=name):
                fixture = self.use_real_mixed_fixture()
                fixture["pr"][section][key] = value
                self.fixture_path.write_text(json.dumps(fixture))
                result = self.run_report(expected_head=MIXED_HEAD, number=344)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assert_no_true_output()
                self.assert_only_pr_validation_was_attempted()

        fixture = self.use_real_mixed_fixture()
        self.fixture_path.write_text(json.dumps(fixture))
        result = self.run_report(expected_head="3" * 40, number=344)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_no_true_output()
        self.assert_only_pr_validation_was_attempted()

    def test_api_renderer_and_body_marker_failures_never_emit_true_eligibility(self):
        action_content = workflow(f"      - uses: actions/checkout@{'a' * 40}\n")
        failure_cases = (
            ("content API failure", {"api_failure": "/contents/"}, False, "Original PR details"),
            ("renderer failure", {}, True, "Original PR details"),
            (
                "malformed body markers", {},
                False, "<!-- dependabot-version-report:start -->",
            ),
            (
                "body PATCH API failure", {"api_failure": "/issues/"},
                False, "Original PR details",
            ),
        )
        for name, options, renderer_failure, body in failure_cases:
            with self.subTest(case=name):
                self.fixture(
                    pull_request(body=body),
                    [{"filename": ACTION_FILE, "status": "modified"}],
                    {
                        BASE_SHA: {ACTION_FILE: action_content},
                        HEAD_SHA: {ACTION_FILE: action_content},
                    },
                    **options,
                )
                result = self.run_report(renderer_failure=renderer_failure)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assert_no_true_output()
                self.assertEqual(self.patches(), [])

    def test_standalone_reporting_succeeds_without_github_output(self):
        content = workflow(f"      - uses: actions/checkout@{'a' * 40}\n")
        self.fixture(
            pull_request(),
            [{"filename": ACTION_FILE, "status": "modified"}],
            {BASE_SHA: {ACTION_FILE: content}, HEAD_SHA: {ACTION_FILE: content}},
        )

        result = self.run_report(output=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output_path.exists())
        self.assertEqual(len(self.patches()), 1)



if __name__ == "__main__":
    unittest.main()
