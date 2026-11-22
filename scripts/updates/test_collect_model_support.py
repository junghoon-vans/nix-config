import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("collect-model-support.py")
SPEC = importlib.util.spec_from_file_location("collect_model_support", SCRIPT)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def catalog():
    return {
        "version": 1, "keys": [], "booleanShapes": [[]],
        "nodes": [[0, [], 0, []]], "compat": [],
        "providers": [
            ["openai", [0], [["gpt-99-other", [0]]]],
            ["openai-codex", [0], [["gpt-6.1-terra", [0]], ["gpt-6-sol", [0]]]],
        ],
    }


class CollectorTests(unittest.TestCase):
    def test_omp_only_explicit_provider_rows(self):
        self.assertEqual(collector.parse_omp(json.dumps(catalog())),
                         ["gpt-6-sol", "gpt-6.1-terra"])

    def test_omp_ambiguous_or_unknown_formats_fail_closed(self):
        for mutate in (
            lambda c: c.update(version=2),
            lambda c: c["providers"].append(c["providers"][1]),
            lambda c: c["providers"][1][2].append(["gpt-6-sol", [0]]),
            lambda c: c["providers"][1][2].append(["gpt-7-terra", [99]]),
            lambda c: c["providers"].pop(),
        ):
            value = catalog()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                collector.parse_omp(json.dumps(value))

    def test_omp_rejects_identity_overrides_from_another_provider(self):
        value = catalog()
        value["keys"] = ["provider"]
        value["nodes"] = [[0, [0, "openai"], 0, []]]
        with self.assertRaises(ValueError):
            collector.parse_omp(json.dumps(value))

    def test_compat_exact_provider_ids_without_catalog_or_wildcard_synthesis(self):
        source = '''
// models "gpt-99-sol" { }
provider "openai-codex" {
    models "gpt-6.2-sol" "gpt-6.2-sol-wm" { max-context-window 922000; }
    models "gpt-6.2-sol" { priority 0; }
    models "gpt-88-*" { priority 0; }
    class "other" { models "gpt-77-sol" { priority 0; } }
    env "gpt-66-sol"
}
on-api "other" { models "gpt-55-sol" { priority 0; } }
'''
        self.assertEqual(collector.parse_omp_compat(source),
                         ["gpt-6.2-sol", "gpt-6.2-sol-wm"])
        self.assertNotIn("gpt-6.2-sol", collector.parse_omp(json.dumps(catalog())))
        self.assertEqual(collector.parse_omp_compat(
            'provider "openai-codex" { models "gpt-*" { priority 0; } }'), [])

    def test_compat_wrong_provider_dynamic_or_malformed_selectors_fail_closed(self):
        for source in (
            'provider "openai" { models "gpt-6.2-sol" {} }',
            'provider "openai-codex" {}\\nprovider "openai-codex" {}',
            'provider "openai-codex" { models MODEL {} }',
            'provider "openai-codex" { models "gpt-6.2-sol" }',
            'provider "openai-codex" { models "gpt-6.2-sol" {',
            'provider "openai-codex" { models "openai/gpt-6.2-sol" {} }',
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                collector.parse_omp_compat(source)

    def test_hermes_literal_list_without_execution_or_synthesis(self):
        source = '''raise RuntimeError("must not execute")
OTHER_PROVIDER = ["gpt-99-terra"]
DEFAULT_CODEX_MODELS: list[str] = ["gpt-6.1-terra", "gpt-6-sol"]
_FORWARD_COMPAT_TEMPLATE_MODELS = [("gpt-99-sol", ("gpt-6-sol",))]
# gpt-99-luna mentioned in a comment is not support.
'''
        self.assertEqual(collector.parse_hermes(source), ["gpt-6-sol", "gpt-6.1-terra"])

    def test_hermes_missing_dynamic_duplicate_or_mutated_lists_fail_closed(self):
        for source in (
            'OTHER_PROVIDER = ["gpt-6-sol"]',
            'DEFAULT_CODEX_MODELS = build_models()',
            'DEFAULT_CODEX_MODELS = ["gpt-6-sol"]\nDEFAULT_CODEX_MODELS = ["gpt-7-sol"]',
            'DEFAULT_CODEX_MODELS = ["gpt-6-sol", "gpt-6-sol"]',
            'DEFAULT_CODEX_MODELS = ["gpt-6-sol"]\nDEFAULT_CODEX_MODELS.append("gpt-7-sol")',
            'DEFAULT_CODEX_MODELS = ["gpt-6-sol"]\nDEFAULT_CODEX_MODELS[0] = "gpt-7-sol"',
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                collector.parse_hermes(source)

    def test_fixture_cli_emits_nonproduction_evidence_and_missing_source_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "release-pins.json").write_text(json.dumps({"omp": {"version": "18.16.0"}}))
            (root / "flake.lock").write_text(json.dumps({"nodes": {"hermes-agent": {"locked": {
                "type": "github", "owner": "NousResearch", "repo": "hermes-agent", "rev": "a" * 40,
            }}}}))
            fixture = root / "fixtures" / "omp" / collector.OMP_PATH
            fixture.parent.mkdir(parents=True)
            fixture.write_text(json.dumps(catalog()))
            output = root / "evidence.json"
            compat = root / "fixtures" / "omp" / collector.OMP_COMPAT_PATH
            compat.parent.mkdir(parents=True)
            compat.write_text('provider "openai-codex" { models "gpt-6.2-sol" {} }')
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(root),
                                     "--fixture-dir", str(root / "fixtures"), "--output", str(output)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(output.read_text())
            self.assertEqual(evidence["schema_version"], 1)
            self.assertTrue(any(e.startswith("NONPRODUCTION:") for e in evidence["errors"]))
            self.assertTrue(any(e.startswith("hermes:") for e in evidence["errors"]))
            sources = {row["client"]: row for row in evidence["sources"]}
            self.assertEqual(set(sources), {"omp", "hermes", "paseo"})
            self.assertTrue(sources["hermes"]["error"].startswith("hermes:"))
            omp, paseo = sources["omp"], sources["paseo"]
            self.assertEqual(omp["models"], ["gpt-6-sol", "gpt-6.1-terra", "gpt-6.2-sol"])
            self.assertEqual(omp["compatibility_models"], ["gpt-6.2-sol"])
            self.assertEqual(paseo["models"], omp["models"])
            self.assertEqual(paseo["kind"], "nonproduction-fixture")
            self.assertEqual(omp["provider"], "openai-codex")
            self.assertEqual(omp["role"], "support")
            self.assertTrue(omp["url"].startswith("file:"))


if __name__ == "__main__":
    unittest.main()
