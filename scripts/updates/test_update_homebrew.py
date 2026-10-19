import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("update_homebrew", Path(__file__).with_name("update-homebrew.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def lock(rev):
    return {"nodes": {
        tap: {"locked": {"owner": "homebrew", "repo": tap, "rev": rev}}
        for tap in updater.TAPS
    }}


class HomebrewSummaryTests(unittest.TestCase):
    def test_reports_definition_changes_additions_and_removals_not_directory_moves(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old"
            new = Path(directory) / "new"
            for root in (old, new):
                for subdir in updater.TAPS.values():
                    (root / subdir / "a").mkdir(parents=True)
            for subdir in updater.TAPS.values():
                (old / subdir / "a" / "changed.rb").write_text('version "1.0"\nrevision 1\n')
                (new / subdir / "a" / "changed.rb").write_text('version "1.0"\nrevision 2\n')
                (old / subdir / "a" / "removed.rb").write_text("removed")
                (new / subdir / "a" / "added.rb").write_text("added")
                (old / subdir / "a" / "moved.rb").write_text("same definition")
                (new / subdir / "moved.rb").write_text("same definition")
                (new / subdir / "README.md").write_text("not a package")
            with patch.object(updater, "prefetch", side_effect=lambda node: old if node["rev"] == "old" else new):
                body = updater.summarize(lock("old"), lock("new"))
            for tap in updater.TAPS:
                self.assertIn(f"https://github.com/homebrew/{tap}/compare/old...new", body)
            self.assertEqual(body.count("**Changed (1)**: `changed`"), 2)
            self.assertEqual(body.count("**Added (1)**: `added`"), 2)
            self.assertEqual(body.count("**Removed (1)**: `removed`"), 2)
            self.assertNotIn("`moved`", body)
            self.assertNotIn("`README`", body)

    def test_unchanged_taps_report_no_changes_without_fetching(self):
        with patch.object(updater, "prefetch", side_effect=AssertionError("unchanged tap fetched")):
            body = updater.summarize(lock("same"), lock("same"))
        self.assertEqual(body.count("No changes."), 2)
        self.assertNotIn("**Changed", body)


if __name__ == "__main__":
    unittest.main()
