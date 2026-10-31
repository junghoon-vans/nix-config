from contextlib import chdir
import html
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("update_homebrew", Path(__file__).with_name("update-homebrew.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

OLD_REVISION = "a" * 40
NEW_REVISION = "b" * 40
LOCK = json.loads((Path(__file__).resolve().parents[2] / "flake.lock").read_text())


def table_entries(body):
    return [
        tuple(html.unescape(value.strip()) for value in line.strip("|").split("|"))[:4]
        for line in body.splitlines() if line.startswith("|")
    ]


def lock(rev, brew_version=LOCK["nodes"]["brew-src"]["original"]["ref"]):
    return {"nodes": {
        "brew-src": {"original": {"ref": brew_version}},
        **{
            tap: {"locked": {"owner": "homebrew", "repo": tap, "rev": rev}}
            for tap in updater.TAPS
        },
    }}


def formula(version, revision=0, description="Example", class_name="Example"):
    return f'''class {class_name} < Formula
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

    def run_main(self, before_lock, after_lock):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_file = root / "flake.lock"
            body_file = root / "body.md"
            changes_file = root / "homebrew-changes.json"
            lock_file.write_text(json.dumps(before_lock))

            def update_taps(*_args, **_kwargs):
                lock_file.write_text(json.dumps(after_lock))

            with (
                chdir(root),
                patch.object(updater, "verify_brew_version"),
                patch.object(updater, "inventory", return_value=self.declared),
                patch.object(
                    updater,
                    "prefetch",
                    side_effect=lambda node: (
                        self.old if node["rev"] == "old" else self.new
                    ) / node["repo"],
                ),
                patch.object(
                    updater,
                    "versions",
                    side_effect=lambda _tap, paths, _brew: {
                        name: "1.0" for name in paths
                    },
                ),
                patch.object(updater.subprocess, "run", side_effect=update_taps),
                patch.object(
                    sys,
                    "argv",
                    [
                        "update-homebrew.py",
                        "--body-file",
                        str(body_file),
                        "--changes-file",
                        str(changes_file),
                    ],
                ),
            ):
                updater.main()

            return (
                json.loads(lock_file.read_text()),
                json.loads(changes_file.read_text()),
                body_file.read_text(),
            )

    def analyze(self, before="old", after="new"):
        old_lock = lock(before)
        new_lock = lock(after)
        with patch.object(
            updater,
            "prefetch",
            side_effect=lambda node: (
                self.old if node["rev"] in ("old", OLD_REVISION) else self.new
            ) / node["repo"],
        ):
            body, changes = updater.analyze(old_lock, new_lock, self.declared, self.brew)
        return old_lock, new_lock, body, changes

    def summary(self, before="old", after="new"):
        return self.analyze(before, after)[2]
    def test_declared_versions_use_formula_url_revision_and_apple_silicon_cask(self):
        self.definition(self.old, "homebrew-core", formula("1.2.0", 1))
        self.definition(self.new, "homebrew-core", formula("1.3.0", 2))
        self.definition(self.old, "homebrew-cask", cask("2.0.0"))
        self.definition(self.new, "homebrew-cask", cask("2.1.0"))
        body = self.summary()
        entries = table_entries(body)
        self.assertIn(("example", "1.2.0_1", "1.3.0_2", "Version / revision"), entries)
        self.assertIn(("example", "2.0.0", "2.1.0", "Version / revision"), entries)
        self.assertNotIn("9.9.9", body)

    def test_cask_zap_not_required_parses_with_selected_runtime(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-cask"] = ["example"]
        candidate = cask("2.1.0").replace(
            '  app "Example.app"\n',
            '  app "Example.app"\n  zap :not_required\n',
        )
        self.definition(self.new, "homebrew-cask", candidate)
        self.assertIn("example | Not present / metadata unavailable | 2.1.0 | Added", self.summary())

    def test_revision_only_and_definition_only_changes_are_distinguished(self):
        for tap in updater.TAPS:
            self.declared[tap] = []
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0", 1))
        self.definition(self.new, "homebrew-core", formula("1.0", 2))
        self.assertIn(("example", "1.0_1", "1.0_2", "Version / revision"), table_entries(self.summary()))
        changed_url = formula("1.0", 1).replace(
            "https://example.com/example-1.0.tar.gz",
            "https://downloads.example.com/example-1.0.tar.gz",
        )
        self.definition(self.new, "homebrew-core", changed_url)
        self.assertIn(("example", "1.0_1", "1.0_1", "Definition only (version unchanged)"), table_entries(self.summary()))

    def test_descriptive_metadata_and_comments_do_not_advance_tap_pins(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0"))
        candidate = formula("1.0", description="Updated description").replace(
            '  homepage "https://example.com"',
            '  homepage "https://new.example.com"',
        )
        self.definition(self.new, "homebrew-core", "# Updated: 2026-10-31\n" + candidate)

        old_lock, new_lock, body, changes = self.analyze()

        self.assertEqual(old_lock["nodes"], new_lock["nodes"])
        self.assertEqual(changes, [])
        self.assertIn(("example", "1.0", "1.0", "Unchanged"), table_entries(body))

    def test_multiline_recipe_content_is_not_stripped_as_metadata_or_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "formula.rb"
            for opening, closing in (("<<~EOS", "EOS"), ("%q{", "}"), ('"', '"')):
                with self.subTest(opening=opening):
                    source = f'def install\n  text = {opening}\n# old payload\n  desc "data"\n{closing}\nend\n'
                    path.write_text(source)
                    before = updater.normalized_recipe(path)
                    path.write_text(source.replace("# old payload", "# new payload"))
                    self.assertNotEqual(before, updater.normalized_recipe(path))

    def test_formula_alias_dependency_ignores_unrelated_changes_but_retains_rebuilds(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        for root in (self.old, self.new):
            source = root / "homebrew-core"
            self.definition(root, "homebrew-core", formula("1.0").replace(
                "  revision 0", '  revision 0\n  depends_on "pkg-config"'))
            self.definition(root, "homebrew-core", formula("1.0", class_name="Pkgconf"), "pkgconf")
            (source / "Aliases").mkdir()
            (source / "Aliases/pkg-config").symlink_to("../Formula/e/pkgconf.rb")
        self.definition(self.new, "homebrew-core", formula("2.0", class_name="Other"), "other")
        before, after, _body, changes = self.analyze()
        self.assertEqual(changes, [])
        self.assertEqual(before, after)
        self.definition(self.new, "homebrew-core", formula("1.0", 1, class_name="Pkgconf"), "pkgconf")
        before, after, _body, changes = self.analyze()
        self.assertEqual([item["dependency"] for item in changes], ["example"])
        self.assertNotEqual(before, after)

    def test_system_version_constraints_are_not_unresolved_formula_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "formula.rb"
            path.write_text('  depends_on xcode: ["12.5", :build]\n  depends_on macos: ">= :ventura"\n')
            self.assertEqual(updater.dependency_references(path), (set(), False))


    def test_homepage_change_is_relevant_when_formula_uses_it(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        template = formula("1.0").replace(
            'url "https://example.com/example-1.0.tar.gz"',
            'url "#{homepage}/example-1.0.tar.gz"',
        )
        self.definition(self.old, "homebrew-core", template)
        self.definition(
            self.new,
            "homebrew-core",
            template.replace(
                'homepage "https://example.com"',
                'homepage "https://new.example.com"',
            ),
        )

        with patch.object(
            updater,
            "versions",
            side_effect=lambda _tap, paths, _brew: {
                name: "1.0" for name in paths
            },
        ):
            old_lock, new_lock, _body, changes = self.analyze()

        self.assertNotEqual(
            old_lock["nodes"]["homebrew-core"],
            new_lock["nodes"]["homebrew-core"],
        )
        self.assertEqual([row["dependency"] for row in changes], ["example"])

    def test_same_version_bottle_change_is_a_declared_package_change(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(
            self.old,
            "homebrew-core",
            formula("1.0").replace(
                "end\n",
                f'  bottle do\n    sha256 cellar: :any_skip_relocation, arm64_sonoma: "{"c" * 64}"\n  end\nend\n',
            ),
        )
        self.definition(
            self.new,
            "homebrew-core",
            formula("1.0").replace(
                "end\n",
                f'  bottle do\n    sha256 cellar: :any_skip_relocation, arm64_sonoma: "{"d" * 64}"\n  end\nend\n',
            ),
        )
        old_lock, new_lock, body, changes = self.analyze()

        self.assertNotEqual(
            old_lock["nodes"]["homebrew-core"],
            new_lock["nodes"]["homebrew-core"],
        )
        self.assertEqual([row["dependency"] for row in changes], ["example"])
        self.assertIn(
            ("example", "1.0", "1.0", "Definition only (version unchanged)"),
            table_entries(body),
        )

    def test_transitive_formula_change_reports_only_affected_declared_packages(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example", "unrelated"]
        self.definition(
            self.old,
            "homebrew-core",
            formula("1.0").replace("  revision 0", '  revision 0\n  depends_on "libfoo"'),
        )
        self.definition(
            self.new,
            "homebrew-core",
            formula("1.0").replace("  revision 0", '  revision 0\n  depends_on "libfoo"'),
        )
        self.definition(self.old, "homebrew-core", formula("1.0", class_name="Libfoo"), "libfoo")
        self.definition(
            self.new,
            "homebrew-core",
            formula("1.0", class_name="Libfoo").replace(
                '"' + "a" * 64 + '"',
                '"' + "b" * 64 + '"',
            ),
            "libfoo",
        )
        for root in (self.old, self.new):
            self.definition(root, "homebrew-core", formula("2.0", class_name="Unrelated"), "unrelated")

        old_lock, new_lock, body, changes = self.analyze()

        self.assertNotEqual(
            old_lock["nodes"]["homebrew-core"],
            new_lock["nodes"]["homebrew-core"],
        )
        self.assertEqual([row["dependency"] for row in changes], ["example"])
        self.assertIn(("example", "1.0", "1.0", "Dependency / helper updated"), table_entries(body))
        self.assertIn(("unrelated", "2.0", "2.0", "Unchanged"), table_entries(body))

    def test_cross_tap_transitive_change_retains_only_dependency_tap(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        dependency = '  revision 0\n  depends_on "hashicorp/tap/libfoo"'
        self.definition(
            self.old,
            "homebrew-core",
            formula("1.0").replace("  revision 0", dependency),
        )
        self.definition(
            self.new,
            "homebrew-core",
            formula("1.0").replace("  revision 0", dependency),
        )
        self.definition(
            self.old,
            "hashicorp-tap",
            formula("1.0", class_name="Libfoo"),
            "libfoo",
        )
        self.definition(
            self.new,
            "hashicorp-tap",
            formula("1.0", class_name="Libfoo").replace(
                '"' + "a" * 64 + '"',
                '"' + "b" * 64 + '"',
            ),
            "libfoo",
        )

        old_lock, new_lock, _body, changes = self.analyze()

        self.assertEqual(
            old_lock["nodes"]["homebrew-core"],
            new_lock["nodes"]["homebrew-core"],
        )
        self.assertNotEqual(
            old_lock["nodes"]["hashicorp-tap"],
            new_lock["nodes"]["hashicorp-tap"],
        )
        self.assertEqual([row["dependency"] for row in changes], ["example"])

    def test_unresolved_dynamic_dependency_refuses_speculative_update(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        dynamic = formula("1.0").replace(
            "  revision 0",
            "  revision 0\n  depends_on dependency_name",
        )
        self.definition(self.old, "homebrew-core", dynamic)
        self.definition(self.new, "homebrew-core", dynamic)
        self.definition(
            self.old,
            "hashicorp-tap",
            formula("1.0", class_name="Libfoo"),
            "libfoo",
        )
        self.definition(
            self.new,
            "hashicorp-tap",
            formula("1.0", class_name="Libfoo").replace(
                '"' + "a" * 64 + '"',
                '"' + "b" * 64 + '"',
            ),
            "libfoo",
        )

        with patch.object(
            updater,
            "versions",
            side_effect=lambda _tap, paths, _brew: {
                name: "1.0" for name in paths
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "refusing a speculative update PR"):
                self.analyze()

    def test_shared_tap_ruby_helper_change_marks_declared_packages(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.definition(self.new, "homebrew-core", formula("1.0"))
        for root, value in ((self.old, "old"), (self.new, "new")):
            helper = root / "homebrew-core/lib/shared.rb"
            helper.parent.mkdir(parents=True)
            helper.write_text(f'SHARED_BUILD_VALUE = "{value}"\n')

        old_lock, new_lock, body, changes = self.analyze()

        self.assertNotEqual(
            old_lock["nodes"]["homebrew-core"],
            new_lock["nodes"]["homebrew-core"],
        )
        self.assertEqual([row["dependency"] for row in changes], ["example"])
        self.assertIn(("example", "1.0", "1.0", "Dependency / helper updated"), table_entries(body))

    def test_missing_declared_package_in_both_revisions_does_not_retain_tap_changes(self):
        self.declared = {tap: ["missing"] for tap in updater.TAPS}

        old_lock, new_lock, _body, changes = self.analyze()

        self.assertEqual(old_lock["nodes"], new_lock["nodes"])
        self.assertEqual(changes, [])

    def test_declared_additions_removals_and_unchanged_packages(self):
        self.declared["homebrew-cask"] = []
        self.declared["hashicorp-tap"] = []
        self.definition(self.new, "homebrew-core", formula("1.0"))
        self.assertIn("example | Not present / metadata unavailable | 1.0 | Added", self.summary())
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.assertIn("example | 1.0 | 1.0 | Unchanged", self.summary())
        (self.new / "homebrew-core/Formula/e/example.rb").unlink()
        self.assertIn("example | 1.0 | Not present / metadata unavailable | Removed", self.summary())

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
        self.assertIn("example | 1.0 | 1.0 | Unchanged", self.summary())

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
            "example | Not present / metadata unavailable | Not present / metadata unavailable "
            "| Unavailable in both pinned taps",
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
        self.assertIn("example | 1.15.0 | 1.16.0 | Version / revision", body)
        self.assertNotIn("0.15.0", body)

    def test_grouped_tap_rows_show_full_revisions_and_unchanged_components(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.definition(self.new, "homebrew-core", formula("1.1"))
        before = lock(OLD_REVISION)
        after = lock(OLD_REVISION)
        after["nodes"]["homebrew-core"]["locked"]["rev"] = NEW_REVISION
        with (
            patch.object(
                updater,
                "prefetch",
                side_effect=lambda node: (
                    self.old if node["rev"] == OLD_REVISION else self.new
                ) / node["repo"],
            ),
            patch.object(
                updater,
                "versions",
                side_effect=lambda _tap, paths, _brew: {
                    name: "1.0" for name in paths
                },
            ),
        ):
            body = updater.summarize(before, after, self.declared, self.brew)

        self.assertIn(
            f"| homebrew-core tap | revision {OLD_REVISION} | revision {NEW_REVISION} "
            f"| Updated | [Compare](https://github.com/homebrew/homebrew-core/compare/"
            f"{OLD_REVISION}...{NEW_REVISION}) |",
            body,
        )
        for tap in ("homebrew-cask", "hashicorp-tap"):
            self.assertIn(
                f"| {tap} tap | revision {OLD_REVISION} | revision {OLD_REVISION} "
                "| Unchanged |",
                body,
            )
        self.assertEqual(body.count("| Dependency |"), len(updater.TAPS))

    def test_main_restores_unrelated_taps_and_writes_empty_changes_file(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.definition(self.new, "homebrew-core", formula("1.0"))

        final_lock, changes, body = self.run_main(lock("old"), lock("new"))

        self.assertEqual(final_lock["nodes"], lock("old")["nodes"])
        self.assertEqual(changes, [])
        self.assertIn("| homebrew-core tap | revision old | revision old | Unchanged |", body)

    def test_main_keeps_same_version_recipe_change_and_reports_package(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        self.declared["homebrew-core"] = ["example"]
        self.definition(self.old, "homebrew-core", formula("1.0"))
        self.definition(
            self.new,
            "homebrew-core",
            formula("1.0").replace(
                '"' + "a" * 64 + '"',
                '"' + "b" * 64 + '"',
            ),
        )

        final_lock, changes, _body = self.run_main(lock("old"), lock("new"))

        self.assertEqual(
            final_lock["nodes"]["homebrew-core"],
            lock("new")["nodes"]["homebrew-core"],
        )
        self.assertEqual([row["dependency"] for row in changes], ["example"])

    def test_declared_package_names_are_escaped_in_shared_table(self):
        self.declared = {tap: [] for tap in updater.TAPS}
        package = "special|`[name]_*"
        self.declared["homebrew-core"] = [package]
        self.definition(self.old, "homebrew-core", formula("1.0"), package)
        self.definition(self.new, "homebrew-core", formula("1.0"), package)
        with patch.object(
            updater,
            "versions",
            side_effect=lambda tap, paths, brew: {
                name: "1.0" for name in paths
            },
        ):
            body = self.summary()

        self.assertIn("special&#124;&#96;&#91;name&#93;&#95;&#42; | 1.0 | 1.0 | Unchanged", body)
        self.assertNotIn(package + " |", body)





if __name__ == "__main__":
    unittest.main()
