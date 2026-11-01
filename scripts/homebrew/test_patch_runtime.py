import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("stdenv"), "requires nix develop for real substituteInPlace")
class HomebrewRuntimePatch(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="homebrew-patch-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.out = self.root / "patched"
        # Minimal executable slices of the pinned upstream entry points. Both
        # update loops must retain taps while excluding the immutable repository.
        self.files = {
            "Library/Homebrew/cmd/update.sh": '''for DIR in "${HOMEBREW_REPOSITORY}" "${HOMEBREW_LIBRARY}"/Taps/*/*
do
  printf '%s\\n' "$DIR"
done
''' * 2,
            "Library/Homebrew/utils/ruby.sh": 'setup-ruby-path() { export HOMEBREW_RUBY_PATH=/upstream/ruby; }\n',
            "Library/Homebrew/vendor/bundle/bundler/setup.rb": "# upstream bundle setup\n",
            "Library/Homebrew/brew.sh": 'set-homebrew-version-from-git\nprintf \'%s\\n\' "$HOMEBREW_VERSION"\n',
            "bin/brew": '''#!/usr/bin/env bash
# Copy and export all HOMEBREW_* variables previously mentioned in
# manpage or used elsewhere by Homebrew.
printf '%s\\n' "${HOMEBREW_NO_AUTO_UPDATE-unset}"
''',
        }
        for name, content in self.files.items():
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    def patch(self):
        return subprocess.run(
            ["bash", "-c", 'source "$stdenv/setup"; source "$@"', "patch-test",
             str(ROOT / "scripts/homebrew/patch-runtime.sh"), str(self.source), str(self.out),
             "test-version", "/nix/ruby/bin/ruby", "/nix/fiddle", "lib/ruby/gems/test", "test-fiddle"],
            cwd=self.root, env={**os.environ, "NIX_BUILD_TOP": str(self.root)},
            capture_output=True, text=True, check=False,
        )

    def test_missing_ruby_file_or_function_fails_with_anchor_diagnostic(self):
        ruby = self.source / "Library/Homebrew/utils/ruby.sh"
        for content in (None, "# upstream removed the Ruby function\n"):
            with self.subTest(content=content):
                if content is None:
                    ruby.unlink()
                else:
                    ruby.write_text(content)
                shutil.rmtree(self.out, ignore_errors=True)
                result = self.patch()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("setup-ruby-path", result.stderr)
                self.assertIn("ruby.sh", result.stderr)

    def test_transformed_entry_points_disable_updates_and_preserve_tap_loops(self):
        result = self.patch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        environment = {key: value for key, value in os.environ.items()
                       if key != "HOMEBREW_NO_AUTO_UPDATE"}
        brew = subprocess.run(["bash", str(self.out / "bin/brew")], env=environment,
                              check=True, capture_output=True, text=True)
        self.assertEqual(brew.stdout, "1\n")
        tap = self.root / "Library/Taps/owner/repo"
        tap.mkdir(parents=True)
        update = subprocess.run(
            ["bash", str(self.out / "Library/Homebrew/cmd/update.sh")],
            env={**environment, "HOMEBREW_REPOSITORY": str(self.out),
                 "HOMEBREW_LIBRARY": str(self.root / "Library")},
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(update.stdout.splitlines(), [str(tap), str(tap)])
        ruby = subprocess.run(
            ["bash", "-c", 'source "$1"; setup-ruby-path; printf "%s\\n" "$HOMEBREW_RUBY_PATH"',
             "ruby-test", str(self.out / "Library/Homebrew/utils/ruby.sh")],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(ruby.stdout, "/nix/ruby/bin/ruby\n")

    def test_changed_substitution_anchors_fail_instead_of_shipping_partial_patch(self):
        for name, anchor in (
            ("Library/Homebrew/cmd/update.sh", 'for DIR in "${HOMEBREW_REPOSITORY}"'),
            ("Library/Homebrew/brew.sh", "set-homebrew-version-from-git"),
            ("bin/brew", "# Copy and export all HOMEBREW_* variables previously mentioned in"),
        ):
            with self.subTest(name=name):
                target = self.source / name
                target.write_text(self.files[name].replace(anchor, "upstream-changed-anchor"))
                shutil.rmtree(self.out, ignore_errors=True)
                result = self.patch()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("doesn't match anything", result.stderr)
                target.write_text(self.files[name])


if __name__ == "__main__":
    unittest.main()
