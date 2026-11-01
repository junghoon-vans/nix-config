import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "hermes_runtime_check",
    Path(__file__).resolve().parents[2] / "tests/hermes/test_packaged_runtime.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesRuntimeDependencies(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.provider_source = Path(temporary.name)
        self.dist_info = self.provider_source / "hermes_omp_acp-0.0.dist-info"
        self.dist_info.mkdir()
        sys.path.insert(0, str(self.provider_source))
        self.addCleanup(sys.path.remove, str(self.provider_source))

    def write_dependencies(self, *dependencies):
        self.dist_info.joinpath("METADATA").write_text(
            "Metadata-Version: 2.1\nName: hermes-omp-acp\nVersion: 0.0\n"
            + "".join(f"Requires-Dist: {item}\n" for item in dependencies)
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
            MODULE.check_provider_dependencies()

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
            MODULE.check_provider_dependencies()

        message = str(failure.exception)
        self.assertIn("PyYAML", message)
        self.assertIn(f"installed={installed}", message)
        self.assertIn(f"required={required}", message)



if __name__ == "__main__":
    unittest.main()
