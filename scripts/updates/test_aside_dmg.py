import hashlib
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
import tempfile
from unittest.mock import patch

import aside_dmg


CASK = '''cask "aside" do
  arch arm: "arm64", intel: "x64"
  version "1.0.1022.1"
  sha256 arm:   "HASH",
         intel: "OTHER"
  url "https://releases.aside.com/dev-updater/Aside-#{version}-#{arch}.dmg"
end
'''.replace("HASH", "a" * 64)


def literal(provider="openai-codex", model="gpt-5.6-terra"):
    return ('openai_codex_default={"openai-codex-images":{},"openai-codex-responses":{'
            f'"chat:{model}":{{id:`{model}`,provider:`{provider}`,'
            'api:`openai-codex-responses`,type:`chat`,reasoning:!0,'
            'cost:{input:.2},input:[`text`,`image`]}}}').encode()


class AsideDmgTests(unittest.TestCase):
    def test_explicit_models_without_inference(self):
        models = aside_dmg.parse_catalog(literal())
        self.assertEqual(models, ["gpt-5.6-terra"])
        self.assertNotIn("gpt-6.1-terra", models)

    def test_other_provider_rejected(self):
        with self.assertRaises(ValueError):
            aside_dmg.parse_catalog(literal(provider="openai"))

    def test_duplicate_or_dynamic_catalog_rejected(self):
        for data in (literal() + literal(), literal().replace(b"!0", b"run()"),
                     literal().replace(b"id:`", b"id:`wrong`,id:`")):
            with self.subTest(data=data), self.assertRaises(ValueError):
                aside_dmg.parse_catalog(data)

    def test_cask_hash_version_and_host_fail_closed(self):
        self.assertEqual(aside_dmg.parse_cask(CASK)["browser_version"], "1.0.1022.1")
        for text in (CASK.replace("1.0.1022.1", "latest"),
                     CASK.replace("a" * 64, "no_check"),
                     CASK.replace("releases.aside.com", "attacker.example"),
                     CASK + '\n  version "1.0.1022.1"\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                aside_dmg.parse_cask(text)

    def test_artifact_integrity(self):
        aside_dmg.verify_hash(b"artifact", hashlib.sha256(b"artifact").hexdigest())
        for digest in ("a" * 64, "invalid"):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                aside_dmg.verify_hash(b"artifact", digest)

    def test_evidence_bound_to_exact_pin_artifact_and_daemon_identity(self):
        identity = ("b" * 40, "https://example.invalid/pinned-cask")
        with patch.object(aside_dmg, "cask_identity", return_value=identity), \
                patch.object(aside_dmg, "fetch", return_value=CASK.encode()):
            source = {"provider": "openai-codex", "client": "aside", "role": "support",
                      "kind": "static-dmg-catalog", "revision": identity[0],
                      "pin_revision": identity[0], "cask_url": identity[1],
                      **aside_dmg.parse_cask(CASK), "daemon_version": "1.26.1023.5",
                      "daemon_sha256": "c" * 64}
            aside_dmg.validate_source(Path("."), source)
            for key, value in (("revision", "d" * 40), ("artifact_sha256", "d" * 64),
                               ("daemon_version", "latest"), ("daemon_sha256", "invalid"),
                               ("provider", "openai")):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    aside_dmg.validate_source(Path("."), {**source, key: value})

    def test_unknown_ambiguous_and_oversized_partitions_fail_closed(self):
        listings = (
            "Path = unexpected.bin\nSize = 12\n",
            "Path = 1.apfs\nSize = 12\n\nPath = 2.hfs\nSize = 12\n",
            f"Path = 1.apfs\nSize = {aside_dmg.MAX_PARTITION + 1}\n",
        )
        for listing in listings:
            with self.subTest(listing=listing), tempfile.TemporaryDirectory() as directory, \
                    patch.object(aside_dmg.sys, "platform", "linux"), \
                    patch.object(aside_dmg.shutil, "which", return_value="/tool/7zz"), \
                    patch.object(aside_dmg, "run", return_value=SimpleNamespace(stdout=listing)):
                with self.assertRaises(ValueError):
                    aside_dmg.bundled_files(Path("artifact.dmg"), Path(directory), "1.0.1022.1")

    def test_extracted_partition_size_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(aside_dmg.sys, "platform", "linux"), \
                patch.object(aside_dmg.shutil, "which", return_value="/tool/7zz"), \
                patch.object(aside_dmg, "run", return_value=SimpleNamespace(
                    stdout="Path = 1.apfs\nSize = 12\n")):
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                aside_dmg.bundled_files(Path("artifact.dmg"), Path(directory), "1.0.1022.1")


if __name__ == "__main__":
    unittest.main()
