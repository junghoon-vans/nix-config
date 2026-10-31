import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "update_fixed_release", Path(__file__).with_name("update-fixed-release.py")
)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class FixedReleaseUpdateTests(unittest.TestCase):
    def run_update(self, root, package, release, hashes):
        fake_script = root / "scripts/updates/update-fixed-release.py"
        fake_script.parent.mkdir(parents=True, exist_ok=True)
        results = [
            subprocess.CompletedProcess([], 0, json.dumps({"hash": value}), "")
            for value in hashes
        ]
        with patch.object(updater, "__file__", str(fake_script)), \
             patch.object(updater, "github_json", return_value=release), \
             patch.object(updater.subprocess, "run", side_effect=results) as run, \
             patch.object(sys, "argv", [str(fake_script), package]):
            updater.main()
        return run

    def test_noop_keeps_original_manifest_bytes_and_unrelated_package_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "release-pins.json"
            original = (
                '{ "paseo": {"version":"0.14.0", "hash":"sha256-same", '
                '"custom":"keep"}, "other": { "version": "1.0.0" } }\n'
            )
            manifest.write_text(original)

            self.run_update(
                root, "paseo",
                {"tag_name": "v0.14.0", "assets": [{
                    "name": "Paseo-0.14.0-arm64.dmg", "browser_download_url": "https://example.invalid/paseo.dmg",
                }]},
                ["sha256-same"],
            )

            self.assertEqual(manifest.read_text(), original)

    def test_hash_only_release_change_preserves_other_package_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "release-pins.json"
            manifest.write_text(json.dumps({
                "officecli": {
                    "version": "1.0.155", "hash": "sha256-old-artifact",
                    "skillHash": "sha256-old-skill", "custom": "keep",
                },
                "other": {"version": "2.0.0", "hash": "sha256-other"},
            }, indent=2) + "\n")

            run = self.run_update(
                root, "officecli",
                {"tag_name": "v1.0.155", "assets": [{
                    "name": "officecli-mac-arm64", "browser_download_url": "https://example.invalid/officecli",
                }]},
                ["sha256-new-artifact", "sha256-new-skill"],
            )

            pins = json.loads(manifest.read_text())
            self.assertEqual(pins["officecli"], {
                "version": "1.0.155", "hash": "sha256-new-artifact",
                "skillHash": "sha256-new-skill", "custom": "keep",
            })
            self.assertEqual(pins["other"], {"version": "2.0.0", "hash": "sha256-other"})
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                run.call_args_list[1].args[0][-1],
                "https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/v1.0.155/skills/officecli/SKILL.md",
            )

    def test_unpacked_release_uses_tree_hash_instead_of_archive_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "release-pins.json"
            manifest.write_text(json.dumps({
                "bun": {"version": "1.4.3", "hash": "sha256-old"},
            }, indent=2) + "\n")
            results = [
                subprocess.CompletedProcess([], 0, json.dumps({
                    "hash": "sha256-archive", "storePath": "/nix/store/archive",
                }), ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, "sha256-unpacked\n", ""),
            ]

            fake_script = root / "scripts/updates/update-fixed-release.py"
            fake_script.parent.mkdir(parents=True)
            with patch.object(updater, "__file__", str(fake_script)), \
                 patch.object(updater, "github_json", return_value={
                     "tag_name": "bun-v1.4.4", "assets": [{
                         "name": "bun-darwin-aarch64.zip",
                         "browser_download_url": "https://example.invalid/bun.zip",
                     }],
                 }), \
                 patch.object(updater.subprocess, "run", side_effect=results) as run, \
                 patch.object(sys, "argv", [str(fake_script), "bun"]):
                updater.main()

            pins = json.loads(manifest.read_text())
            self.assertEqual(pins["bun"], {"version": "1.4.4", "hash": "sha256-unpacked"})
            self.assertEqual(run.call_args_list[1].args[0][:2], ["unzip", "-qq"])
            self.assertEqual(run.call_args_list[3].args[0][:3], ["nix", "hash", "path"])


if __name__ == "__main__":
    unittest.main()
