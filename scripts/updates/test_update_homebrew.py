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


def formula(version, revision=0, description="Example"):
    return f'''class Example < Formula
  desc "{description}"
  homepage "https://example.com"
  url "https://example.com/example-{version}.tar.gz"
  sha256 "{'a' * 64}"
  revision {revision}
end
'''


def cask(version):
    return f'''cask "example" do
  on_arm do
    version "{version}"
    sha256 "{'b' * 64}"
  end
  on_intel do
    version "9.9.9"
    sha256 "{'c' * 64}"
  end
  url "https://example.com/example-#{{version}}.dmg"
  name "Example"
  homepage "https://example.com"
  app "Example.app"
end
'''


class HomebrewSummaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.old = Path(temporary.name) / "old"
        self.new = Path(temporary.name) / "new"
        for root in (self.old, self.new):
            for tap, subdir in updater.TAPS.items():
                (root / tap / subdir / "e").mkdir(parents=True)
        self.declared = {tap: ["example"] for tap in updater.TAPS}

    def definition(self, root, tap, text, name="example"):
        (root / tap / updater.TAPS[tap] / "e" / f"{name}.rb").write_text(text)

    def summary(self):
        with patch.object(updater, "prefetch", side_effect=lambda node: (self.old if node["rev"] == "old" else self.new) / node["repo"]):
            return updater.summarize(lock("old"), lock("new"), self.declared)

    def test_declared_versions_use_formula_url_revision_and_apple_silicon_cask(self):
        self.definition(self.old, "homebrew-core", formula("1.2.0", 1))
        self.definition(self.new, "homebrew-core", formula("1.3.0", 2))
        self.definition(self.old, "homebrew-cask", cask("2.0.0"))
        self.definition(self.new, "homebrew-cask", cask("2.1.0"))
        self.definition(self.new, "homebrew-core", "invalid Ruby", "unrelated")
        body = self.summary()
        self.assertIn("| `example` | `1.2.0_1` | `1.3.0_2` | Version / revision |", body)
        self.assertIn("| `example` | `2.0.0` | `2.1.0` | Version / revision |", body)
        self.assertNotIn("unrelated", body)
        self.assertNotIn("9.9.9", body)

    def test_revision_only_and_definition_only_changes_are_distinguished(self):
        for tap in updater.TAPS:
            self.declared[tap] = []
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0", 1))
        self.definition(self.new, "homebrew-core", formula("1.0", 2))
        self.assertIn("| `example` | `1.0_1` | `1.0_2` | Version / revision |", self.summary())
        self.definition(self.new, "homebrew-core", formula("1.0", 1, "New description"))
        self.assertIn("| `example` | `1.0_1` | `1.0_1` | Definition only (version unchanged) |", self.summary())

    def test_declared_additions_removals_and_unchanged_packages(self):
        self.declared["homebrew-cask"] = []
        self.declared["hashicorp-tap"] = []
        self.definition(self.new, "homebrew-core", formula("1.0"))
        self.assertIn("| `example` | — | `1.0` | Added |", self.summary())
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.assertNotIn("| `example`", self.summary())
        (self.new / "homebrew-core/Formula/e/example.rb").unlink()
        self.assertIn("| `example` | `1.0` | — | Removed |", self.summary())

    def test_unchanged_taps_do_not_fetch(self):
        with patch.object(updater, "prefetch", side_effect=AssertionError("unchanged tap fetched")):
            body = updater.summarize(lock("same"), lock("same"), self.declared)
        self.assertNotIn("| `example`", body)

    def test_declaration_missing_from_both_pins_is_not_reported_as_added(self):
        self.declared["homebrew-cask"] = []
        self.assertIn(
            "| `example` | — | — | Unavailable in both pinned taps |",
            self.summary(),
        )

    def test_hashicorp_formula_versions_are_reported_separately_from_core(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["hashicorp-tap"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("0.15.0"))
        self.definition(self.new, "homebrew-core", formula("0.15.1"))
        for root, version in ((self.old, "1.15.0"), (self.new, "1.16.0")):
            directory = root / "hashicorp-tap/Formula"
            (directory / "example.rb").write_text(formula(version))
        body = self.summary()
        self.assertIn("### hashicorp-tap", body)
        self.assertIn("| `example` | `1.15.0` | `1.16.0` | Version / revision |", body)
        self.assertNotIn("`0.15.0`", body)



if __name__ == "__main__":
    unittest.main()
