import importlib.util
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("update_mcp_versions", Path(__file__).with_name("update-mcp-versions.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def metadata(package):
    return {"name": package, "version": "10.0.0"}


class MCPVersionUpdateTests(unittest.TestCase):
    def test_updates_supported_launch_shapes_without_changing_other_configuration(self):
        original = {
            "$schema": "https://example.invalid/schema",
            "custom": {"note": "보존"},
            "mcpServers": {
                "direct": {"command": "npx", "args": ["--yes", "server@9.9.9"], "env": {"KEEP": "value"}},
                "scoped": {"command": "npx", "args": ["--package=@scope/server@1.0.0", "server-cli"], "instructions": False},
                "remote": {"type": "http", "url": "https://example.invalid/mcp", "headers": {"Authorization": "!do-not-execute"}},
            },
        }
        updated, _ = updater.update_configuration(json.dumps(original), metadata)
        result = json.loads(updated)
        self.assertEqual(result["mcpServers"]["direct"]["args"], ["--yes", "server@10.0.0"])
        self.assertEqual(result["mcpServers"]["scoped"]["args"], ["--package=@scope/server@10.0.0", "server-cli"])
        for name in ("direct", "scoped"):
            result["mcpServers"][name]["args"] = original["mcpServers"][name]["args"]
        self.assertEqual(result, original)

    def test_does_not_downgrade_or_reformat_an_unchanged_configuration(self):
        text = '{"mcpServers": {"server": {"command":"npx", "args":["server@10.1.0"]}}}\n'
        self.assertEqual(updater.update_configuration(text, metadata), (text, []))

    def test_experimental_disabled_floating_and_shell_commands_stay_unchanged(self):
        config = {"mcpServers": {
            "experimental": {"command": "npx", "args": ["server@1.0.0-beta.1"]},
            "disabled": {"command": "npx", "args": ["server@1.0.0"], "disabled": True},
            "floating": {"command": "npx", "args": ["server@latest"]},
            "shell": {"command": "/bin/zsh", "args": ["-lc", "npx -y server@1.0.0; touch unexpected"]},
            "local-env-shell": {"command": "/bin/zsh", "args": ["-lc", 'source "$HOME/.zshrc.local" 2>/dev/null || true; exec npx -y server@1.0.0']},
        }}
        text = json.dumps(config)
        self.assertEqual(updater.update_configuration(text, metadata), (text, []))

    def test_rejects_mismatched_deprecated_or_prerelease_latest_metadata(self):
        text = '{"mcpServers":{"server":{"command":"npx","args":["server@1.0.0"]}}}'
        for invalid in (
            {"name": "another", "version": "2.0.0"},
            {"name": "server", "version": "2.0.0", "deprecated": "unsafe"},
            {"name": "server", "version": "2.0.0-beta.1"},
            {"name": "server", "version": "2.0.0; unexpected"},
        ):
            with self.subTest(metadata=invalid), self.assertRaises(ValueError):
                updater.update_configuration(text, lambda _package: invalid)

    def test_a_later_registry_failure_does_not_partially_write_the_configuration(self):
        text = json.dumps({"mcpServers": {
            "first": {"command": "npx", "args": ["first@1.0.0"]},
            "second": {"command": "npx", "args": ["second@1.0.0"]},
        }})
        def fetch(package):
            if package == "second":
                raise OSError("registry unavailable")
            return metadata(package)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text(text)
            with patch.object(updater, "fetch_latest", fetch), patch.object(sys, "argv", ["updater", "--config", str(path)]):
                with self.assertRaises(OSError):
                    updater.main()
            self.assertEqual(path.read_text(), text)


if __name__ == "__main__":
    unittest.main()
