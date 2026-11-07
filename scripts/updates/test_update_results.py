import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPORTER = Path(__file__).resolve().with_name("report-update-results.py")


class UpdateResultsTests(unittest.TestCase):
    def report(self, results):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            env = dict(os.environ, UPDATER_RESULTS=json.dumps(results), GITHUB_STEP_SUMMARY=str(summary))
            result = subprocess.run(
                [sys.executable, "-B", str(REPORTER)], env=env,
                text=True, capture_output=True, timeout=10,
            )
            return result, summary.read_text()

    def test_every_success_is_reported_without_failing(self):
        result, summary = self.report({"hermes": {"result": "success"}, "gno": {"result": "success"}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| hermes | success |", summary)
        self.assertIn("| gno | success |", summary)

    def test_failed_cancelled_or_skipped_updater_does_not_hide_successful_peers(self):
        for outcome in ("failure", "cancelled", "skipped"):
            with self.subTest(outcome=outcome):
                result, summary = self.report({
                    "hermes": {"result": outcome},
                    "homebrew": {"result": "success"},
                    "fixed-releases": {"result": "success"},
                })
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"| hermes | {outcome} |", summary)
                self.assertIn("| homebrew | success |", summary)
                self.assertIn("| fixed-releases | success |", summary)

    def test_empty_outcomes_fail_closed(self):
        result, _ = self.report({})
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
