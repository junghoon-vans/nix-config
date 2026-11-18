import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("model_updater", SCRIPTS / "update-models.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence.json"
        self.body = self.root / "report.md"
        self.write("release-pins.json", json.dumps({"omp": {"version": "18.16.0", "hash": "unchanged"}}))
        self.write("flake.lock", json.dumps({"nodes": {"hermes-agent": {"locked": {
            "type": "github", "owner": "NousResearch", "repo": "hermes-agent", "rev": "a" * 40}}}}))
        self.write("home/.omp/agent/config.yml", "# preserve comment\nmodelRoles:\n  default: 'openai-codex/gpt-6.9-terra:high'\n  other: openai/gpt-6.9-terra\n")
        self.write("home/.paseo/config.json", '{"daemon":{"agentProfiles":[{"id":"main","provider":"omp","model":"openai-codex/gpt-6.9-terra:low"}]}}\n')
        self.write("modules/hermes.nix", 'backends.model_map = { options = [ { name = "native"; provider = "openai-codex"; model = "gpt-6.9-terra"; } ]; };\n')
        self.write("modules/aside.nix", 'model = modelId: thinkingLevel: { provider = "openai-codex"; };\n default = model "gpt-6-sol" "high";\n')
        self.before = {p: (self.root / p).read_text() for p in (*updater.TARGETS.values(), "release-pins.json", "flake.lock")}
        self.models = ["gpt-6.9-terra", "gpt-6.10-terra", "gpt-6.11-sol", "gpt-7-terra-preview"]
        self.data = {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(), "errors": ["aside: no adapter"], "sources": []}
        for client, repo, path, pin in (
            ("omp", "can1357/oh-my-pi", "packages/catalog/src/models.json", "v18.16.0"),
            ("hermes", "NousResearch/hermes-agent", "hermes_cli/codex_models.py", "a" * 40),
        ):
            self.data["sources"].append({"client": client, "provider": "openai-codex", "kind": "static-catalog", "role": "support", "pin_revision": pin, "revision": "a" * 40, "url": f"https://raw.githubusercontent.com/{repo}/{'a' * 40}/{path}", "models": self.models})
        self.data["sources"].append({
            "client": "paseo", "provider": "openai-codex", "kind": "nonproduction-fixture",
            "role": "support", "pin_revision": "NONPRODUCTION", "revision": "NONPRODUCTION",
            "url": "file:///fixtures/paseo.json", "omp_revision": "a" * 40, "models": self.models,
        })

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def run_update(self, **kwargs):
        self.evidence.write_text(json.dumps(self.data))
        kwargs.setdefault("test_only_fixtures", True)
        return updater.update(self.root, self.evidence, self.body, **kwargs)

    def test_dynamic_terra_numeric_successor_preserves_provider_options_and_unrelated_pins(self):
        changed, report = self.run_update()
        self.assertEqual(set(p.relative_to(self.root).as_posix() for p in changed), set(updater.TARGETS.values()) - {"modules/aside.nix"})
        for path, original in self.before.items():
            expected = original if path == "modules/aside.nix" else original.replace("gpt-6.9-terra", "gpt-6.10-terra")
            if path.endswith("config.yml"):
                expected = expected.replace("other: openai/gpt-6.10-terra", "other: openai/gpt-6.9-terra")
            self.assertEqual((self.root / path).read_text(), expected)
        self.assertIn("Live account availability and inference behavior were NOT VERIFIED", "\n".join(report))
        changed, _ = self.run_update()
        self.assertEqual(changed, {})

    def test_same_model_consumer_without_support_blocks_atomic_update(self):
        self.write("modules/aside.nix", self.before["modules/aside.nix"].replace("gpt-6-sol", "gpt-6.9-terra"))
        changed, report = self.run_update()
        self.assertEqual(changed, {})
        self.assertIn("blocked by aside", "\n".join(report))

    def test_invalid_evidence_never_changes_configuration(self):
        mutations = (
            lambda: self.data.update(observed_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat()),
            lambda: self.data["sources"][0].update(pin_revision="v0.0.1"),
            lambda: self.data["sources"][1].update(revision="b" * 40),
            lambda: self.data["sources"][0].pop("pin_revision"),
            lambda: self.data["sources"].append(self.data["sources"][0].copy()),
        )
        original = json.dumps(self.data)
        for mutation in mutations:
            self.data = json.loads(original)
            mutation()
            with self.subTest(data=self.data), self.assertRaises(ValueError):
                self.run_update()
            for path, text in self.before.items():
                self.assertEqual((self.root / path).read_text(), text)

    def test_missing_support_keeps_same_model_consumers_unchanged(self):
        self.data["sources"] = [source for source in self.data["sources"] if source["client"] != "hermes"]
        changed, _ = self.run_update()
        self.assertEqual(changed, {})
        for path in updater.TARGETS.values():
            self.assertEqual((self.root / path).read_text(), self.before[path])

    def test_ambiguous_numeric_alias_is_not_selected(self):
        for row in self.data["sources"]:
            row["models"] = ["gpt-7-terra", "gpt-7.0-terra"]
        changed, report = self.run_update()
        self.assertEqual(changed, {})
        self.assertIn("ambiguous same-family", "\n".join(report))

    def test_aliases_in_union_remain_ambiguous_at_common_numeric_version(self):
        for row in self.data["sources"]:
            row["models"] = ["gpt-6.9-terra", "gpt-7-terra", "gpt-7.0-terra"]
            if row["client"] == "hermes":
                row["models"].remove("gpt-7.0-terra")
        changed, report = self.run_update()
        self.assertEqual(changed, {})
        self.assertIn("ambiguous same-family", "\n".join(report))

    def test_wm_family_and_effort_option_are_preserved(self):
        path = "home/.omp/agent/config.yml"
        self.write(
            path,
            self.before[path] + "  wm: 'openai-codex/gpt-6.9-terra-wm:medium'\n",
        )
        for source in self.data["sources"]:
            source["models"] = [
                model for model in source["models"] if model != "gpt-6.10-terra"
            ] + ["gpt-6.10-terra-wm"]
        changed, _ = self.run_update()
        self.assertEqual(set(changed), {self.root / path})
        self.assertEqual(
            (self.root / path).read_text(),
            self.before[path] + "  wm: 'openai-codex/gpt-6.10-terra-wm:medium'\n",
        )

    def test_successor_selection_uses_highest_cross_client_intersection(self):
        omp_models = ["gpt-6.9-terra", "gpt-6.10-terra", "gpt-6.11-terra"]
        for row in self.data["sources"]:
            row["models"] = omp_models if row["client"] in {"omp", "paseo"} else ["gpt-6.9-terra", "gpt-6.10-terra"]
        changed, _ = self.run_update()
        self.assertEqual(set(p.relative_to(self.root).as_posix() for p in changed), {
            "home/.omp/agent/config.yml", "home/.paseo/config.json", "modules/hermes.nix",
        })
        self.assertEqual(
            (self.root / "modules/hermes.nix").read_text(),
            self.before["modules/hermes.nix"].replace("gpt-6.9-terra", "gpt-6.10-terra"),
        )

    def test_no_common_successor_leaves_all_consumers_unchanged(self):
        for row in self.data["sources"]:
            row["models"] = ["gpt-6.9-terra", "gpt-6.10-terra"] if row["client"] in {"omp", "paseo"} else [
                "gpt-6.9-terra", "gpt-6.11-terra",
            ]
        changed, report = self.run_update()
        self.assertEqual(changed, {})
        self.assertIn("blocked by", "\n".join(report))
        for path in updater.TARGETS.values():
            self.assertEqual((self.root / path).read_text(), self.before[path])

    def test_missing_paseo_transport_proof_blocks_all_same_model_consumers(self):
        self.data["sources"] = [source for source in self.data["sources"] if source["client"] != "paseo"]
        changed, report = self.run_update()
        self.assertEqual(changed, {})
        self.assertIn("blocked by paseo", "\n".join(report))
        for path in updater.TARGETS.values():
            self.assertEqual((self.root / path).read_text(), self.before[path])

    def test_paseo_omp_revision_mismatch_fails_closed_before_edits(self):
        paseo = next(source for source in self.data["sources"] if source["client"] == "paseo")
        paseo["omp_revision"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "does not match OMP revision"):
            self.run_update()
        for path in updater.TARGETS.values():
            self.assertEqual((self.root / path).read_text(), self.before[path])

    def test_omp_compatibility_aggregate_requires_matching_provenance_and_reports_tier(self):
        omp = next(source for source in self.data["sources"] if source["client"] == "omp")
        omp.update(
            kind="static-catalog+compat",
            catalog_models=["gpt-6.9-terra", "gpt-6.11-sol", "gpt-7-terra-preview"],
            compatibility_models=["gpt-6.10-terra"],
            compat_revision="a" * 40,
            compat_url="https://raw.githubusercontent.com/can1357/oh-my-pi/"
            + "a" * 40 + "/packages/catalog/src/compat/rules/providers/openai-codex.kdl",
        )
        changed, report = self.run_update()
        self.assertTrue(changed)
        report_text = "\n".join(report)
        self.assertIn("compatibility tier (static provider rules)", report_text)
        self.assertIn(omp["compat_url"], report_text)

        omp["compat_revision"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "invalid compatibility catalog provenance"):
            self.run_update()
        omp["compat_revision"] = "a" * 40
        omp["compatibility_models"] = ["gpt-6.99-terra"]
        with self.assertRaisesRegex(ValueError, "invalid compatibility catalog provenance"):
            self.run_update()

    def test_offline_collector_to_updater_cli_requires_explicit_test_mode(self):
        compact = {"version": 1, "keys": [], "booleanShapes": [[]], "nodes": [[0, [], 0, []]], "providers": [["openai-codex", [0], [[model, [0]] for model in self.models]]]}
        self.write(
            "fixtures/omp/packages/catalog/src/compat/rules/providers/openai-codex.kdl",
            'provider "openai-codex" { models "gpt-6.10-terra" {} }\n',
        )
        self.write("fixtures/omp/packages/catalog/src/models.json", json.dumps(compact))
        self.write("fixtures/hermes/hermes_cli/codex_models.py", "DEFAULT_CODEX_MODELS = " + repr(self.models))
        collect = subprocess.run([sys.executable, "-B", str(SCRIPTS / "collect-model-support.py"), "--root", str(self.root), "--fixture-dir", str(self.root / "fixtures"), "--output", str(self.evidence)], capture_output=True, text=True, timeout=10)
        self.assertEqual(collect.returncode, 0, collect.stderr)
        command = [sys.executable, "-B", str(SCRIPTS / "update-models.py"), "--root", str(self.root), "--evidence", str(self.evidence), "--body-file", str(self.body)]
        rejected = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("NONPRODUCTION", rejected.stderr)
        accepted = subprocess.run(command + ["--test-only-fixtures"], capture_output=True, text=True, timeout=10)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual((self.root / "home/.omp/agent/config.yml").read_text(), self.before["home/.omp/agent/config.yml"].replace("openai-codex/gpt-6.9-terra", "openai-codex/gpt-6.10-terra"))
        self.assertEqual((self.root / "release-pins.json").read_text(), self.before["release-pins.json"])
        self.assertEqual((self.root / "flake.lock").read_text(), self.before["flake.lock"])
        self.assertIn("gpt-6.10-terra", self.body.read_text())
        self.assertIn("NOT VERIFIED", self.body.read_text())

    def test_check_base_ref_ignores_unchanged_gaps_but_rejects_new_unsupported_id(self):
        for args in (
            ["init", "--initial-branch=main"],
            ["add", "--force", "."],
            ["-c", "user.name=Model Test", "-c", "user.email=test@example.invalid",
             "-c", "commit.gpgsign=false", "commit", "-m", "fixture"],
        ):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, timeout=10)
        changed, _ = self.run_update(check=True, base_ref="HEAD")
        self.assertEqual(changed, {})
        path = "home/.omp/agent/config.yml"
        self.write(path, self.before[path].replace("openai-codex/gpt-6.9-terra", "openai-codex/gpt-6.10-terra"))
        changed, _ = self.run_update(check=True, base_ref="HEAD")
        self.assertEqual(changed, {})
        unsupported = (self.root / path).read_text().replace("openai-codex/gpt-6.10-terra", "openai-codex/gpt-99-terra")
        self.write(path, unsupported)
        with self.assertRaisesRegex(ValueError, "lack exact static support"):
            self.run_update(check=True, base_ref="HEAD")
        self.assertEqual((self.root / path).read_text(), unsupported)


if __name__ == "__main__":
    unittest.main()
