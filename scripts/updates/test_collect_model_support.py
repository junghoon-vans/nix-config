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
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(root),
                                     "--fixture-dir", str(root / "fixtures"), "--output", str(output)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(output.read_text())
            self.assertEqual(evidence["schema_version"], 1)
            self.assertTrue(any(e.startswith("NONPRODUCTION:") for e in evidence["errors"]))
            self.assertTrue(any(e.startswith("hermes:") for e in evidence["errors"]))
            self.assertTrue(any(e.startswith("aside:") for e in evidence["errors"]))
            self.assertEqual(len(evidence["sources"]), 2)
            omp, hermes = evidence["sources"]
            self.assertEqual(omp["models"], ["gpt-6-sol", "gpt-6.1-terra"])
            self.assertEqual(omp["provider"], "openai-codex")
            self.assertEqual(omp["role"], "support")
            self.assertTrue(omp["url"].startswith("file:"))
            self.assertEqual(hermes["models"], [])
            self.assertIn("error", hermes)


if __name__ == "__main__":
    unittest.main()
