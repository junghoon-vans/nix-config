"""Unit fixtures: synthetic repositories and manifests, never upstream execution."""

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("paseo_updater", Path(__file__).with_name("update-paseo-plugins.py"))
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)
OLD = "a" * 40
NEW = "b" * 40
OLD_HASH = "sha256-" + "A" * 43 + "="
NEW_HASH = "sha256-" + "B" * 43 + "="


class PluginUpdates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "modules").mkdir()
        self.module = self.root / "modules/home-manager.nix"
        self.module.write_text("\n".join(
            f'{symbol} = pkgs.fetchzip {{\n  url = "https://github.com/{repo}/archive/{OLD}.tar.gz";\n  hash = "{OLD_HASH}";\n}};'
            for _, symbol, repo, _ in updater.SPECS
        ))
        self.original = self.module.read_text()
        (self.root / "release-pins.json").write_text(json.dumps({"paseo": {"version": "0.13.2"}}))
        self.revision = NEW
        self.manifests = {}
        for plugin_id, _, repo, directory in updater.SPECS:
            source = self.root / repo.replace("/", "_")
            plugin = source / directory
            plugin.mkdir(parents=True)
            manifest = plugin / "paseo-plugin.json"
            manifest.write_text(json.dumps({"id": plugin_id, "requirements": {"paseo": ">=0.12.0-beta.1"}}))
            for entry in ("index.server.ts", "index.client.tsx"):
                (plugin / entry).write_text("throw new Error('fixture must never execute');")
            self.manifests[plugin_id] = manifest

    def api(self, path):
        if "/releases?" in path:
            return []
        if "/commits/" in path:
            return {"sha": self.revision}
        if "/compare/" in path:
            return {"status": "ahead"}
        return {"default_branch": "main"}

    def fetch(self, url):
        repo = url.removeprefix("https://github.com/").split("/archive/")[0]
        return (OLD_HASH if self.revision == OLD else NEW_HASH, self.root / repo.replace("/", "_"))

    def run_update(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return updater.update(self.root, api=self.api, fetch=self.fetch, **kwargs)

    def test_updates_all_pins_and_second_run_is_no_change(self):
        self.assertTrue(self.run_update())
        text = self.module.read_text()
        self.assertEqual(text.count(NEW), 3)
        self.assertEqual(text.count(NEW_HASH), 3)
        self.assertNotIn(OLD, text)
        self.assertFalse(self.run_update())
        self.assertEqual(self.module.read_text(), text)

    def test_no_change_leaves_file_identical(self):
        self.revision = OLD
        self.assertFalse(self.run_update())
        self.assertEqual(self.module.read_text(), self.original)

    def test_dry_run_inspects_without_writing(self):
        body = self.root / "body.md"
        self.assertTrue(self.run_update(dry_run=True, body_file=body))
        self.assertEqual(self.module.read_text(), self.original)
        self.assertIn(NEW, body.read_text())

    def test_late_manifest_error_preserves_all_pins(self):
        self.manifests["keep-awake"].write_text(json.dumps({"id": "wrong"}))
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            self.run_update()
        self.assertEqual(self.module.read_text(), self.original)

    def test_newer_requirement_preserves_all_pins(self):
        self.manifests["keep-awake"].write_text(json.dumps({"id": "keep-awake", "requirements": {"paseo": ">=0.14.0"}}))
        with self.assertRaisesRegex(ValueError, "requires Paseo"):
            self.run_update()
        self.assertEqual(self.module.read_text(), self.original)

    def test_hash_process_error_preserves_all_pins(self):
        with patch.object(self, "fetch", side_effect=subprocess.CalledProcessError(1, ["nix"])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_update()
        self.assertEqual(self.module.read_text(), self.original)

    def test_api_error_does_not_fall_back(self):
        with patch.object(self, "api", side_effect=subprocess.CalledProcessError(1, ["gh"])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_update()
        self.assertEqual(self.module.read_text(), self.original)

    def test_immutable_hash_mismatch_fails(self):
        self.revision = OLD
        with patch.object(self, "fetch", return_value=(NEW_HASH, self.root)):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                self.run_update()
        self.assertEqual(self.module.read_text(), self.original)

    def test_missing_or_escaping_entrypoint_fails(self):
        entry = self.manifests["keep-awake"].parent / "index.server.ts"
        entry.unlink()
        entry.symlink_to(self.module)
        with self.assertRaisesRegex(ValueError, "escaping"):
            self.run_update()
        self.assertEqual(self.module.read_text(), self.original)

    def test_stable_release_preferred_over_branch(self):
        calls = []
        def api(path):
            calls.append(path)
            if "/releases?" in path:
                return [{"draft": False, "prerelease": False}]
            if path.endswith("/releases/latest"):
                return {"tag_name": "v1.0.0"}
            return self.api(path)
        revision, policy = updater.candidate("fixture/plugin", OLD, api)
        self.assertEqual(revision, NEW)
        self.assertIn("stable release v1.0.0", policy)
        self.assertIn("repos/fixture/plugin/commits/v1.0.0", calls)
        self.assertNotIn("repos/fixture/plugin", calls)

    def test_older_release_retains_pin_and_divergence_fails(self):
        for status in ("behind", "diverged"):
            def api(path):
                return {"status": status} if "/compare/" in path else self.api(path)
            if status == "behind":
                self.assertEqual(updater.candidate("fixture/plugin", OLD, api)[0], OLD)
            else:
                with self.assertRaisesRegex(ValueError, "diverged"):
                    updater.candidate("fixture/plugin", OLD, api)

    def test_requirement_boundaries_and_unknown_ranges(self):
        for installed, requirement, accepted in (
            ("0.12.0-beta.1", ">=0.12.0-beta.1", True),
            ("0.12.0", ">=0.12.0-beta.1", True),
            ("0.12.0-beta.1", ">=0.12.0", False),
            ("0.13.2", "^0.12.0", False),
            ("0.13.2", ">=0.12.0 <0.13.0", False),
        ):
            with self.subTest(installed=installed, requirement=requirement):
                manifest = {"id": "fixture", "requirements": {"paseo": requirement}}
                if accepted:
                    self.assertEqual(updater.compatible(manifest, "fixture", installed), requirement)
                else:
                    with self.assertRaises(ValueError):
                        updater.compatible(manifest, "fixture", installed)


if __name__ == "__main__":
    unittest.main()
