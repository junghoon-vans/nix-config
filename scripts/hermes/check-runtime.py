#!/usr/bin/env python3
"""Check packaged Hermes and mixed delegation routes without credentials or model calls."""
from contextlib import closing

import json
import os
from pathlib import Path
import subprocess
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
        repository = root / "repositories" / "probe"
        repository.mkdir(parents=True)
        for arguments in (
            ["init", "--quiet"],
            ["-c", "user.name=Hermes runtime check", "-c", "user.email=check@example.invalid",
             "commit", "--allow-empty", "--quiet", "-m", "probe"],
        ):
            subprocess.run(["git", "-C", str(repository), *arguments], check=True)
        config["delegation"]["backends"]["omp-worktree"]["allowed_roots"] = [str(repository.parent)]
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
            from providers import get_provider_profile

            if get_provider_profile("omp-acp") is None:
                raise RuntimeError("The OMP model provider was not discovered.")

            backend, error = backend_status("omp-worktree")
            if error or backend is None:
                raise RuntimeError(f"omp-worktree is unavailable: {error}")
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
            if properties.get("repository", {}).get("type") != "string":
                raise RuntimeError("delegate_task must expose a structured coder repository.")
            delegation = config["delegation"]
            if delegation["backend"] != "omp-worktree":
                raise RuntimeError("The active delegation backend must be omp-worktree.")
            for name in ("fast", "deep"):
                route = backend.route_task({"option": name}, delegation)
                if route.get("provider") != "openai-codex" or route.get("base_url"):
                    raise RuntimeError(f"{name} must route directly to the OpenAI provider.")
            routes, error = resolve_task_routes(
                [
                    {"goal": "Inspect the repository", "option": "coder", "repository": str(repository)},
                    {"goal": "Refuse an unknown route", "option": "unknown-route"},
                    {"goal": "Refuse a missing repository", "option": "coder"},
                    {"goal": "Refuse a repository outside the allowed roots", "option": "coder",
                     "repository": str(root)},
                ],
                delegation,
                None,
            )
            if error or len(routes) != 4 or routes[0].error or any(not route.error for route in routes[1:]):
                raise RuntimeError(f"Coder dispatch or unknown-route refusal failed: {error or routes!r}")
            coder = routes[0]
            credentials = coder.creds
            if coder.backend != "omp-worktree" or credentials.get("provider") != "omp-acp":
                raise RuntimeError("coder did not resolve to the OMP ACP provider.")
            if credentials.get("model") != coder.routing_cfg["model"]:
                raise RuntimeError("The coder route lost its selected OMP model.")
            command = credentials.get("command")
            expected_command = os.environ["HERMES_OMP_ACP_COMMAND"]
            if not command or Path(command).resolve() != Path(expected_command).resolve():
                raise RuntimeError("The coder route lost the packaged OMP executable.")
            if not os.access(command, os.X_OK) or credentials.get("args") != ["acp"]:
                raise RuntimeError("The coder route cannot launch the packaged OMP ACP server.")
            from run_agent import AIAgent

            with closing(AIAgent(
                **credentials, enabled_toolsets=[], quiet_mode=True, skip_memory=True,
                skip_background_review=True, skip_context_files=True, max_iterations=1,
            )) as child:
                request = child._build_api_kwargs(
                    [{"role": "user", "content": "Inspect this repository"}], tools_for_api=[],
                )
                metadata = request["extra_body"]["hermes_omp_acp"]
                if Path(metadata["repository"]).resolve() != repository.resolve():
                    raise RuntimeError("The coder request lost its selected repository.")
                try:
                    child.client.chat.completions.create(
                        model=credentials["model"], messages=[], timeout=1,
                    )
                except ValueError:
                    pass
                else:
                    raise RuntimeError("OMP accepted an unisolated request without workspace metadata.")
            print(
                f"Hermes {version}: fast/deep OpenAI routes, isolated coder OMP ACP route, "
                "repository enforcement, request metadata and delegate_task exposure verified."
            )
        finally:
            manager.unload()


if __name__ == "__main__":
    main()
