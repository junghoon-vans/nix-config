import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import aside_model_catalog as aside
import test_update_models as model_tests

SPEC = importlib.util.spec_from_file_location("aside_collector", Path(__file__).with_name("collect-model-support.py"))
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

DESIRED = ["gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra"]


def catalog():
    return {"models": [{
        "id": model, "name": model, "provider": "openai-codex",
        "api": "openai-codex-responses", "baseUrl": "https://chatgpt.com/backend-api",
        "type": "chat", "reasoning": True, "input": ["text", "image"],
        "contextWindow": 272000, "maxTokens": 128000,
    } for model in DESIRED], "visibleModelIds": DESIRED.copy()}


def source():
    return {"client": "aside", "provider": "openai-codex", "role": "support",
            "kind": "live-official-catalog", "revision": "LIVE", "url": aside.URL,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "catalog": catalog(), "models": DESIRED.copy()}


class AsideCatalogTests(unittest.TestCase):
    def test_exact_visible_models_only(self):
        self.assertEqual(aside.parse_catalog(catalog()), sorted(DESIRED))
        data = catalog()
        data["visibleModelIds"].remove("gpt-6.1-sol")
        self.assertEqual(aside.parse_catalog(data), ["gpt-6-luna", "gpt-6.1-terra"])

    def test_unknown_provider_and_malformed_catalog_rejected(self):
        for mutate in (
            lambda c: c["models"][0].update(provider="openai"),
            lambda c: c["models"][0].update(api="openai-responses"),
            lambda c: c["models"][0].update(baseUrl="https://example.invalid"),
            lambda c: c["models"][0].update(id="../gpt-6-luna"),
            lambda c: c["models"][0].update(contextWindow=True),
            lambda c: c["models"][0].pop("input"),
            lambda c: c["models"].append(c["models"][0]),
            lambda c: c["visibleModelIds"].append("gpt-99-unknown"),
            lambda c: c.pop("models"),
            lambda c: c.update(schema_version=2),
        ):
            value = catalog()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                aside.parse_catalog(value)

    def test_unavailable_or_untrusted_network_fails_closed(self):
        for error in (urllib.error.URLError("unavailable"), ValueError("malformed response")):
            with patch.object(collector, "fetch", side_effect=OSError("offline")), patch.object(
                aside.urllib.request.OpenerDirector, "open", side_effect=error
            ), tempfile.TemporaryDirectory() as directory:
                result = collector.collect(Path(directory))
            self.assertFalse(any(row["client"] == "aside" for row in result["sources"]))
            self.assertTrue(any(e.startswith("aside: LIVE official catalog unavailable") for e in result["errors"]))
        with self.assertRaisesRegex(ValueError, "redirects"):
            aside.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid")

    def test_collect_rejects_status_content_type_redirect_and_oversize(self):
        from email.message import Message
        from unittest.mock import MagicMock
        for status, url, content_type, payload in (
            (200, aside.URL, "application/json", b'{"models":'),
            (200, aside.URL, "application/json", b'{"models":[],"models":[]}'),
            (503, aside.URL, "application/json", b'{}'),
            (200, "https://evil.invalid", "application/json", b'{}'),
            (200, aside.URL, "text/html", b'{}'),
            (200, aside.URL, "application/json", b'x' * (aside.MAX_BYTES + 1)),
        ):
            response = MagicMock()
            response.status, response.geturl.return_value = status, url
            response.headers = Message()
            response.headers["Content-Type"] = content_type
            response.read.return_value = payload
            response.__enter__.return_value = response
            with patch.object(aside.urllib.request.OpenerDirector, "open", return_value=response):
                with self.subTest(status=status, url=url, content_type=content_type), self.assertRaises(ValueError):
                    aside.collect_source()


class AsideEvidenceTests(unittest.TestCase):
    write = model_tests.ModelSelectionTests.write
    run_update = model_tests.ModelSelectionTests.run_update

    def setUp(self):
        model_tests.ModelSelectionTests.setUp(self)
        self.data["errors"] = []
        self.data["sources"].append(source())

    def test_live_aside_changed_models_accept_exact_catalog(self):
        for args in (
            ["init", "--initial-branch=main"], ["add", "--force", "."],
            ["-c", "user.name=Model Test", "-c", "user.email=test@example.invalid",
             "-c", "commit.gpgsign=false", "commit", "-m", "fixture"],
        ):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, timeout=10)
        self.write("modules/aside.nix", 'model = modelId: thinkingLevel: { provider = "openai-codex"; };\n' +
                   '\n'.join(f' role{i} = model "{model}" "high";' for i, model in enumerate(DESIRED)))
        # Other consumers retain their original, statically supported IDs.
        changed, report = self.run_update(check=True, base_ref="HEAD")
        self.assertEqual(changed, {})
        self.assertIn("LIVE `aside`", "\n".join(report))
        self.assertIn("NOT pinned-client verification", "\n".join(report))

    def test_unknown_aside_model_rejected(self):
        self.write("modules/aside.nix", self.before["modules/aside.nix"].replace("gpt-6-sol", "gpt-99-unknown"))
        with self.assertRaisesRegex(ValueError, "gpt-99-unknown.*aside"):
            self.run_update(check=True)

    def test_live_evidence_provenance_time_and_model_tampering_rejected(self):
        original = copy.deepcopy(self.data)
        for changes in (
            {"url": aside.URL + "?untrusted=1"}, {"provider": "openai"},
            {"kind": "static-catalog"}, {"revision": "a" * 40}, {"pin_revision": "latest"},
            {"observed_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
            {"observed_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
            {"observed_at": "2026-11-07T00:00:00"}, {"observed_at": None},
            {"catalog": {}}, {"models": DESIRED + ["gpt-99-unknown"]},
        ):
            self.data = copy.deepcopy(original)
            self.data["sources"][-1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_update(check=True)

    def test_live_kind_cannot_replace_static_omp_or_hermes(self):
        for index in (0, 1):
            self.data["sources"][index]["kind"] = "live-official-catalog"
            with self.assertRaisesRegex(ValueError, "invalid pinned catalog provenance"):
                self.run_update(check=True)
            self.data["sources"][index]["kind"] = "static-catalog"

    def test_aside_network_failure_blocks_changed_aside_model(self):
        self.data["sources"].pop()
        self.data["errors"] = ["aside: LIVE official catalog unavailable"]
        self.write("modules/aside.nix", self.before["modules/aside.nix"].replace("gpt-6-sol", "gpt-6-luna"))
        with self.assertRaisesRegex(ValueError, "aside.*unavailable"):
            self.run_update(check=True)

    def test_live_aside_cannot_approve_successor_missing_from_other_consumer(self):
        self.write("modules/aside.nix", self.before["modules/aside.nix"].replace("gpt-6-sol", "gpt-6.9-terra"))
        self.data["sources"][-1]["models"] = ["gpt-6.9-terra", "gpt-6.10-terra"]
        self.data["sources"][-1]["catalog"] = catalog()
        rows = self.data["sources"][-1]["catalog"]
        rows["models"] = [{**rows["models"][0], "id": model} for model in self.data["sources"][-1]["models"]]
        rows["visibleModelIds"] = self.data["sources"][-1]["models"]
        self.data["sources"][1]["models"] = ["gpt-6.9-terra"]
        changed, report = self.run_update()
        self.assertEqual(changed, {})
        self.assertIn("blocked by hermes", "\n".join(report))
