import importlib.util
from pathlib import Path
import unittest


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
    def failures(self, report, returncode=0):
        return scan_skills.validate_scan_report(report, returncode)

    def test_complete_static_safe_and_caution_reports_pass(self):
        self.assertEqual(self.failures(complete_report()), [])

        caution = complete_report(
            score=50,
            severity="MEDIUM",
            recommendation="CAUTION",
            issues=[finding("LOW"), finding("MEDIUM")],
        )
        self.assertEqual(self.failures(caution), [])

    def test_high_and_critical_findings_fail_even_if_overall_score_looks_safe(self):
        for severity in ("HIGH", "CRITICAL"):
            with self.subTest(severity=severity):
                report = complete_report(issues=[finding(severity)])
                self.assertTrue(self.failures(report))

    def test_high_critical_and_do_not_install_assessments_fail(self):
        assessments = (
            ("HIGH", "DO_NOT_INSTALL", 51),
            ("CRITICAL", "DO_NOT_INSTALL", 100),
            ("HIGH", "SAFE", 0),
            ("CRITICAL", "CAUTION", 50),
            ("LOW", "DO_NOT_INSTALL", 0),
            ("MEDIUM", "CAUTION", 51),
        )
        for severity, recommendation, score in assessments:
            with self.subTest(severity=severity, recommendation=recommendation):
                report = complete_report(score, severity, recommendation)
                self.assertTrue(self.failures(report))

    def test_static_mode_and_scanner_exit_status_are_enforced(self):
        llm_report = complete_report()
        llm_report["metadata"]["llm_requested"] = True
        self.assertTrue(self.failures(llm_report))

        missing_mode = complete_report()
        del missing_mode["metadata"]["llm_requested"]
        self.assertTrue(self.failures(missing_mode))

        wrong_mode_type = complete_report()
        wrong_mode_type["metadata"]["llm_requested"] = "false"
        self.assertTrue(self.failures(wrong_mode_type))

        # Exit status 1 cannot be discarded just because the JSON says SAFE.
        self.assertTrue(self.failures(complete_report(), returncode=1))
        self.assertTrue(self.failures(complete_report(), returncode=2))

    def test_incomplete_or_failed_execution_is_rejected(self):
        incomplete = complete_report()
        completeness = incomplete["analysis_completeness"]
        completeness.update(
            {
                "scanned_components": 0,
                "coverage_percent": 0.0,
                "is_complete": False,
                "status": "incomplete",
                "partially_inspected_files": 1,
                "entirely_uninspected_files": 1,
            }
        )
        self.assertTrue(self.failures(incomplete))

        failed = complete_report()
        failed["execution_successful"] = False
        failed["analysis_completeness"]["execution_successful"] = False
        self.assertTrue(self.failures(failed, returncode=2))

        skipped_work = complete_report()
        status = skipped_work["analysis_completeness"]["analyzer_statuses"][0]
        status.update({"planned_work": 2, "completed": 1, "skipped": 1})
        self.assertTrue(self.failures(skipped_work))

    def test_malformed_or_internally_inconsistent_reports_fail_closed(self):
        malformed_reports = (
            {},
            {"risk_assessment": {}, "issues": [], "metadata": {"llm_requested": False}},
            complete_report() | {"execution_successful": "true"},
            complete_report() | {"components": []},
            complete_report() | {"issues": {}},
            complete_report(issues=[{"severity": "LOW"}]),
            complete_report(issues=[finding("BLOCKER")]),
            complete_report(score="0"),
        )
        for report in malformed_reports:
            with self.subTest(report=report):
                self.assertTrue(self.failures(report))

        missing_skill = complete_report()
        del missing_skill["skill"]
        self.assertTrue(self.failures(missing_skill))

        wrong_version = complete_report()
        wrong_version["metadata"]["skillspector_version"] = "2.11.0"
        self.assertTrue(self.failures(wrong_version))

        malformed_component = complete_report()
        del malformed_component["components"][0]["type"]
        self.assertTrue(self.failures(malformed_component))

        for line in (-1, "1", True):
            with self.subTest(start_line=line):
                malformed_location = complete_report(issues=[finding("LOW")])
                malformed_location["issues"][0]["location"]["start_line"] = line
                self.assertTrue(self.failures(malformed_location))

        no_analyzers = complete_report()
        no_analyzers["analysis_completeness"]["analyzer_statuses"] = []
        self.assertTrue(self.failures(no_analyzers))

        malformed_analyzer = complete_report()
        del malformed_analyzer["analysis_completeness"]["analyzer_statuses"][0]["completed"]
        self.assertTrue(self.failures(malformed_analyzer))

        inconsistent = complete_report()
        inconsistent["analysis_completeness"]["coverage_percent"] = 99.0
        self.assertTrue(self.failures(inconsistent))


if __name__ == "__main__":
    unittest.main()
