import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/validation/check-release-pins.py"


class ReleasePinsTests(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((ROOT / "release-pins.json").read_text())
        self.pins["egoLite"].pop("appBuild", None)
        self.pins["egoLite"].pop("appHash", None)

    def validate(self, pins):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "release-pins.json").write_text(json.dumps(pins))
            return subprocess.run([sys.executable, "-B", str(VALIDATOR)],
                                  cwd=directory, capture_output=True, text=True)

    def test_external_ego_app_needs_no_build_or_hash(self):
        result = self.validate(self.pins)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_packaged_artifact_still_requires_version_and_hash(self):
        for name, pin in self.pins.items():
            for field in pin:
                with self.subTest(package=name, field=field):
                    broken = copy.deepcopy(self.pins)
                    broken[name][field] = ""
                    result = self.validate(broken)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(name, result.stderr)

    def test_other_packages_cannot_opt_out_of_integrity(self):
        for name in self.pins:
            with self.subTest(package=name):
                broken = copy.deepcopy(self.pins)
                del broken[name]["hash"]
                result = self.validate(broken)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)


if __name__ == "__main__":
    unittest.main()
