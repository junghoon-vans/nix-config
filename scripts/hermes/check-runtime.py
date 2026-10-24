#!/usr/bin/env python3
"""Check packaged Hermes and mixed delegation routes without credentials or model calls."""

import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    defaults_path, provider_source, delegation_source, expected_version = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="hermes-runtime-check-") as directory:
        root = Path(directory)
        home = root / ".hermes/profiles/omp-worker"
        home.mkdir(parents=True, mode=0o700)
        os.environ["HOME"] = str(root)
        os.environ["HERMES_HOME"] = str(home)
        os.environ["HERMES_REAL_HOME"] = str(root)

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
            expected_command = os.environ["HERMES_OMP_ACP_COMMAND"]
            if not command or Path(command).resolve() != Path(expected_command).resolve():
                raise RuntimeError("The coder route lost the packaged OMP executable.")
            if not os.access(command, os.X_OK) or credentials.get("args") != ["acp"]:
                raise RuntimeError("The coder route cannot launch the packaged OMP ACP server.")
            print(
                f"Hermes {version}: fast/deep OpenAI routes, coder OMP ACP route, "
                "unknown-route refusal and delegate_task exposure verified."
            )
        finally:
            manager.unload()


if __name__ == "__main__":
    main()
