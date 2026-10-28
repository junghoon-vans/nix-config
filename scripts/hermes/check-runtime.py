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


def check_native_mcp(config):
    """Offline registration smoke using synthetic discovery, never vendor connections."""
    from types import SimpleNamespace
    from unittest.mock import patch

    import model_tools
    from hermes_cli.tools_config import _get_platform_tools
    from tools import mcp_tool
    from tools.mcp_tool_config import _interpolate_env_vars
    from tools.mcp_tool_registration import _register_server_tools
    from tools.mcp_tool_scope import _server_key

    servers = config["mcp_servers"]
    if set(servers) != {"notion", "github"}:
        raise RuntimeError("Only Notion and GitHub should be declared natively.")
    notion, github = servers["notion"], servers["github"]
    if notion["url"] != "https://mcp.notion.com/mcp" or notion["auth"] != "oauth":
        raise RuntimeError("Notion must use its official OAuth endpoint.")
    if github["url"] != "https://api.githubcopilot.com/mcp/":
        raise RuntimeError("GitHub must use its official hosted endpoint.")
    authorization = github["headers"]["Authorization"]
    if authorization != "Bearer ${HERMES_GITHUB_TOKEN}":
        raise RuntimeError("GitHub credentials must remain a runtime placeholder.")
    with patch("agent.secret_scope.get_secret", return_value="synthetic-mcp-token"):
        if _interpolate_env_vars(authorization) != "Bearer synthetic-mcp-token":
            raise RuntimeError("GitHub runtime token expansion failed.")
    if github["headers"]["X-MCP-Readonly"] != "true":
        raise RuntimeError("GitHub must request read-only server tools.")

    expected = set()
    for name, server_config in servers.items():
        # A new mutating vendor tool must not silently become available.
        native_names = [*server_config["tools"]["include"], "create_unapproved_content"]
        server = SimpleNamespace(
            name=name,
            tool_timeout=30,
            session=SimpleNamespace(),
            initialize_result=SimpleNamespace(
                capabilities=SimpleNamespace(resources=object(), prompts=object())
            ),
            _tools=[
                SimpleNamespace(
                    name=tool, description="Synthetic offline discovery fixture",
                    input_schema={"type": "object", "properties": {}},
                    annotations={"readOnlyHint": tool != "create_unapproved_content"},
                )
                for tool in native_names
            ],
        )
        # Publish only synthetic sessions in this build's isolated profile.
        mcp_tool._servers[_server_key(name)] = server
        with patch("tools.mcp_tool_registration._write_schema_cache"):
            registered = set(_register_server_tools(name, server, server_config))
        expected_native = {
            f"mcp__{name}__{tool.replace('-', '_')}"
            for tool in server_config["tools"]["include"]
        }
        utilities = {f"mcp__{name}__list_resources", f"mcp__{name}__read_resource"} if name == "notion" else set()
        if registered != expected_native | utilities:
            raise RuntimeError(f"{name}: native allowlist or utility policy was not enforced.")
        expected |= registered

    for platform in ("cli", "slack"):
        # Local MCPs remain user-managed but must not leak into these platform allowlists.
        selection_config = {
            **config,
            "mcp_servers": {**servers, "user-local": {"command": "not-invoked"}},
        }
        selected = _get_platform_tools(selection_config, platform)
        if not {"delegation", "notion", "github"} <= selected or "user-local" in selected:
            raise RuntimeError(f"{platform}: incorrect delegation/native MCP selection.")
        definitions = model_tools.get_tool_definitions(
            enabled_toolsets=sorted(selected), quiet_mode=True, skip_tool_search_assembly=True,
        )
        exposed = {tool["function"]["name"] for tool in definitions}
        if not expected | {"delegate_task"} <= exposed:
            raise RuntimeError(f"{platform}: declared MCP tools or delegation are missing.")
        if any("create_unapproved_content" in tool for tool in exposed):
            raise RuntimeError(f"{platform}: an unapproved write tool escaped filtering.")
    print("Offline synthetic MCP discovery: CLI/Slack allowlists, Notion resources, "
          "GitHub placeholder expansion and write-tool exclusion verified; no vendor connection.")


