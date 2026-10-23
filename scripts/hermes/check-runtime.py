#!/usr/bin/env python3
"""Check packaged Hermes identity and OMP tool exposure without credentials or model calls."""

import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    defaults_path, plugin_source, expected_version = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="hermes-runtime-check-") as directory:
        root = Path(directory)
        home = root / ".hermes/profiles/omp-worker"
        home.mkdir(parents=True, mode=0o700)
        os.environ["HOME"] = str(root)
        os.environ["HERMES_HOME"] = str(home)
        os.environ["HERMES_REAL_HOME"] = str(root)

        from hermes_cli.version_info import get_version_info

        version = get_version_info().base_version
        if version != expected_version:
            raise RuntimeError(f"Packaged Hermes reports {version}, expected {expected_version}.")

        from ruamel.yaml import YAML

        config = YAML(typ="safe").load(Path(defaults_path).read_text())
        config["plugins"]["entries"]["omp-acp-delegator"]["settings"]["allowed_roots"] = [str(home)]
        (home / "config.yaml").write_text(json.dumps(config))
        (home / "config.yaml").chmod(0o600)
        (home / "plugins").mkdir()
        (home / "plugins/omp-acp-delegator").symlink_to(plugin_source, target_is_directory=True)

        from hermes_cli.plugins import get_plugin_manager

        manager = get_plugin_manager()
        manager.discover_and_load()
        try:
            import model_tools
            from hermes_cli.tools_config import _get_platform_tools
            from tools.tool_search import dispatch_tool_search

            definitions = model_tools.get_tool_definitions(
                enabled_toolsets=sorted(_get_platform_tools(config, "slack")),
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
            names = {tool["function"]["name"] for tool in definitions}
            missing = {"omp_task", "omp_status", "omp_cancel"} - names
            if missing:
                raise RuntimeError(f"OMP tools missing from model definitions: {sorted(missing)}")
            search = json.loads(dispatch_tool_search(
                {"queries": ["omp_task", "omp_status"]}, current_tool_defs=definitions,
            ))
            for result in search["results"]:
                if result["query"] not in result["matches"]:
                    raise RuntimeError(f"Tool search did not expose {result['query']}.")
            print(f"Hermes {version}: OMP tool definitions and tool_search exposure verified.")
        finally:
            manager.unload()


if __name__ == "__main__":
    main()
