"""Unit fixtures: synthetic repositories and manifests, never upstream execution."""

import contextlib
import importlib.util
import io
import json
import os
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

# Keep test declarations independent of the updater's implementation data.
PLUGIN_DEFINITIONS = {
    "paseo-jira": ("tranhuywin/paseo-jira", ""),
    "fixture-nested": ("sample-owner/paseo-monitor", "plugins/nested"),
    "keep-awake": ("hichamboushaba/paseo-plugins", "keep-awake"),
    "fixture-four": ("sample-owner/paseo-tools", "plugins/examples/nested-plugin"),
}


class PluginUpdates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR") or None)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        modules = self.root / "modules"
        modules.mkdir()
        self.pins_file = modules / "paseo-plugins.json"
        self.initial_pins = {
            plugin_id: {
                "source": "github",
                "repository": repository,
                "directory": directory,
                "revision": OLD,
                "hash": OLD_HASH,
                "enabled": True,
            }
            for plugin_id, (repository, directory) in PLUGIN_DEFINITIONS.items()
        }
        self.pins_file.write_text(json.dumps(self.initial_pins, indent=2) + "\n")
        self.original = self.pins_file.read_text()
        (self.root / "release-pins.json").write_text(json.dumps({"paseo": {"version": "0.13.2"}}))
        self.revision = NEW
        self.revisions = {}
        self.branch = "main"
        self.sources = {}
        self.manifests = {}
        for plugin_id, (repository, directory) in PLUGIN_DEFINITIONS.items():
            source = self.root / repository.replace("/", "_")
            plugin = source / directory
            plugin.mkdir(parents=True)
            manifest = plugin / "paseo-plugin.json"
            manifest.write_text(json.dumps({"id": plugin_id, "requirements": {"paseo": ">=0.12.0-beta.1"}}))
            for entry in ("index.server.ts", "index.client.tsx"):
                (plugin / entry).write_text("throw new Error('fixture must never execute');")
            self.sources[repository] = source
            self.manifests[plugin_id] = manifest
        self.api_calls = []
        self.fetch_calls = []

    def api(self, path):
        self.api_calls.append(path)
        if "/releases?" in path:
            return []
        if "/commits/" in path:
            repository = path.split("repos/", 1)[1].split("/commits/", 1)[0]
            return {"sha": self.revisions.get(repository, self.revision)}
        if "/compare/" in path:
            return {"status": "ahead"}
        return {"default_branch": self.branch}

    def fetch(self, url):
        self.fetch_calls.append(url)
        repository = url.removeprefix("https://github.com/").split("/archive/")[0]
        revision = url.split("/archive/", 1)[1].removesuffix(".tar.gz")
        return (OLD_HASH if revision == OLD else NEW_HASH, self.sources[repository])

    def run_update(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return updater.update(self.root, api=self.api, fetch=self.fetch, **kwargs)

    def read_pins(self):
        return json.loads(self.pins_file.read_text())

    def test_discovers_updates_all_declared_plugins_and_is_idempotent(self):
        self.assertTrue(self.run_update())
        pins = self.read_pins()
        for plugin_id, initial in self.initial_pins.items():
            expected = dict(initial, revision=NEW, hash=NEW_HASH)
            self.assertEqual(pins[plugin_id], expected)
        fourth_repository = PLUGIN_DEFINITIONS["fixture-four"][0]
        self.assertTrue(any(fourth_repository in path for path in self.api_calls))
        self.assertTrue(any(fourth_repository in url for url in self.fetch_calls))
        text = self.pins_file.read_text()
        self.assertFalse(self.run_update())
        self.assertEqual(self.pins_file.read_text(), text)

    def test_no_change_leaves_file_identical_and_reports_full_unchanged_pins(self):
        self.revision = OLD
        body = self.root / "body.md"
        self.assertFalse(self.run_update(body_file=body))
        self.assertEqual(self.pins_file.read_text(), self.original)
        report = body.read_text()
        self.assertEqual(report.count("| Dependency |"), 1)
        for plugin_id, (repository, _) in PLUGIN_DEFINITIONS.items():
            self.assertIn(
                f"| {plugin_id} | revision {OLD} | revision {OLD} | Unchanged;",
                report,
            )
            self.assertIn(
                f"https://github.com/{repository}/compare/{OLD}...{OLD}",
                report,
            )
            self.assertIn(f"source hash {OLD_HASH} → {OLD_HASH}", report)
        self.assertIn("Paseo requirement &gt;=0.12.0-beta.1", report)

    def test_report_groups_changed_and_unchanged_plugins_with_full_pins(self):
        retained_repository = PLUGIN_DEFINITIONS["keep-awake"][0]
        self.revisions[retained_repository] = OLD
        body = self.root / "body.md"
        self.assertTrue(self.run_update(body_file=body))
        report = body.read_text()
        self.assertEqual(report.count("| Dependency |"), 1)
        for plugin_id, (repository, _) in PLUGIN_DEFINITIONS.items():
            revision, change, source_hash = (
                (OLD, "Unchanged", OLD_HASH)
                if plugin_id == "keep-awake"
                else (NEW, "Updated", NEW_HASH)
            )
            self.assertIn(
                f"| {plugin_id} | revision {OLD} | revision {revision} | {change};",
                report,
            )
            self.assertIn(
                f"https://github.com/{repository}/compare/{OLD}...{revision}",
                report,
            )
            self.assertIn(f"source hash {OLD_HASH} → {source_hash}", report)
        self.assertIn("Paseo requirement &gt;=0.12.0-beta.1", report)

    def test_policy_metadata_is_escaped_in_shared_table(self):
        self.branch = "feature|_name"
        body = self.root / "body.md"
        self.assertTrue(self.run_update(body_file=body))
        report = body.read_text()
        self.assertIn("feature&#124;&#95;name", report)
        self.assertNotIn(self.branch, report)

    def test_dry_run_inspects_without_writing(self):
        body = self.root / "body.md"
        self.assertTrue(self.run_update(dry_run=True, body_file=body))
        self.assertEqual(self.pins_file.read_text(), self.original)
        self.assertIn(NEW, body.read_text())

    def test_removal_prevents_any_api_or_fetch_for_removed_plugin(self):
        removed_id = "fixture-four"
        removed_repository = PLUGIN_DEFINITIONS[removed_id][0]
        pins = self.read_pins()
        del pins[removed_id]
        self.pins_file.write_text(json.dumps(pins, indent=2) + "\n")

        self.assertTrue(self.run_update())
        updated = self.read_pins()
        self.assertNotIn(removed_id, updated)
        self.assertFalse(any(removed_repository in path for path in self.api_calls))
        self.assertFalse(any(removed_repository in url for url in self.fetch_calls))
        for plugin_id, pin in updated.items():
            self.assertEqual(pin["revision"], NEW, plugin_id)
            self.assertEqual(pin["hash"], NEW_HASH, plugin_id)

    def test_empty_plugin_map_is_safe_and_does_not_call_network(self):
        self.pins_file.write_text("{}\n")
        original = self.pins_file.read_text()
        self.assertFalse(self.run_update())
        self.assertEqual(self.api_calls, [])
        self.assertEqual(self.fetch_calls, [])
        self.assertEqual(self.pins_file.read_text(), original)

    def test_invalid_late_declarations_fail_before_network_or_write(self):
        invalid_cases = (
            ("unsupported source", lambda entry: entry.update(source="gitlab")),
            ("missing field", lambda entry: entry.pop("hash")),
            ("invalid repository", lambda entry: entry.update(repository="owner/../repo")),
            ("invalid revision", lambda entry: entry.update(revision="g" * 40)),
            ("invalid hash", lambda entry: entry.update(hash="sha256-invalid")),
            ("parent directory", lambda entry: entry.update(directory="../escape")),
            ("absolute directory", lambda entry: entry.update(directory="/absolute/path")),
            ("unknown field", lambda entry: entry.update(unexpected=True)),
            ("non-boolean enabled", lambda entry: entry.update(enabled=1)),
        )
        for index, (case, mutate) in enumerate(invalid_cases):
            with self.subTest(case=case):
                pins = json.loads(self.original)
                mutate(pins["fixture-four"])
                self.pins_file.write_text(json.dumps(pins, indent=2) + "\n")
                original = self.pins_file.read_bytes()
                body = self.root / f"invalid-{index}.md"
                with self.assertRaises(ValueError):
                    self.run_update(body_file=body)
                self.assertEqual(self.api_calls, [])
                self.assertEqual(self.fetch_calls, [])
                self.assertEqual(self.pins_file.read_bytes(), original)
                self.assertFalse(body.exists())

    def test_late_manifest_error_preserves_all_pins(self):
        self.manifests["fixture-four"].write_text(json.dumps({"id": "wrong"}))
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            self.run_update()
        self.assertEqual(self.pins_file.read_text(), self.original)

    def test_newer_requirement_preserves_all_pins(self):
        self.manifests["keep-awake"].write_text(json.dumps({"id": "keep-awake", "requirements": {"paseo": ">=0.14.0"}}))
        with self.assertRaisesRegex(ValueError, "requires Paseo"):
            self.run_update()
        self.assertEqual(self.pins_file.read_text(), self.original)

    def test_hash_process_error_preserves_all_pins(self):
        with patch.object(self, "fetch", side_effect=subprocess.CalledProcessError(1, ["nix"])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_update()
        self.assertEqual(self.pins_file.read_text(), self.original)

    def test_api_error_does_not_fall_back(self):
        with patch.object(self, "api", side_effect=subprocess.CalledProcessError(1, ["gh"])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_update()
        self.assertEqual(self.pins_file.read_text(), self.original)

    def test_immutable_hash_mismatch_fails(self):
        self.revision = OLD
        with patch.object(self, "fetch", return_value=(NEW_HASH, self.root)):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                self.run_update()
        self.assertEqual(self.pins_file.read_text(), self.original)

    def test_missing_or_escaping_entrypoint_fails(self):
        entry = self.manifests["keep-awake"].parent / "index.server.ts"
        entry.unlink()
        entry.symlink_to(self.pins_file)
        with self.assertRaisesRegex(ValueError, "escaping"):
            self.run_update()
        self.assertEqual(self.pins_file.read_text(), self.original)


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
