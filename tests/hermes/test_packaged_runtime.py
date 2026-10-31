#!/usr/bin/env python3
"""Check packaged Hermes routes and native ACP retry limits without live credentials."""

import base64
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import copy
import unittest
from unittest.mock import patch


def check_provider_dependencies(provider_source):
    from importlib import metadata
    import tomllib
    from packaging.requirements import Requirement

    pyproject_path = Path(provider_source) / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text())["project"]
    unsatisfied = []
    for declared in project.get("dependencies", []):
        requirement = Requirement(declared)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        if requirement.url is not None:
            raise RuntimeError(
                f"Cannot verify direct-URL provider dependency from installed versions: {declared}"
            )
        try:
            installed = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed is None or not requirement.specifier.contains(installed, prereleases=True):
            unsatisfied.append(
                f"{requirement.name}: installed={installed or 'missing'}; required={declared}"
            )

    if unsatisfied:
        details = "\n  ".join(unsatisfied)
        raise RuntimeError(
            f"Packaged Python environment does not satisfy provider dependencies "
            f"from {pyproject_path}:\n  {details}"
        )


def check_acp_retries(profile, command, configured_args, root):
    attempts = []

    class CapacityEndpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            attempts.append(time.monotonic())
            payload = (
                "data: "
                + json.dumps({
                    "type": "error",
                    "code": "turn_rate_limit_exceeded",
                    "message": "Codex is at capacity, please try again later",
                })
                + "\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            pass

    agent = root / ".omp/agent"
    agent.mkdir(parents=True)
    os.environ["PI_CODING_AGENT_DIR"] = str(agent)
    os.environ["PI_CONFIG_FILES"] = ""
    os.environ["PI_CODEX_WEBSOCKET"] = "0"
    # Synthetic JWT shape for the loopback Codex fixture, never a live credential.
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": "synthetic-account"}}
    encoded_claims = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    with ThreadingHTTPServer(("127.0.0.1", 0), CapacityEndpoint) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            (agent / "models.yml").write_text(json.dumps({"providers": {"fixture": {
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                "api": "openai-codex-responses",
                "apiKey": f"synthetic.{encoded_claims}.fixture",
                "models": [{"id": "retry-probe", "name": "retry-probe", "reasoning": False,
                            "contextWindow": 128000, "maxTokens": 1024}],
            }}}))
            (agent / "config.yml").write_text(json.dumps({
                "modelRoles": {"default": "fixture/retry-probe"},
                "retry": {"maxRetries": 0, "baseDelayMs": 1, "modelFallback": False},
            }))
            quiet_args = ["--no-title", "--no-lsp", "--no-extensions", "--no-skills", "--no-rules", "--no-tools"]
            for label, args, expected_requests in (
                ("ordinary ACP control", ["acp"], 1),
                ("Hermes ACP overlay", configured_args, 4),
            ):
                attempts.clear()
                with closing(profile.create_client(
                    command=command, args=[*args, *quiet_args], acp_cwd=str(root), mcp_enabled=False,
                )) as client:
                    result = client.chat.completions.create(
                        model="fixture/retry-probe", timeout=60,
                        messages=[{"role": "user", "content": "Reply OK."}],
                    )
                if len(attempts) != expected_requests:
                    raise RuntimeError(
                        f"{label} sent {len(attempts)} provider requests, expected {expected_requests}."
                    )
                if "turn_rate_limit_exceeded" not in (result.choices[0].message.content or ""):
                    raise RuntimeError(f"{label} did not reach the synthetic Codex capacity failure.")
            delays = [later - earlier for earlier, later in zip(attempts, attempts[1:])]
            for delay, minimum in zip(delays, (1.5, 3.0, 6.0), strict=True):
                if delay < minimum:
                    raise RuntimeError(f"ACP retry arrived after {delay:.3f}s, below {minimum}s.")
            print(
                "Native ACP capacity failure: control sent 1 request; Hermes overlay sent 4; "
                f"retry intervals: {', '.join(f'{delay:.2f}s' for delay in delays)}."
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)


class PackagedHermesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defaults_path, provider_source, delegation_source, cls.expected_version, cls.expected_command = INPUTS
        temporary = tempfile.TemporaryDirectory(prefix="hermes-runtime-check-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        home = cls.root / ".hermes/profiles/omp-worker"
        home.mkdir(parents=True, mode=0o700)
        os.environ.update(HOME=str(cls.root), HERMES_HOME=str(home), HERMES_REAL_HOME=str(cls.root))
        for name in ("HERMES_OMP_ACP_COMMAND", "HERMES_OMP_ACP_ARGS", "HERMES_OMP_ACP_MCP_ENABLED"):
            os.environ.pop(name, None)
        check_provider_dependencies(provider_source)
        # Complete the profile before ANY Hermes import can snapshot provider discovery.
        (home / "plugins").mkdir()
        for name, source in (("omp-acp-provider", provider_source), ("advanced-delegation", delegation_source)):
            (home / "plugins" / name).symlink_to(source, target_is_directory=True)
        from ruamel.yaml import YAML

        cls.config = YAML(typ="safe").load(Path(defaults_path).read_text())
        (home / "config.yaml").write_text(json.dumps(cls.config))
        (home / "config.yaml").chmod(0o600)
        import providers

        # Never let a slow machine/expired TTL repair a bad fixture initialization order.
        frozen_cache = patch.object(providers, "_PLUGIN_DIR_STAMP_TTL_SECONDS", float("inf"))
        frozen_cache.start()
        cls.addClassCleanup(frozen_cache.stop)
        from hermes_cli.version_info import get_version_info
        from hermes_cli.auth import PROVIDER_REGISTRY

        cls.version = get_version_info().base_version
        if "omp-acp" not in PROVIDER_REGISTRY:
            raise RuntimeError("omp-acp missing from the first auth registry snapshot; install fixtures before Hermes imports")
        from hermes_cli.plugins import get_plugin_manager

        cls.manager = get_plugin_manager()
        cls.addClassCleanup(cls.manager.unload)
        cls.manager.discover_and_load()

    def test_packaged_version(self):
        self.assertEqual(self.version, self.expected_version)

    def test_nix_launchd_detects_changed_service_definition(self):
        from hermes_cli import gateway, gateway_launchd
        import plistlib

        declared_dir = self.root / "nix-launchd"
        declared_dir.mkdir()
        label = "ai.hermes.gateway-omp-worker"
        declared = declared_dir / f"{label}.plist"
        installed = self.root / "installed.plist"
        definition = {
            "Label": label,
            "ProgramArguments": ["/nix/store/current/bin/hermes", "--profile", "omp-worker", "gateway", "run"],
            "EnvironmentVariables": {"HERMES_HOME": str(self.root / ".hermes/profiles/omp-worker")},
        }
        declared.write_bytes(plistlib.dumps(definition))
        installed.write_bytes(declared.read_bytes())
        with (
            patch.object(gateway_launchd, "_NIX_LAUNCHD_DIRECTORY", declared_dir, create=True),
            patch.object(gateway, "get_launchd_plist_path", return_value=installed),
            patch.object(gateway, "get_launchd_label", return_value=label),
        ):
            self.assertTrue(gateway.launchd_plist_is_current())
            definition["ProgramArguments"][0] = "/nix/store/old/bin/hermes"
            installed.write_bytes(plistlib.dumps(definition))
            self.assertFalse(gateway.launchd_plist_is_current())
            declared.unlink()
            self.assertEqual(plistlib.loads(gateway.generate_launchd_plist().encode())["Label"], label)

    def test_provider_auth_snapshot_without_cache_expiry(self):
        from hermes_cli.auth import PROVIDER_REGISTRY
        self.assertIn("omp-acp", PROVIDER_REGISTRY)

    def test_provider_timeout_policy(self):
        from hermes_cli.timeouts import get_provider_request_timeout, get_provider_stale_timeout
        self.assertEqual(get_provider_stale_timeout("omp-acp", "openai-codex/gpt-6.1-sol"), 1800)
        self.assertIsNone(get_provider_request_timeout("omp-acp"))
        self.assertIsNone(get_provider_stale_timeout("openai-codex"))

    def check_slack_tools(self, config):
        import model_tools
        from hermes_cli.tools_config import _get_platform_tools
        definitions = model_tools.get_tool_definitions(
            enabled_toolsets=sorted(_get_platform_tools(config, "slack")),
            quiet_mode=True, skip_tool_search_assembly=True,
        )
        functions = {tool["function"]["name"]: tool["function"] for tool in definitions}
        self.assertIn("delegate_task", functions, "delegate_task is missing from Slack tools")
        self.assertFalse({"omp_task", "omp_status", "omp_cancel"} & functions.keys())
        properties = functions["delegate_task"]["parameters"]["properties"]["tasks"]["items"]["properties"]
        self.assertEqual(properties.get("option", {}).get("enum"), ["fast", "deep", "coder"])

    def test_slack_delegation_schema(self):
        self.check_slack_tools(self.config)

    def test_missing_slack_delegation_is_rejected(self):
        config = copy.deepcopy(self.config)
        config["platform_toolsets"]["slack"] = ["memory"]
        with self.assertRaisesRegex(AssertionError, "delegate_task is missing"):
            self.check_slack_tools(config)

    def test_direct_openai_routes(self):
        from agent.delegation_registry import backend_status
        backend, error = backend_status("model_map")
        self.assertFalse(error)
        self.assertIsNotNone(backend)
        delegation = self.config["delegation"]
        self.assertEqual(delegation["backend"], "model_map")
        for name in ("fast", "deep"):
            with self.subTest(route=name):
                route = backend.route_task({"option": name}, delegation)
                self.assertEqual(route.get("provider"), "openai-codex")
                self.assertFalse(route.get("base_url"))

    def resolve_coder(self, config):
        from tools.delegate_tool_routes import resolve_task_routes
        from agent.delegation_registry import backend_status
        backend, error = backend_status("model_map")
        self.assertFalse(error)
        self.assertIsNotNone(backend)
        route = backend.route_task({"option": "coder"}, config["delegation"])
        self.assertEqual(route.get("provider"), "omp-acp", "coder must use omp-acp")
        routes, error = resolve_task_routes(
            [{"goal": "Inspect the repository", "option": "coder"},
             {"goal": "Refuse an unknown route", "option": "unknown-route"}],
            config["delegation"], None,
        )
        self.assertFalse(error)
        self.assertEqual(len(routes), 2)
        self.assertFalse(routes[0].error, str(routes[0].error))
        self.assertTrue(routes[1].error, "Unknown delegation options must be refused")
        coder = routes[0]
        credentials = coder.creds
        self.assertEqual(coder.backend, "model_map")
        self.assertEqual(credentials.get("provider"), "omp-acp", "coder must use omp-acp")
        self.assertEqual(credentials.get("model"), coder.routing_cfg["model"])
        command = credentials.get("command")
        self.assertTrue(command, "coder lost its packaged OMP executable")
        self.assertEqual(Path(command).resolve(), Path(self.expected_command).resolve())
        self.assertTrue(os.access(command, os.X_OK))
        settings = config["plugins"]["entries"]["omp-acp-provider"]["settings"]
        self.assertEqual(credentials.get("args"), settings["args"])
        return credentials

    def test_coder_dispatch_and_unknown_route_refusal(self):
        self.resolve_coder(self.config)

    def test_wrong_coder_provider_is_rejected(self):
        config = copy.deepcopy(self.config)
        options = config["delegation"]["backends"]["model_map"]["options"]
        next(option for option in options if option["name"] == "coder")["provider"] = "openai-codex"
        with self.assertRaisesRegex(AssertionError, "coder must use omp-acp"):
            self.resolve_coder(config)

    def test_native_acp_capacity_retries(self):
        from providers import get_provider_profile
        credentials = self.resolve_coder(self.config)
        check_acp_retries(get_provider_profile("omp-acp"), credentials["command"], credentials["args"], self.root)


if __name__ == "__main__":
    INPUTS = sys.argv[1:]
    if len(INPUTS) != 5:
        raise SystemExit("usage: test_packaged_runtime.py CONFIG PROVIDER DELEGATION VERSION OMP")
    unittest.main(argv=[sys.argv[0]], verbosity=2)
