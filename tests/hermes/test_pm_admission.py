#!/usr/bin/env python3
"""Exercise packaged PM admission, stopping before external tool I/O."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ToolBoundaryReached(Exception):
    pass


class PackagedPluginAdmission(unittest.TestCase):
    def test_admission_reaches_tool_boundary_with_complete_core_inputs(self):
        with tempfile.TemporaryDirectory(prefix="hermes-pm-admission-") as temporary:
            root = Path(temporary)
            home = root / ".hermes"
            plugins = home / "plugins"
            plugins.mkdir(parents=True)
            config = home / "config.yaml"
            original = json.dumps({"plugins": {"enabled": [], "disabled": []}})
            config.write_text(original)
            with patch.dict(os.environ, HOME=str(root), HERMES_REAL_HOME=str(root),
                            HERMES_HOME=str(home)):
                from hermes_cli.plugins_admission import admit_plugin_set_change, AdmissionRefused
                from pm.paths import repo_root
                from pm.workspace import _copy_core_inputs

                # No PM helpers are replaced: block tool downloads and execution.
                with patch.object(subprocess, "Popen", side_effect=ToolBoundaryReached("offline tool boundary")), \
                     patch.object(subprocess, "run", side_effect=ToolBoundaryReached("offline tool boundary")), \
                     patch.object(socket.socket, "connect", side_effect=ToolBoundaryReached("offline tool boundary")):
                    with self.assertRaisesRegex(AdmissionRefused, "offline tool boundary"):
                        admit_plugin_set_change(set(), set(), active_plugins_dir=plugins)
                self.assertEqual(config.read_text(), original)
                snapshot = root / "snapshot"
                snapshot.mkdir()
                _copy_core_inputs(repo_root(), snapshot)
                import tomllib
                metadata = tomllib.loads((snapshot / "pyproject.toml").read_text())
                self.assertEqual(metadata["project"]["name"], "hermes-agent")
                self.assertTrue((snapshot / metadata["project"]["readme"]).is_file())
                self.assertTrue((snapshot / "hermes_cli" / "main.py").is_file())
                self.assertTrue((snapshot / "pm" / "worker.py").is_file())

    def test_generated_workspace_rewrites_read_only_core_snapshot(self):
        import tomllib

        with tempfile.TemporaryDirectory(prefix="hermes-pm-workspace-") as temporary:
            root = Path(temporary)
            generated = root / "generation"

            from pm.paths import repo_root
            from pm.workspace import _generate_pyproject

            source = repo_root().resolve()
            source_pyproject = source / "pyproject.toml"
            self.assertTrue(source_pyproject.is_file())
            self.assertEqual(source_pyproject.stat().st_mode & 0o222, 0)
            self.assertFalse(generated.exists())

            _generate_pyproject([], generated, source=source, python=sys.executable)

            generated_pyproject = generated / "pyproject.toml"
            self.assertNotEqual(generated_pyproject.stat().st_mode & 0o222, 0)
            generated_metadata = tomllib.loads(generated_pyproject.read_text(encoding="utf-8-sig"))
            source_metadata = tomllib.loads(source_pyproject.read_text(encoding="utf-8-sig"))
            self.assertEqual(generated_metadata["project"], source_metadata["project"])
            self.assertEqual(generated_metadata["project"]["name"], "hermes-agent")
            self.assertTrue((generated / generated_metadata["project"]["readme"]).is_file())

            for relative in ("hermes_cli/main.py", "pm/paths.py", "pm/worker.py"):
                with self.subTest(relative=relative):
                    self.assertEqual((generated / relative).read_bytes(), (source / relative).read_bytes())

            source_spec = importlib.util.spec_from_file_location(
                "hermes_checkout_pm_paths", source / "pm" / "paths.py"
            )
            self.assertIsNotNone(source_spec)
            source_paths = importlib.util.module_from_spec(source_spec)
            source_spec.loader.exec_module(source_paths)
            self.assertEqual(source_paths.repo_root(), source)

            generated_spec = importlib.util.spec_from_file_location(
                "hermes_generated_pm_paths", generated / "pm" / "paths.py"
            )
            self.assertIsNotNone(generated_spec)
            generated_paths = importlib.util.module_from_spec(generated_spec)
            generated_spec.loader.exec_module(generated_paths)
            self.assertEqual(generated_paths.repo_root(), generated.resolve())

            generated_pyproject.write_text(
                generated_pyproject.read_text(encoding="utf-8"), encoding="utf-8"
            )
            self.assertEqual(
                tomllib.loads(generated_pyproject.read_text(encoding="utf-8")),
                generated_metadata,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
