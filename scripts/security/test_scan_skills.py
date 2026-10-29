import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("scan-skills.py")
spec = importlib.util.spec_from_file_location("scan_skills", SCRIPT)
scan_skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_skills)


COMMIT = "a" * 40
CONTENT_HASH = "sha256:" + "1" * 64


def dependency(name="sample", **overrides):
    entry = {
        "repo_url": "example/skills",
        "name": name,
        "host": "github.com",
        "resolved_commit": COMMIT,
        "resolved_ref": "v1.2.3",
        "virtual_path": f"skills/{name}",
        "content_hash": CONTENT_HASH,
        "is_virtual": True,
        "package_type": "claude_skill",
    }
    entry.update(overrides)
    return entry


def complete_report(score=0, severity="LOW", recommendation="SAFE", issues=None):
    return {
        "skill": {
            "name": "sample",
            "source": "https://github.com/example/skills",
            "scanned_at": "2026-01-01T00:00:00Z",
        },
        "risk_assessment": {
            "score": score,
            "severity": severity,
            "recommendation": recommendation,
        },
        "components": [
            {
                "path": "SKILL.md",
                "type": "markdown",
                "lines": 1,
                "executable": False,
                "size_bytes": 1,
            }
        ],
        "issues": [] if issues is None else issues,
        "metadata": {
            "skillspector_version": "2.12.0",
            "llm_requested": False,
            "llm_available": False,
        },
        "execution_successful": True,
        "analysis_completeness": {
            "total_components": 1,
            "scanned_components": 1,
            "coverage_percent": 100.0,
            "is_complete": True,
            "status": "complete",
            "execution_successful": True,
            "fully_inspected_files": 1,
            "partially_inspected_files": 0,
            "entirely_uninspected_files": 0,
            "ledger_exceptions": [],
            "scope_exclusions": [],
            "analyzer_statuses": [
                {
                    "analyzer_id": "static_patterns_prompt_injection",
                    "status": "completed",
                    "planned_work": 1,
                    "completed": 1,
                    "partial": 0,
                    "skipped": 0,
                    "failed": 0,
                    "unaccounted": 0,
                },
                {
                    "analyzer_id": "semantic_developer_intent",
                    "status": "disabled",
                    "planned_work": 0,
                    "completed": 0,
                    "partial": 0,
                    "skipped": 0,
                    "failed": 0,
                    "unaccounted": 0,
                    "reason_code": "disabled_by_configuration",
                    "message": "Analyzer was disabled by the requested configuration.",
                },
                {
                    "analyzer_id": "behavioral_ast",
                    "status": "not_applicable",
                    "planned_work": 0,
                    "completed": 0,
                    "partial": 0,
                    "skipped": 0,
                    "failed": 0,
                    "unaccounted": 0,
                    "reason_code": "no_applicable_files",
                    "message": "No files matched this analyzer's applicability contract.",
                },
            ],
            "references": [],
            "limitations": [],
        },
    }


def finding(severity):
    return {
        "id": f"TEST-{severity}",
        "category": "test",
        "severity": severity,
        "confidence": 1.0,
        "location": {"file": "SKILL.md", "start_line": 1},
    }


class ChangedDependenciesTests(unittest.TestCase):
    def test_additions_and_operational_changes_are_selected(self):
        unchanged = dependency("unchanged")
        ref_changed = dependency("ref-changed", resolved_ref="v2.0.0")
        content_changed = dependency("content-changed", content_hash="sha256:" + "2" * 64)
        added = dependency("added")
        removed = dependency("removed")

        base = {"dependencies": [unchanged, dependency("ref-changed"), dependency("content-changed"), removed]}
        head = {"dependencies": [unchanged, ref_changed, content_changed, added]}

        selected = scan_skills.changed_dependencies(base, head)

        self.assertEqual(
            {entry["name"] for entry in selected},
            {"ref-changed", "content-changed", "added"},
        )
        self.assertEqual(len(selected), 3)

    def test_changes_to_locked_scan_inputs_are_selected(self):
        original = dependency()
        changes = {
            "repo_url": "different/skills",
            "materialization_repo_url": "Different/skills",
            "host": "github.com.attacker.invalid",
            "resolved_commit": "b" * 40,
            "resolved_ref": "release/v2",
            "virtual_path": "packages/sample",
            "content_hash": "sha256:" + "3" * 64,
            "package_type": "other",
            "is_virtual": False,
        }

        for field, value in changes.items():
            with self.subTest(field=field):
                updated = dependency(**{field: value})
                selected = scan_skills.changed_dependencies(
                    {"dependencies": [original]},
                    {"dependencies": [updated]},
                )
                self.assertEqual(selected, [updated])

    def test_removals_and_deployment_only_changes_are_not_selected(self):
        retained = dependency("retained")
        removed = dependency("removed")
        base = {
            "apm_version": "0.33.0",
            "dependencies": [retained, removed],
            "deployments": [{"name": "old", "target": "local"}],
        }
        head = {
            "apm_version": "0.34.0",
            "dependencies": [retained],
            "deployments": [{"name": "new", "target": "remote"}],
        }

        self.assertEqual(scan_skills.changed_dependencies(base, head), [])