def main():
    defaults_path, provider_source, delegation_source, expected_version, expected_command = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="hermes-runtime-check-") as directory:
        root = Path(directory)
        home = root / ".hermes/profiles/omp-worker"
        home.mkdir(parents=True, mode=0o700)
        os.environ["HOME"] = str(root)
        os.environ["HERMES_HOME"] = str(home)
        os.environ["HERMES_REAL_HOME"] = str(root)
        for name in ("HERMES_OMP_ACP_COMMAND", "HERMES_OMP_ACP_ARGS", "HERMES_OMP_ACP_MCP_ENABLED"):
            os.environ.pop(name, None)
        check_provider_dependencies(provider_source)

        from hermes_cli.version_info import get_version_info
        from ruamel.yaml import YAML

        version = get_version_info().base_version
        if version != expected_version:
            raise RuntimeError(f"Packaged Hermes reports {version}, expected {expected_version}.")
        config = YAML(typ="safe").load(Path(defaults_path).read_text())
        (home / "config.yaml").write_text(json.dumps(config))
        (home / "config.yaml").chmod(0o600)
        (home / "plugins").mkdir()
        for name, source in (
            ("omp-acp-provider", provider_source),
            ("advanced-delegation", delegation_source),
        ):
            (home / "plugins" / name).symlink_to(source, target_is_directory=True)

        from hermes_cli.plugins import get_plugin_manager

        manager = get_plugin_manager()
        try:
            manager.discover_and_load()
            from agent.delegation_registry import backend_status
            import model_tools
            from hermes_cli.tools_config import _get_platform_tools
            from tools.delegate_tool_routes import resolve_task_routes

            backend, error = backend_status("model_map")
            if error or backend is None:
                raise RuntimeError(f"model_map is unavailable: {error}")
            check_native_mcp(config)
            definitions = model_tools.get_tool_definitions(
                enabled_toolsets=sorted(_get_platform_tools(config, "slack")),
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
            functions = {tool["function"]["name"]: tool["function"] for tool in definitions}
            if "delegate_task" not in functions:
                raise RuntimeError("delegate_task is missing from Slack tools.")
            obsolete = {"omp_task", "omp_status", "omp_cancel"} & functions.keys()
            if obsolete:
                raise RuntimeError(f"Obsolete OMP tools remain exposed: {sorted(obsolete)}")
            properties = functions["delegate_task"]["parameters"]["properties"]["tasks"]["items"]["properties"]
            if properties.get("option", {}).get("enum") != ["fast", "deep", "coder"]:
                raise RuntimeError("delegate_task must offer the fast, deep and coder routes.")
            delegation = config["delegation"]
            if delegation["backend"] != "model_map":
                raise RuntimeError("The active delegation backend must be model_map.")
            for name in ("fast", "deep"):
                route = backend.route_task({"option": name}, delegation)
                if route.get("provider") != "openai-codex" or route.get("base_url"):
                    raise RuntimeError(f"{name} must route directly to the OpenAI provider.")
            routes, error = resolve_task_routes(
                [
                    {"goal": "Inspect the repository", "option": "coder"},
                    {"goal": "Refuse an unknown route", "option": "unknown-route"},
                ],
                delegation,
                None,
            )
            if error or len(routes) != 2 or routes[0].error or not routes[1].error:
                raise RuntimeError(f"Coder dispatch or unknown-route refusal failed: {error or routes!r}")
            coder = routes[0]
            credentials = coder.creds
            if coder.backend != "model_map" or credentials.get("provider") != "omp-acp":
                raise RuntimeError("coder did not resolve to the OMP ACP provider.")
            if credentials.get("model") != coder.routing_cfg["model"]:
                raise RuntimeError("The coder route lost its selected OMP model.")
            command = credentials.get("command")
            settings = config["plugins"]["entries"]["omp-acp-provider"]["settings"]
            if not command or Path(command).resolve() != Path(expected_command).resolve():
                raise RuntimeError("The coder route lost the packaged OMP executable.")
            if not os.access(command, os.X_OK) or credentials.get("args") != settings["args"]:
                raise RuntimeError("The coder route cannot launch the packaged OMP ACP server.")
            from providers import get_provider_profile

            check_acp_retries(get_provider_profile("omp-acp"), command, credentials["args"], root)
            print(
                f"Hermes {version}: fast/deep OpenAI routes, coder OMP ACP route, "
                "unknown-route refusal and delegate_task exposure verified."
            )
        finally:
            manager.unload()


if __name__ == "__main__":
    main()
