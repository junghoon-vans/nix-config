import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("update_homebrew", Path(__file__).with_name("update-homebrew.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

LOCK = json.loads((Path(__file__).resolve().parents[2] / "flake.lock").read_text())


def lock(rev, brew_version=LOCK["nodes"]["brew-src"]["original"]["ref"]):
    return {"nodes": {
        "brew-src": {"original": {"ref": brew_version}},
        **{
            tap: {"locked": {"owner": "homebrew", "repo": tap, "rev": rev}}
            for tap in updater.TAPS
        },
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
        home = Path(temporary.name) / "home"
        cache = Path(temporary.name) / "cache"
        home.mkdir()
        cache.mkdir()
        homebrew_env = patch.dict(os.environ, {
            "HOME": str(home),
            "HOMEBREW_CACHE": str(cache),
            "HOMEBREW_NO_AUTO_UPDATE": "1",
            "HOMEBREW_NO_INSTALL_FROM_API": "1",
        })
        homebrew_env.start()
        self.addCleanup(homebrew_env.stop)
        self.brew = os.environ.get("HOMEBREW_TEST_BREW", "brew")
        for root in (self.old, self.new):
            for tap, subdir in updater.TAPS.items():
                (root / tap / subdir / "e").mkdir(parents=True)
        self.declared = {tap: ["example"] for tap in updater.TAPS}

    def definition(self, root, tap, text, name="example"):
        (root / tap / updater.TAPS[tap] / "e" / f"{name}.rb").write_text(text)

    def summary(self, before="old", after="new"):
        with patch.object(
            updater,
            "prefetch",
            side_effect=lambda node: (self.old if node["rev"] == "old" else self.new) / node["repo"],
        ):
            return updater.summarize(lock(before), lock(after), self.declared, self.brew)

    def test_declared_versions_use_formula_url_revision_and_apple_silicon_cask(self):
        self.definition(self.old, "homebrew-core", formula("1.2.0", 1))
        self.definition(self.new, "homebrew-core", formula("1.3.0", 2))
        self.definition(self.old, "homebrew-cask", cask("2.0.0"))
        self.definition(self.new, "homebrew-cask", cask("2.1.0"))
        body = self.summary()
        self.assertIn("| `example` | `1.2.0_1` | `1.3.0_2` | Version / revision |", body)
        self.assertIn("| `example` | `2.0.0` | `2.1.0` | Version / revision |", body)
        self.assertNotIn("9.9.9", body)

    def test_cask_zap_not_required_parses_with_selected_runtime(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-cask"] = ["example"]
        candidate = cask("2.1.0").replace(
            '  app "Example.app"\n',
            '  app "Example.app"\n  zap :not_required\n',
        )
        self.definition(self.new, "homebrew-cask", candidate)
        self.assertIn("| `example` | — | `2.1.0` | Added |", self.summary())

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

    def test_unchanged_incompatible_declared_definition_is_rejected(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        incompatible = formula("1.0").replace(
            "  revision 0\n",
            "  revision 0\n  future_homebrew_dsl :unsupported\n",
        )
        self.definition(self.old, "homebrew-core", incompatible)
        self.definition(self.new, "homebrew-core", incompatible)
        for before, after in (("old", "new"), ("same", "same")):
            with self.subTest(before=before, after=after):
                with self.assertRaisesRegex(RuntimeError, "update the brew-src pin"):
                    self.summary(before, after)

    def test_unrelated_incompatible_definition_is_ignored(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.definition(self.new, "homebrew-core", formula("1.0"))
        self.definition(
            self.new,
            "homebrew-core",
            "class Unrelated < Formula\n  future_homebrew_dsl :unsupported\nend\n",
            "unrelated",
        )
        self.assertIn("No declared package changes.", self.summary())

    def test_built_runtime_reports_locked_release_exactly(self):
        self.assertEqual(
            updater.verify_brew_version(self.brew, LOCK),
            LOCK["nodes"]["brew-src"]["original"]["ref"],
        )

    def test_runtime_version_must_match_brew_src_pin_exactly(self):
        with patch.object(
            updater.subprocess,
            "run",
            return_value=Mock(stdout="Homebrew 0.0.0\n"),
        ):
            with self.assertRaisesRegex(RuntimeError, "brew-src pin"):
                updater.verify_brew_version(self.brew, lock("old"))

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