class LocalDependencyTests(unittest.TestCase):
    def test_local_manifest_and_lock_identity_are_supported(self):
        manifest = {"dependencies": {"apm": [{"path": "./skills/jira-cloud-formatting"}]}}
        lock = {"dependencies": [{
            "repo_url": "_local/jira-cloud-formatting",
            "name": "jira-cloud-formatting",
            "version": "unknown",
            "package_type": "claude_skill",
            "source": "local",
            "local_path": "./skills/jira-cloud-formatting",
        }]}

        scan_skills._assert_manifest_lock_consistent(manifest, lock, "head")

    def test_local_manifest_paths_are_restricted_to_safe_skill_directories(self):
        unsafe_paths = (
            "/skills/jira-cloud-formatting",
            "../skills/jira-cloud-formatting",
            "./skills/../outside",
            "./other/jira-cloud-formatting",
            "./skills/nested/jira-cloud-formatting",
            "./skills/jira-cloud-formatting/",
            "./skills/jira-cloud-formatting\\outside",
            "./skills/.git",
        )
        for path in unsafe_paths:
            with self.subTest(path=path):
                manifest = {"dependencies": {"apm": [{"path": path}]}}
                with self.assertRaises(scan_skills.ScanError):
                    scan_skills._manifest_dependencies(manifest)

    def test_local_lock_source_path_and_name_must_match_manifest(self):
        manifest = {"dependencies": {"apm": [{"path": "./skills/jira-cloud-formatting"}]}}
        entry = {
            "repo_url": "_local/jira-cloud-formatting",
            "name": "jira-cloud-formatting",
            "version": "unknown",
            "package_type": "claude_skill",
            "source": "local",
            "local_path": "./skills/jira-cloud-formatting",
        }
        invalid_values = {
            "repo_url": "_local/other",
            "source": "remote",
            "local_path": "./skills/other",
            "name": "other",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                lock = {"dependencies": [entry | {field: value}]}
                with self.assertRaises(scan_skills.ScanError):
                    scan_skills._assert_manifest_lock_consistent(manifest, lock, "head")

    def test_changed_local_skill_source_is_selected_without_lock_changes(self):
        manifest = {"dependencies": {"apm": [{"path": "./skills/jira-cloud-formatting"}]}}
        lock = {"dependencies": [{
            "repo_url": "_local/jira-cloud-formatting",
            "name": "jira-cloud-formatting",
            "version": "unknown",
            "package_type": "claude_skill",
            "source": "local",
            "local_path": "./skills/jira-cloud-formatting",
        }]}
        manifest_yaml = """dependencies:
  apm:
    - path: ./skills/jira-cloud-formatting
"""
        lock_yaml = """dependencies:
  - repo_url: _local/jira-cloud-formatting
    name: jira-cloud-formatting
    version: unknown
    package_type: claude_skill
    source: local
    local_path: ./skills/jira-cloud-formatting
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "apm.yml").write_text(manifest_yaml, encoding="utf-8")
            (root / "apm.lock.yaml").write_text(lock_yaml, encoding="utf-8")
            with (
                patch.object(scan_skills, "_read_lock_and_manifest", return_value=(manifest, lock)),
                patch.object(
                    scan_skills.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout=f"{COMMIT}\n", stderr=""),
                ),
                patch.object(
                    scan_skills,
                    "_git",
                    return_value=b"skills/jira-cloud-formatting/SKILL.md\0",
                ),
            ):
                plan = scan_skills._make_plan("base", root)

        self.assertEqual(len(plan["dependencies"]), 1)
        selected = plan["dependencies"][0]
        self.assertEqual(selected["name"], "jira-cloud-formatting")
        self.assertEqual(selected["change"], "changed")
        self.assertEqual(selected["repo_url"], "junghoon-vans/nix-config")
        self.assertEqual(selected["resolved_commit"], COMMIT)
        self.assertEqual(selected["resolved_ref"], COMMIT)
        self.assertEqual(selected["virtual_path"], "skills/jira-cloud-formatting")


class DependencyValidationTests(unittest.TestCase):
    def test_valid_github_dependency_and_root_package_are_supported(self):
        scan_skills.validate_dependency(dependency())
        scan_skills.validate_dependency(dependency("root", virtual_path="."))
        root = dependency("root", skill_subset=["root"])
        del root["virtual_path"]
        scan_skills.validate_dependency(root)

    def test_root_skill_selection_must_match_lock(self):
        root = dependency("root", skill_subset=["root"])
        del root["virtual_path"]
        manifest = {"dependencies": {"apm": [{
            "git": "https://github.com/example/skills.git",
            "ref": "v1.2.3",
            "skills": ["root"],
        }]}}
        lock = {"dependencies": [root]}
        scan_skills._assert_manifest_lock_consistent(manifest, lock, "head")
        manifest["dependencies"]["apm"][0]["skills"] = ["different"]
        with self.assertRaises(scan_skills.ScanError):
            scan_skills._assert_manifest_lock_consistent(manifest, lock, "head")

    def test_untrusted_git_sources_are_rejected(self):
        unsafe_entries = (
            dependency(host="github.com.attacker.invalid"),
            dependency(repo_url="https://evil.invalid/example/skills.git"),
            dependency(repo_url="example/../outside"),
            dependency(repo_url="git@github.com:example/skills.git"),
            dependency(materialization_repo_url="attacker.invalid/example/skills"),
        )

        for entry in unsafe_entries:
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError):
                    scan_skills.validate_dependency(entry)

    def test_non_full_or_non_hex_commits_are_rejected(self):
        for commit in ("a" * 39, "a" * 41, "z" * 40, "a" * 40 + " "):
            with self.subTest(commit=commit):
                with self.assertRaises(ValueError):
                    scan_skills.validate_dependency(dependency(resolved_commit=commit))
        scan_skills.validate_dependency(dependency(resolved_commit="A" * 40))

    def test_unsafe_paths_and_git_refs_are_rejected(self):
        unsafe_paths = (
            "/etc/passwd",
            "skills/../../outside",
            "skills\\..\\outside",
            "C:/Windows/system.ini",
            "skills/\x00outside",
        )
        unsafe_refs = ("", "--upload-pack=/tmp/payload", "bad..ref", "refs/heads/..")

        for path in unsafe_paths:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    scan_skills.validate_dependency(dependency(virtual_path=path))

        for ref in unsafe_refs:
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):
                    scan_skills.validate_dependency(dependency(resolved_ref=ref))


class ScanReportValidationTests(unittest.TestCase):
    def test_findings_remain_visible_without_becoming_a_safety_gate(self):
        for severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            with self.subTest(severity=severity):
                report = complete_report(
                    score=100, severity="CRITICAL", recommendation="DO_NOT_INSTALL",
                    issues=[finding(severity)],
                )
                result = scan_skills._report_details(report, 1)
                self.assertEqual(result["scan_status"], "completed")
                self.assertEqual(result["risk"], "CRITICAL (100)")
                self.assertEqual(result["recommendation"], "DO_NOT_INSTALL")
                self.assertEqual(result["finding_count"], 1)
                self.assertEqual(result["high_critical_count"], int(severity in {"HIGH", "CRITICAL"}))
                self.assertTrue(result["review_required"])
                self.assertEqual(result["failures"], [])

    def test_low_score_caution_and_missing_reference_are_incomplete_not_malformed(self):
        report = complete_report(recommendation="CAUTION")
        report["analysis_completeness"].update({
            "is_complete": False,
            "status": "incomplete",
            "ledger_exceptions": [{"reason_code": "reference_missing"}],
        })
        result = scan_skills._report_details(report, 1)
        self.assertEqual(result["scan_status"], "incomplete")
        self.assertEqual(result["coverage"]["percent"], 100)
        self.assertEqual(result["coverage"]["exceptions"], 1)
        self.assertEqual(result["recommendation"], "CAUTION")
        self.assertTrue(result["review_required"])
        self.assertEqual(result["failures"], [])

    def test_coverage_exclusions_and_analyzer_limits_are_reported_separately(self):
        report = complete_report()
        completeness = report["analysis_completeness"]
        completeness["scope_exclusions"] = [{"path": "assets/logo.png", "reason_code": "binary_content"}]
        completeness["analyzer_statuses"][0].update({"status": "degraded", "failed": 1})
        result = scan_skills._report_details(report, 0)
        self.assertEqual(result["scan_status"], "incomplete")
        self.assertEqual(result["finding_count"], 0)
        self.assertEqual(result["coverage"]["exclusions"], 1)
        self.assertEqual(result["coverage"]["analyzer_problems"], ["static_patterns_prompt_injection"])

    def test_partial_coverage_is_not_a_security_finding(self):
        report = complete_report()
        report["analysis_completeness"].update({"is_complete": False, "coverage_percent": 48.3})
        result = scan_skills._report_details(report, 1)
        self.assertEqual(result["scan_status"], "incomplete")
        self.assertEqual(result["high_critical_count"], 0)
        self.assertEqual(result["coverage"]["percent"], 48.3)

    def test_complete_report_is_not_labelled_a_safety_approval(self):
        result = scan_skills._report_details(complete_report(), 0)
        self.assertEqual(result["scan_status"], "completed")
        self.assertFalse(result["review_required"])
        self.assertTrue(result["coverage"]["complete"])

    def test_scanner_errors_and_unexplained_exits_stay_errors(self):
        for returncode in (1, 2, -9):
            with self.subTest(returncode=returncode):
                result = scan_skills._report_details(complete_report(), returncode)
                self.assertEqual(result["scan_status"], "error")
                self.assertTrue(result["review_required"])
                self.assertTrue(result["failures"])
        report = complete_report()
        report["execution_successful"] = False
        self.assertEqual(scan_skills._report_details(report, 0)["scan_status"], "error")

    def test_malformed_reports_and_llm_mode_mismatch_are_errors(self):
        malformed = (
            {},
            complete_report(score="0"),
            complete_report(issues=[finding("UNKNOWN")]),
            complete_report() | {"issues": {}},
            complete_report() | {"metadata": {"llm_requested": True}},
            complete_report() | {"metadata": {"llm_requested": "false"}},
            complete_report() | {"analysis_completeness": {}},
        )
        for report in malformed:
            with self.subTest(report=report):
                self.assertEqual(scan_skills._report_details(report, 0)["scan_status"], "error")


class SkillStagingTests(unittest.TestCase):
    def test_self_contained_reference_survives_without_source_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "checkout"
            skill = source / "plugins/worktrunk/skills/worktrunk"
            reference = skill / "reference/README.md"
            reference.parent.mkdir(parents=True)
            (skill / "SKILL.md").write_text("Read reference/README.md\n")
            reference.write_text("# Worktrunk reference\n")
            staged = scan_skills._stage_target(source, skill, root / "staged")
            reference.unlink()
            self.assertEqual((staged / "SKILL.md").read_text(), "Read reference/README.md\n")
            self.assertEqual((staged / "reference/README.md").read_text(), "# Worktrunk reference\n")
            self.assertFalse((staged / "reference/README.md").is_symlink())

    def test_reference_symlinks_cannot_escape_staged_skill(self):
        cases = (
            ("../../../README.md", False),
            ("../../../README.md", True),
            ("../../../../outside.md", False),
            ("../../../.git/config", False),
            ("README.md", False),
            ("/etc/passwd", False),
        )
        for link, root_readme in cases:
            with self.subTest(link=link, root_readme=root_readme):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / "checkout"
                    skill = source / "skills/worktrunk"
                    reference = skill / "reference/README.md"
                    reference.parent.mkdir(parents=True)
                    (skill / "SKILL.md").write_text("Read reference/README.md\n")
                    (root / "outside.md").write_text("Not part of the repository\n")
                    (source / ".git").mkdir()
                    (source / ".git/config").write_text("Not skill content\n")
                    if root_readme:
                        (source / "README.md").write_text("Repository documentation\n")
                    reference.symlink_to(link)
                    destination = root / "staged"
                    with self.assertRaises(scan_skills.ScanError):
                        scan_skills._stage_target(source, skill, destination)
                    self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
