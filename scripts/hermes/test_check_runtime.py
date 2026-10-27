import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "hermes_runtime_check", Path(__file__).with_name("check-runtime.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesRuntimeDependencies(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.provider_source = Path(temporary.name) / "provider"
        self.provider_source.mkdir()
        self.pyproject = self.provider_source / "pyproject.toml"

    def write_dependencies(self, *dependencies):
        declared = ",\n".join(f"    {json.dumps(item)}" for item in dependencies)
        self.pyproject.write_text(
            '[project]\nname = "runtime-check-fixture"\nversion = "1.0"\n'
            f"dependencies = [\n{declared}\n]\n"
        )

    def test_reports_only_unsatisfied_active_dependencies(self):
        installed = importlib.metadata.version("PyYAML")
        inactive = "hermes-runtime-check-inactive-dependency"
        missing = "hermes-runtime-check-missing-dependency"
        required = f"{missing}>=1"
        self.write_dependencies(
            f"PyYAML=={installed}",
            f'{inactive}; sys_platform != {json.dumps(sys.platform)}',
            required,
        )

        with self.assertRaises(RuntimeError) as failure:
            MODULE.check_provider_dependencies(self.provider_source)

        message = str(failure.exception)
        self.assertIn(missing, message)
        self.assertIn("installed=missing", message)
        self.assertIn(f"required={required}", message)
        self.assertNotIn(inactive, message)
        self.assertNotIn("PyYAML", message)

    def test_rejects_incompatible_installed_version_with_context(self):
        installed = importlib.metadata.version("PyYAML")
        required = f"PyYAML!={installed}"
        self.write_dependencies(required)

        with self.assertRaises(RuntimeError) as failure:
            MODULE.check_provider_dependencies(self.provider_source)

        message = str(failure.exception)
        self.assertIn("PyYAML", message)
        self.assertIn(f"installed={installed}", message)
        self.assertIn(f"required={required}", message)



if __name__ == "__main__":
    unittest.main()
