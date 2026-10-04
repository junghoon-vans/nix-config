#!/usr/bin/env python3
"""Exercise native Finder aliases without changing Dock or the real home directory."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("create-stack-aliases.js")
TERMINAL = "/System/Applications/Utilities/Terminal.app"


@unittest.skipUnless(sys.platform == "darwin", "Finder aliases require macOS")
class StackAliasTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dock-alias-test-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.relative = "Library/Application Support/DockStacks/Development/Terminal.app"
        self.alias = self.home / self.relative

    def update(self, target=TERMINAL):
        subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", str(SCRIPT), str(self.home),
             json.dumps({self.relative: target})],
            check=True, capture_output=True, text=True,
        )

    def assert_terminal_alias(self):
        source = """
ObjC.import("Foundation");
function run(argv) {
    var url = $.NSURL.fileURLWithPath(argv[0]);
    var alias = Ref();
    if (!url.getResourceValueForKeyError(alias, $.NSURLIsAliasFileKey, Ref())) {
        throw new Error("Cannot read alias metadata");
    }
    var target = $.NSURL.URLByResolvingAliasFileAtURLOptionsError(
        url, $.NSURLBookmarkResolutionWithoutUI, Ref()
    );
    return JSON.stringify({alias: ObjC.unwrap(alias[0]), target: ObjC.unwrap(target.path)});
}
"""
        result = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", source, str(self.alias)],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(json.loads(result.stdout), {"alias": True, "target": TERMINAL})
        self.assertFalse(self.alias.is_symlink())

    def test_repeat_activation_keeps_a_native_alias_without_backups(self):
        self.update()
        self.update()
        self.assert_terminal_alias()
        self.assertEqual(list(self.alias.parent.glob("*.pre-nix.*")), [])

    def test_collisions_are_preserved_before_alias_creation(self):
        for collision in ("file", "broken-symlink"):
            with self.subTest(collision=collision):
                self.alias.parent.mkdir(parents=True, exist_ok=True)
                if collision == "file":
                    self.alias.write_text("user-owned content")
                else:
                    self.alias.symlink_to(self.home / "missing-store-link")
                self.update()
                self.assert_terminal_alias()
                backup, = self.alias.parent.glob("*.pre-nix.*")
                if collision == "file":
                    self.assertEqual(backup.read_text(), "user-owned content")
                else:
                    self.assertTrue(backup.is_symlink())
                    self.assertEqual(backup.readlink(), self.home / "missing-store-link")
                self.alias.unlink()
                backup.unlink()

    def test_missing_application_does_not_replace_existing_item(self):
        self.alias.parent.mkdir(parents=True)
        self.alias.write_text("keep this shortcut")
        self.update(str(self.home / "not-installed.app"))
        self.assertEqual(self.alias.read_text(), "keep this shortcut")
        self.assertEqual(list(self.alias.parent.glob("*.pre-nix.*")), [])


if __name__ == "__main__":
    unittest.main()
