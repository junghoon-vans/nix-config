#!/usr/bin/env python3
"""Check packaged Hermes routes and native ACP retry limits without live credentials."""

import base64
import copy
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import plistlib
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
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


def _launchd_command_from_definition(definition):
    arguments = list(definition["ProgramArguments"])
    if arguments[:2] == ["/bin/sh", "-c"]:
        shell_arguments = shlex.split(arguments[2])
        try:
            exec_index = shell_arguments.index("exec")
        except ValueError as error:
            raise AssertionError("Home Manager launchd wrapper has no exec command") from error
        return shell_arguments[exec_index + 1:]
    return arguments


class PackagedHermesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (
            defaults_path,
            provider_source,
            delegation_source,
            cls.expected_version,
            cls.expected_command,
            launchd_plist,
        ) = INPUTS
        cls.launchd_plist = Path(launchd_plist)
        temporary = tempfile.TemporaryDirectory(prefix="hermes-runtime-check-")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name)
        home = cls.root / ".hermes/profiles/omp-worker"
        cls.home = home
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

    def test_home_manager_agent_is_outside_upstream_service_ownership(self):
        from hermes_cli import gateway

        fixture_bytes = self.launchd_plist.read_bytes()
        definition = plistlib.loads(fixture_bytes)
        label = "org.nixos.hermes.gateway-omp-worker"
        self.assertEqual(definition.get("Label"), label)
        self.assertEqual(
            _launchd_command_from_definition(definition)[1:6],
            ["--profile", "omp-worker", "gateway", "run", "--external-supervisor"],
        )
        profile_home = Path(definition["EnvironmentVariables"]["HERMES_HOME"])
        self.assertEqual(profile_home.parts[-3:], (".hermes", "profiles", "omp-worker"))
        self.assertEqual(definition.get("KeepAlive"), {"SuccessfulExit": False})
        self.assertEqual(definition.get("ThrottleInterval"), 30)

        agents = self.root / "Library/LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        custom_plist = agents / f"{label}.plist"
        custom_plist.write_bytes(fixture_bytes)
        canonical_plist = agents / "ai.hermes.gateway-omp-worker.plist"
        self.assertEqual(gateway.get_launchd_label(), "ai.hermes.gateway-omp-worker")

        launchctl_calls = []

        def launchctl(command, **_kwargs):
            command = list(command)
            launchctl_calls.append(command)
            if command[:2] == ["launchctl", "print"]:
                self.assertEqual(command[2].rsplit("/", 1)[-1], "ai.hermes.gateway-omp-worker")
                return subprocess.CompletedProcess(command, 113, stdout="", stderr="service not found")
            if command == ["launchctl", "list"]:
                return subprocess.CompletedProcess(
                    command, 0, stdout=f"58321\t0\t{label}\n", stderr=""
                )
            self.fail(f"unexpected launchctl query: {command}")

        with (
            patch.object(gateway, "supports_systemd_services", return_value=False),
            patch.object(gateway, "is_macos", return_value=True),
            patch.object(gateway, "get_launchd_plist_path", return_value=canonical_plist),
            patch.object(gateway, "launchd_gateway_labels_for_install", return_value=[]),
            patch.object(gateway.subprocess, "run", side_effect=launchctl),
        ):
            self.assertIsNone(gateway._installed_service_kind_for(lambda: False))
            self.assertEqual(gateway._get_service_pids(all_profiles=True), set())

        self.assertEqual(custom_plist.read_bytes(), fixture_bytes)
        self.assertTrue(any(command == ["launchctl", "list"] for command in launchctl_calls))
        self.assertFalse(any(command[1] in {"bootstrap", "bootout", "kickstart"} for command in launchctl_calls))

    def test_nix_owned_profile_passes_real_gateway_startup_guard(self):
        definition = plistlib.loads(self.launchd_plist.read_bytes())
        command = _launchd_command_from_definition(definition)
        probe = (
            f"import sys; sys.argv = {['hermes', *command[1:]]!r}; "
            "import hermes_cli.main; "
            "from hermes_cli.gateway import _attach_to_host_gateway_or_guard; "
            "_attach_to_host_gateway_or_guard()"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", probe],
            env={
                **os.environ,
                "HOME": str(self.root),
                "HERMES_HOME": str(self.home),
                "HERMES_REAL_HOME": str(self.root),
                "XPC_SERVICE_NAME": definition["Label"],
            },
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_profile_override_and_external_supervisor_restart(self):
        from types import SimpleNamespace

        from gateway import control_socket
        from hermes_cli import gateway

        definition = plistlib.loads(self.launchd_plist.read_bytes())
        command = _launchd_command_from_definition(definition)
        argv = ["hermes", *command[1:]]
        probe_env = os.environ.copy()
        probe_env.update(
            HOME=str(self.root),
            HERMES_HOME=str(self.home),
            HERMES_REAL_HOME=str(self.root),
        )
        probe = (
            f"import os, sys; sys.argv = {argv!r}; "
            "import hermes_cli.main; "
            "print('RESOLVED_HERMES_HOME=' + os.environ['HERMES_HOME'])"
        )
        profile_probe = subprocess.run(
            [sys.executable, "-c", probe],
            env=probe_env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(profile_probe.returncode, 0, profile_probe.stderr)
        resolved = next(
            line.partition("=")[2]
            for line in profile_probe.stdout.splitlines()
            if line.startswith("RESOLVED_HERMES_HOME=")
        )
        self.assertEqual(Path(resolved), self.home)

        supervised_pid = 58321
        previous_argv = sys.argv
        marker_names = (
            "INVOCATION_ID",
            "XPC_SERVICE_NAME",
            "LAUNCHD_SOCKET",
            "HERMES_LAUNCHD_LABEL",
            "HERMES_DESKTOP_MANAGED",
            "HERMES_S6_SUPERVISED_CHILD",
            "HERMES_GATEWAY_EXTERNAL_SUPERVISOR",
        )
        cleared_markers = {name: "" for name in marker_names}

        try:
            with patch.dict(os.environ, cleared_markers):
                sys.argv = argv
                run_args = SimpleNamespace(
                    external_supervisor="--external-supervisor" in argv,
                    verbose=0,
                    quiet=False,
                    replace=False,
                    force=False,
                    idle_exit=False,
                )
                with (
                    patch.object(gateway, "_maybe_redirect_run_to_s6_supervision", return_value=False),
                    patch.object(gateway, "run_gateway"),
                ):
                    gateway._cmd_run(run_args)
                self.assertEqual(os.environ["HERMES_GATEWAY_EXTERNAL_SUPERVISOR"], "1")
                self.assertEqual(control_socket._detect_supervisor(), "external")

                from gateway import status

                with (
                    patch.object(
                        status,
                        "_build_pid_record",
                        return_value={
                            "kind": "gateway",
                            "pid": supervised_pid,
                            "start_time": 1.0,
                            "hermes_home": str(self.home),
                        },
                    ),
                    patch.object(status, "_get_code_identity_fields", return_value={}),
                    patch.object(status, "_profile_label_for_home", return_value="omp-worker"),
                    patch.object(status, "read_runtime_status", return_value=None),
                ):
                    identity = control_socket.build_identify_payload()
                self.assertEqual(identity["launch_supervisor"], "external")
                with (
                    patch.object(gateway, "_capture_gateway_argv", return_value=argv),
                    patch.object(
                        gateway,
                        "launch_detached_profile_gateway_restart",
                        side_effect=AssertionError("external supervisor owns update restart"),
                    ),
                    patch.object(
                        gateway,
                        "launch_detached_gateway_restart_by_cmdline",
                        side_effect=AssertionError("external supervisor owns update restart"),
                    ),
                ):
                    self.assertEqual(
                        gateway._prepare_profile_gateway_update_restart("omp-worker", supervised_pid),
                        "external-supervisor",
                    )
        finally:
            sys.argv = previous_argv

    def test_supervised_restart_exit_remains_retryable_under_launchd(self):
        from types import SimpleNamespace

        from gateway.restart import GATEWAY_SERVICE_RESTART_EXIT_CODE, map_fatal_config_exit_for_launchd
        from gateway.run_shutdown import _resolve_gateway_exit_verdict

        runner = SimpleNamespace(
            should_exit_with_failure=False,
            exit_reason=None,
            exit_code=None,
            _restart_via_service=True,
        )
        with self.assertRaises(SystemExit) as failure:
            _resolve_gateway_exit_verdict(runner, signal_initiated_shutdown=False)
        self.assertEqual(failure.exception.code, GATEWAY_SERVICE_RESTART_EXIT_CODE)
        self.assertEqual(GATEWAY_SERVICE_RESTART_EXIT_CODE, 75)
        self.assertEqual(map_fatal_config_exit_for_launchd(75), 75)
        self.assertEqual(map_fatal_config_exit_for_launchd(78), 0)

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
    if len(INPUTS) != 6:
        raise SystemExit("usage: test_packaged_runtime.py CONFIG PROVIDER DELEGATION VERSION OMP LAUNCHD_PLIST")
    unittest.main(argv=[sys.argv[0]], verbosity=2)
