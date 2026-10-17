import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("update_fixed_release", Path(__file__).with_name("update-fixed-release.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

class HermesReleaseTests(unittest.TestCase):
    def test_selects_versioned_arm64_zip_and_resolves_same_origin_url(self):
        document = """\
version: 0.22.0
files:
  - url: /releases/tag/rc.3-v0.22.0/HermesBundled-0.22.0-mac-arm64.zip
    sha512: /yJW3pbB9+1By97TUSY2xgv0S2O56QMQeoxs5v+8Z17MiVV5XWFVsTfd8RND7D9rFnQ1Eha8ThUWSOC1F9SF4Q==
  - url: /releases/tag/rc.3-v0.22.0/HermesBundled-0.22.0-mac-arm64.dmg
    sha512: AoSIZ9q9f1K3eW65/NculpeOa3VmaZUIyDFXvHVb8qG5msI4iFDDL4ZH8X+nyZFU+u8CtBfL31kD4ZqBN56ewQ==
  - url: /releases/tag/rc.3-v0.22.0/HermesBundled-0.22.0-mac-arm64-Light.dmg
    sha512: AoSIZ9q9f1K3eW65/NculpeOa3VmaZUIyDFXvHVb8qG5msI4iFDDL4ZH8X+nyZFU+u8CtBfL31kD4ZqBN56ewQ==
"""
        self.assertEqual(
            updater.parse_hermes_feed(document),
            {
                "version": "0.22.0",
                "url": "https://hermes-assets.nousresearch.com/releases/tag/rc.3-v0.22.0/HermesBundled-0.22.0-mac-arm64.zip",
                "hash": "sha512-/yJW3pbB9+1By97TUSY2xgv0S2O56QMQeoxs5v+8Z17MiVV5XWFVsTfd8RND7D9rFnQ1Eha8ThUWSOC1F9SF4Q==",
            },
        )

    def test_rejects_wrong_origin_and_invalid_sha512(self):
        digest = "/yJW3pbB9+1By97TUSY2xgv0S2O56QMQeoxs5v+8Z17MiVV5XWFVsTfd8RND7D9rFnQ1Eha8ThUWSOC1F9SF4Q=="
        for url in (
            "https://example.invalid/HermesBundled-0.22.0-mac-arm64.zip",
            "http://hermes-assets.nousresearch.com/releases/tag/rc.3-v0.22.0/HermesBundled-0.22.0-mac-arm64.zip",
        ):
            document = f"version: 0.22.0\nfiles:\n  - url: {url}\n    sha512: {digest}\n"
            with self.subTest(url=url), self.assertRaises(ValueError):
                updater.parse_hermes_feed(document)

        document = """\
version: 0.22.0
files:
  - url: /releases/tag/rc.3-v0.22.0/HermesBundled-0.22.0-mac-arm64.zip
    sha512: not-a-digest
"""
        with self.assertRaisesRegex(ValueError, "invalid SHA-512"):
            updater.parse_hermes_feed(document)


if __name__ == "__main__":
    unittest.main()
