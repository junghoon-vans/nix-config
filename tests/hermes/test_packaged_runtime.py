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


def check_provider_dependencies():
    from importlib import metadata
    from packaging.requirements import Requirement

    distribution = metadata.distribution("hermes-omp-acp")
    unsatisfied = []
    for declared in distribution.requires or []:
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
            f"from {distribution.metadata['Name']}:\n  {details}"
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
        check_provider_dependencies()
        # Complete the profile before ANY Hermes import can snapshot provider discovery.
        (home / "plugins").mkdir()
        (home / "plugins" / "advanced-delegation").symlink_to(delegation_source, target_is_directory=True)
        from ruamel.yaml import YAML

        cls.config = YAML(typ="safe").load(Path(defaults_path).read_text())
        cls.provider_source = Path(provider_source)
        cls.apm_skill_dir = cls.root / ".agents" / "skills" / "hermes-apm-fixture"
        cls.apm_skill_dir.mkdir(parents=True)
        cls.apm_skill_content = (
            "---\n"
            "name: hermes-apm-fixture\n"
            "description: Isolated APM skill used by the packaged Hermes regression.\n"
            "---\n"
            "\n"
            "# APM fixture\n"
            "\n"
            "This skill is exposed only through the generated common skills root.\n"
        )
        (cls.apm_skill_dir / "SKILL.md").write_text(cls.apm_skill_content)
        global_roots = [
            path
            for path in cls.config["skills"]["external_dirs"]
            if Path(path).parts[-2:] == (".agents", "skills")
        ]
        if len(global_roots) != 1:
            raise RuntimeError("generated Hermes config must declare the common .agents/skills root once")
        # Redirect only the generated common root into the disposable HOME.
        isolated_global_root = str(cls.root / ".agents" / "skills")
        cls.config["skills"]["external_dirs"] = [
            isolated_global_root if path == global_roots[0] else path
            for path in cls.config["skills"]["external_dirs"]
        ]
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

    def test_installed_provider_discovery(self):
        from importlib import metadata
        from hermes_omp_acp.skill_resources import skill_directory

        self.assertEqual(metadata.version("hermes-omp-acp"), "0.3.0")
        self.assertEqual(metadata.version("agent-client-protocol"), "0.9.0")
        entries = [
            entry for entry in metadata.entry_points(group="hermes_agent.plugins")
            if entry.dist.metadata["Name"] == "hermes-omp-acp"
        ]
        self.assertCountEqual(
            [entry.name for entry in entries], ["omp-acp-provider", "omp-acp-skills"]
        )
        self.assertFalse((self.home / "plugins" / "omp-acp-provider").exists())
        self.assertEqual(skill_directory().resolve(), (self.provider_source / "skills").resolve())

    def test_generated_config_discovers_apm_and_provider_skills_without_hiding_bundled_skills(self):
        from tools.skills_sync import sync_skills
        from tools.skills_tool import skill_view, skills_list

        sync_skills()
        listing = json.loads(skills_list())
        self.assertTrue(listing.get("success"), listing)
        names = {skill["name"] for skill in listing["skills"]}
        self.assertIn("hermes-apm-fixture", names)
        self.assertIn("omp-web-search", names)
        self.assertIn("github", names)
        self.assertIn("hermes-agent", names)

        apm_view = json.loads(skill_view("hermes-apm-fixture", preprocess=False))
        self.assertTrue(apm_view.get("success"), apm_view)
        expected_apm = self.apm_skill_dir / "SKILL.md"
        self.assertEqual(Path(apm_view["skill_dir"]).resolve(), self.apm_skill_dir.resolve())
        self.assertEqual(apm_view["content"], self.apm_skill_content)

        provider_view = json.loads(skill_view("omp-web-search", preprocess=False))
        self.assertTrue(provider_view.get("success"), provider_view)
        expected_provider = self.provider_source / "skills/omp-web-search/SKILL.md"
        self.assertEqual(Path(provider_view["skill_dir"]).resolve(), expected_provider.parent.resolve())
        self.assertEqual(provider_view["content"], expected_provider.read_text())
        self.assertEqual(self.resolve_omp(self.config)["provider"], "omp-acp")
        print(
            "Generated-config skills: hermes-apm-fixture, omp-web-search, github, hermes-agent; "
            f"APM fixture: {expected_apm}; provider source: {expected_provider}"
        )

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

    def test_native_mcp_policy_uses_exact_offline_allowlists(self):
        from types import SimpleNamespace

        import model_tools
        from hermes_cli.tools_config import _get_platform_tools
        from tools import mcp_tool
        from tools.mcp_tool_config import _interpolate_env_vars
        from tools.mcp_tool_registration import _register_server_tools
        from tools.mcp_tool_scope import _server_key

        expected_native_tools = {
            "notion": (
                "notion-search",
                "notion-fetch",
                "notion-get-self",
                "notion-get-tool-access",
                "notion-query-data-sources",
                "notion-get-comments",
            ),
            "github": (
                "get_me",
                "search_repositories",
                "list_pull_requests",
                "search_pull_requests",
                "pull_request_read",
                "actions_list",
                "actions_get",
                "get_job_logs",
            ),
            "context7": ("resolve-library-id", "query-docs"),
            "atlassian": (
                "atlassianUserInfo",
                "getAccessibleAtlassianResources",
                "getJiraIssue",
                "searchJiraIssuesUsingJql",
                "getConfluenceContent",
                "searchConfluence",
            ),
            "aside": ("browser_profiles", "exec", "repl", "memory_search"),
        }
        expected_registered_tools = {
            "notion": {
                "mcp__notion__notion_search",
                "mcp__notion__notion_fetch",
                "mcp__notion__notion_get_self",
                "mcp__notion__notion_get_tool_access",
                "mcp__notion__notion_query_data_sources",
                "mcp__notion__notion_get_comments",
            },
            "github": {
                "mcp__github__get_me",
                "mcp__github__search_repositories",
                "mcp__github__list_pull_requests",
                "mcp__github__search_pull_requests",
                "mcp__github__pull_request_read",
                "mcp__github__actions_list",
                "mcp__github__actions_get",
                "mcp__github__get_job_logs",
            },
            "context7": {
                "mcp__context7__resolve_library_id",
                "mcp__context7__query_docs",
            },
            "atlassian": {
                "mcp__atlassian__atlassianUserInfo",
                "mcp__atlassian__getAccessibleAtlassianResources",
                "mcp__atlassian__getJiraIssue",
                "mcp__atlassian__searchJiraIssuesUsingJql",
                "mcp__atlassian__getConfluenceContent",
                "mcp__atlassian__searchConfluence",
            },
            "aside": {
                "mcp__aside__browser_profiles",
                "mcp__aside__exec",
                "mcp__aside__repl",
                "mcp__aside__memory_search",
            },
        }
        # Fixed vendor-discovery fixtures, deliberately separate from both
        # configured includes and expected registry names.
        discovered_tools = {
            "notion": (
                "notion-search",
                "notion-fetch",
                "notion-get-self",
                "notion-get-tool-access",
                "notion-query-data-sources",
                "notion-get-comments",
                "create_page",
                "update_page",
                "search_people",
            ),
            "github": (
                "get_me",
                "search_repositories",
                "list_pull_requests",
                "search_pull_requests",
                "pull_request_read",
                "actions_list",
                "actions_get",
                "get_job_logs",
                "create_issue",
                "search_commits",
            ),
            "context7": ("resolve-library-id", "query-docs"),
            "atlassian": (
                "atlassianUserInfo",
                "getAccessibleAtlassianResources",
                "getJiraIssue",
                "searchJiraIssuesUsingJql",
                "getConfluenceContent",
                "searchConfluence",
                "executeWrite",
                "executeDestructive",
            ),
            "aside": ("browser_profiles", "exec", "repl", "memory_search"),
        }
        excluded_mutation_tools = {
            "notion": {"create_page", "update_page"},
            "github": {"create_issue"},
            "atlassian": {"executeWrite", "executeDestructive"},
        }
        excluded_registered_tools = {
            "notion": {
                "mcp__notion__create_page",
                "mcp__notion__update_page",
            },
            "github": {"mcp__github__create_issue"},
            "atlassian": {
                "mcp__atlassian__executeWrite",
                "mcp__atlassian__executeDestructive",
            },
        }
        for name, excluded in excluded_mutation_tools.items():
            self.assertTrue(excluded <= set(discovered_tools[name]))
        write_tools = {
            "create_page",
            "update_page",
            "create_issue",
            "executeWrite",
            "executeDestructive",
            "exec",
            "repl",
        }
        for name, excluded in excluded_registered_tools.items():
            self.assertTrue(excluded.isdisjoint(set(expected_registered_tools[name])))

        servers = self.config["mcp_servers"]
        self.assertEqual(set(servers), set(expected_native_tools))
        notion = servers["notion"]
        github = servers["github"]
        context7 = servers["context7"]
        atlassian = servers["atlassian"]
        aside = servers["aside"]
        self.assertEqual(notion["url"], "https://mcp.notion.com/mcp")
        self.assertEqual(notion["auth"], "oauth")
        self.assertEqual(github["url"], "https://api.githubcopilot.com/mcp/")
        self.assertEqual(github.get("protocol"), "stateless")
        self.assertEqual(context7["url"], "https://mcp.context7.com/mcp")
        self.assertEqual(atlassian["url"], "https://mcp.atlassian.com/v1/mcp/authv2")
        self.assertEqual(atlassian["auth"], "oauth")
        self.assertEqual(aside["trust"], "untrusted")
        self.assertFalse(aside["sampling"]["enabled"])
        for name, server_config in servers.items():
            self.assertCountEqual(
                server_config["tools"]["include"], expected_native_tools[name]
            )
            self.assertEqual(server_config["tools"]["resources"], name == "notion")
            self.assertFalse(server_config["tools"]["prompts"])

        github_headers = github["headers"]
        authorization = github_headers["Authorization"]
        self.assertEqual(authorization, "Bearer ${HERMES_GITHUB_TOKEN}")
        self.assertEqual(github_headers["X-MCP-Readonly"], "true")
        self.assertEqual(
            github_headers["X-MCP-Toolsets"], "context,repos,pull_requests,actions"
        )
        with patch("agent.secret_scope.get_secret", return_value="synthetic-mcp-token"):
            self.assertEqual(
                _interpolate_env_vars(authorization), "Bearer synthetic-mcp-token"
            )

        fake_servers = {}
        for name, tool_names in discovered_tools.items():
            fake_server = SimpleNamespace(
                name=name,
                tool_timeout=30,
                session=SimpleNamespace(),
                initialize_result=SimpleNamespace(
                    capabilities=SimpleNamespace(resources=object(), prompts=object())
                ),
                _tools=[
                    SimpleNamespace(
                        name=tool,
                        description="Synthetic offline discovery fixture",
                        input_schema={"type": "object", "properties": {}},
                        annotations={"readOnlyHint": tool not in write_tools},
                    )
                    for tool in tool_names
                ],
            )
            key = _server_key(name)
            mcp_tool._servers[key] = fake_server
            fake_servers[name] = fake_server

        allowed_resource_tools = {
            "mcp__notion__list_resources",
            "mcp__notion__read_resource",
        }
        expected_mcp_tools = set().union(*expected_registered_tools.values())
        expected_mcp_tools |= allowed_resource_tools
        for name, server_config in servers.items():
            with patch("tools.mcp_tool_registration._write_schema_cache"):
                registered = set(
                    _register_server_tools(name, fake_servers[name], server_config)
                )
            allowed = set(expected_registered_tools[name])
            if name == "notion":
                allowed |= allowed_resource_tools
            self.assertEqual(registered, allowed, f"{name} MCP registration policy")
            if name in excluded_registered_tools:
                self.assertTrue(
                    excluded_registered_tools[name].isdisjoint(registered),
                    f"{name} exposed a mutation tool",
                )

        selection_config = {
            **self.config,
            "mcp_servers": {**servers, "user-local": {"command": "not-invoked"}},
        }
        for platform in ("cli", "slack"):
            with self.subTest(platform=platform):
                selected = _get_platform_tools(selection_config, platform)
                self.assertTrue({"delegation", *servers} <= selected)
                self.assertNotIn("user-local", selected)
                session_env = {
                    "HERMES_GATEWAY_SESSION": "1" if platform == "slack" else "0",
                    "HERMES_INTERACTIVE": "1" if platform == "cli" else "0",
                }
                with patch.dict(os.environ, session_env):
                    definitions = model_tools.get_tool_definitions(
                        enabled_toolsets=sorted(selected),
                        quiet_mode=True,
                        skip_tool_search_assembly=True,
                    )
                exposed = {tool["function"]["name"] for tool in definitions}
                exposed_mcp_tools = {
                    tool for tool in exposed if tool.startswith("mcp__")
                }
                self.assertEqual(exposed_mcp_tools, expected_mcp_tools)
                self.assertIn("delegate_task", exposed)


    def check_platform_tools(self, config, platform):

        import model_tools
        from hermes_cli.tools_config import _get_platform_tools
        # Match the platform's live session; cron is unavailable in batch mode.
        session_env = {
            "HERMES_GATEWAY_SESSION": "1" if platform == "slack" else "0",
            "HERMES_INTERACTIVE": "1" if platform == "cli" else "0",
        }
        # Inspect the raw catalog: tool-search assembly may defer schemas from
        # the initially visible list without removing their availability.
        with patch.dict(os.environ, session_env):
            definitions = model_tools.get_tool_definitions(
                enabled_toolsets=sorted(_get_platform_tools(config, platform)),
                quiet_mode=False, skip_tool_search_assembly=True,
            )
        functions = {tool["function"]["name"]: tool["function"] for tool in definitions}
        required = {
            "delegate_task", "cronjob_manage", "session_search", "memory",
            "skills_list", "skill_view", "skill_manage",
        }
        self.assertFalse(
            required - functions.keys(),
            f"{platform} raw tools missing: {sorted(required - functions.keys())}",
        )
        self.assertFalse({"omp_task", "omp_status", "omp_cancel"} & functions.keys())
        properties = functions["delegate_task"]["parameters"]["properties"]["tasks"]["items"]["properties"]
        self.assertEqual(properties.get("option", {}).get("enum"), ["fast", "deep", "omp"])

    def test_platform_coordinator_raw_tools(self):
        for platform in ("slack", "cli"):
            with self.subTest(platform=platform):
                self.check_platform_tools(self.config, platform)

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

    def resolve_omp(self, config):
        from tools.delegate_tool_routes import resolve_task_routes
        from agent.delegation_registry import backend_status
        backend, error = backend_status("model_map")
        self.assertFalse(error)
        self.assertIsNotNone(backend)
        route = backend.route_task({"option": "omp"}, config["delegation"])
        self.assertEqual(route.get("provider"), "omp-acp", "omp must use omp-acp")
        routes, error = resolve_task_routes(
            [{"goal": "Search current primary sources", "option": "omp"},
             {"goal": "Refuse the removed coder route", "option": "coder"}],
            config["delegation"], None,
        )
        self.assertFalse(error)
        self.assertEqual(len(routes), 2)
        self.assertFalse(routes[0].error, str(routes[0].error))
        self.assertTrue(routes[1].error, "The removed coder option must be refused")
        omp = routes[0]
        credentials = omp.creds
        self.assertEqual(omp.backend, "model_map")
        self.assertEqual(credentials.get("provider"), "omp-acp", "omp must use omp-acp")
        self.assertEqual(credentials.get("model"), omp.routing_cfg["model"])
        command = credentials.get("command")
        self.assertTrue(command, "omp lost its packaged OMP executable")
        self.assertEqual(Path(command).resolve(), Path(self.expected_command).resolve())
        self.assertTrue(os.access(command, os.X_OK))
        settings = config["plugins"]["entries"]["omp-acp-provider"]["settings"]
        self.assertEqual(credentials.get("args"), settings["args"])
        return credentials

    def test_omp_dispatch_and_removed_coder_refusal(self):
        self.resolve_omp(self.config)

    def test_wrong_omp_provider_is_rejected(self):
        config = copy.deepcopy(self.config)
        options = config["delegation"]["backends"]["model_map"]["options"]
        next(option for option in options if option["name"] == "omp")["provider"] = "openai-codex"
        with self.assertRaisesRegex(AssertionError, "omp must use omp-acp"):
            self.resolve_omp(config)

    def test_native_acp_capacity_retries(self):
        from providers import get_provider_profile
        credentials = self.resolve_omp(self.config)
        check_acp_retries(get_provider_profile("omp-acp"), credentials["command"], credentials["args"], self.root)


if __name__ == "__main__":
    INPUTS = sys.argv[1:]
    if len(INPUTS) != 6:
        raise SystemExit("usage: test_packaged_runtime.py CONFIG PROVIDER DELEGATION VERSION OMP LAUNCHD_PLIST")
    unittest.main(argv=[sys.argv[0]], verbosity=2)
