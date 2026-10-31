"""Compare authoritative dependency declarations without resolving or updating them."""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from version_table import render_table

SPEC = importlib.util.spec_from_file_location(
    "fixed_release", Path(__file__).with_name("update-fixed-release.py")
)
fixed_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixed_release)


PATHS = (
    "flake.lock", "release-pins.json", "modules/languages/gno.nix",
    "home/.omp/agent/mcp.json", "apm.yml", "apm.lock.yaml", "modules/paseo-plugins.json",
)


def compare(repository, previous, current):
    if not repository or not previous or not current or previous == current:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return None
    return f"https://github.com/{repository}/compare/{quote(str(previous), safe='')}...{quote(str(current), safe='')}"


def row(name, old, new, repository=None, old_ref=None, new_ref=None):
    return {
        "dependency": name, "previous": old, "next": new,
        "change": "Metadata unavailable" if old is None and new is None else
                  "Added" if old is None else "Removed" if new is None else
                  "Unchanged" if old == new else "Updated",
        "compare": compare(repository, old_ref, new_ref),
    }


def pin(value):
    if value is None:
        return None
    return "; ".join(f"{key}: {item if isinstance(item, str) else json.dumps(item, sort_keys=True)}"
                     for key, item in sorted(value.items())) or "Metadata unavailable"


def flake_pin(node):
    if node is None:
        return None
    locked = dict(node.get("locked", {}))
    if reference := node.get("original", {}).get("ref"):
        locked["declared ref"] = reference
    return pin(locked)


def collect_rows(before, after):
    """Return all changed pins, plus unchanged members of grouped Gno/plugin updates."""
    rows = []
    for path in PATHS:
        old_text, new_text = before.get(path), after.get(path)
        if old_text == new_text:
            continue
        if path.endswith(".json") or path == "flake.lock":
            old = json.loads(old_text) if old_text else {}
            new = json.loads(new_text) if new_text else {}
            if path == "flake.lock":
                old, new = old.get("nodes", {}), new.get("nodes", {})
                for name in sorted(old.keys() | new.keys()):
                    a, b = old.get(name), new.get(name)
                    if a == b or not ((a or {}).get("locked") or (b or {}).get("locked")):
                        continue
                    first, last = (a or {}).get("locked"), (b or {}).get("locked")
                    source = last or first or {}
                    repository = (
                        f"{source['owner']}/{source['repo']}"
                        if source.get("type") == "github" and source.get("owner") and source.get("repo") else None
                    )
                    item = row(f"flake input {name}", flake_pin(a), flake_pin(b), repository,
                               (first or {}).get("rev"), (last or {}).get("rev"))
                    if item["change"] == "Unchanged":
                        item["change"] = "Input metadata changed (locked pin unchanged)"
                    rows.append(item)
            elif path == "home/.omp/agent/mcp.json":
                old, new = old.get("mcpServers", {}), new.get("mcpServers", {})
                for name in sorted(old.keys() | new.keys()):
                    if old.get(name) != new.get(name):
                        # Exact launch specs include npm version pins, without assuming SemVer.
                        def launch(server):
                            if server is None:
                                return None
                            return pin({key: server[key] for key in ("command", "args", "url") if key in server})
                        rows.append(row(f"npm MCP {name}", launch(old.get(name)), launch(new.get(name))))
            else:
                grouped = path == "modules/paseo-plugins.json"
                for name in sorted(old.keys() | new.keys()):
                    a, b = old.get(name), new.get(name)
                    if a == b and not grouped:
                        continue
                    source = b or a or {}
                    if path == "release-pins.json":
                        repository, prefix, *_ = fixed_release.SPECS.get(name, (None, "", "", False))
                        rows.append(row(name, pin(a), pin(b), repository,
                                        prefix + a["version"] if a and a.get("version") else None,
                                        prefix + b["version"] if b and b.get("version") else None))
                    else:
                        rows.append(row(name, pin(a), pin(b), source.get("repository"),
                                        (a or {}).get("revision"), (b or {}).get("revision")))
        elif path == "modules/languages/gno.nix":
            for name, repository in (("gno", "gnolang/gno"), ("gnopls", "gnoverse/gnopls")):
                def source(text):
                    values = dict(re.findall(r'^\s*(' + name + r'(?:Rev|Hash|VendorHash)) = "([^"\n]+)";', text or "", re.MULTILINE))
                    return {key.removeprefix(name): value for key, value in values.items()} or None
                a, b = source(old_text), source(new_text)
                rows.append(row(name, pin(a), pin(b), repository,
                                (a or {}).get("Rev"), (b or {}).get("Rev")))
        else:
            # Only tagged-skills uses YAML; its CI already installs the pinned parser.
            import yaml
            old = yaml.safe_load(old_text) if old_text else {}
            new = yaml.safe_load(new_text) if new_text else {}
            if path == "apm.yml":
                def declarations(document):
                    return {(entry.get("git", "local"), entry.get("path", ""), entry.get("alias", "")): entry.get("ref")
                            for entry in document.get("dependencies", {}).get("apm", [])}
                a, b = declarations(old), declarations(new)
                for identity in sorted(a.keys() | b.keys()):
                    if a.get(identity) == b.get(identity):
                        continue
                    repository = identity[0].removeprefix("https://github.com/").removesuffix(".git")
                    rows.append(row("APM ref " + " / ".join(filter(None, identity)), a.get(identity), b.get(identity),
                                    repository, a.get(identity), b.get(identity)))
            else:
                def dependencies(document):
                    return {(entry.get("repo_url", ""), entry.get("virtual_path", ""), entry.get("alias", ""), entry.get("local_path", "")): entry
                            for entry in document.get("dependencies", [])}
                a, b = dependencies(old), dependencies(new)
                for identity in sorted(a.keys() | b.keys()):
                    first, last = a.get(identity), b.get(identity)
                    if first == last:
                        continue
                    def resolved(entry):
                        if entry is None:
                            return None
                        fields = {key: entry[key] for key in ("version", "resolved_ref", "resolved_commit", "content_hash") if key in entry}
                        return pin(fields)
                    item = row("APM lock " + " / ".join(filter(None, identity)), resolved(first), resolved(last), identity[0],
                               (first or {}).get("resolved_commit"), (last or {}).get("resolved_commit"))
                    if item["change"] == "Unchanged":
                        item["change"] = "Lock metadata changed (pin unchanged)"
                    rows.append(item)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    before, after = {}, {}
    for path in args.paths:
        if path not in PATHS:
            continue  # Generated docs are context, not another dependency owner.
        result = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, text=True)
        if result.returncode not in (0, 128):
            result.check_returncode()
        if result.returncode == 0:
            before[path] = result.stdout
        if Path(path).exists():
            after[path] = Path(path).read_text()
    rows = collect_rows(before, after)
    if not rows:
        parser.error("Changed update paths contain no reportable dependency metadata; refusing an incomplete PR body")
    context = sys.stdin.read()
    print(context.rstrip() + "\n\n## Dependency versions and pins\n\n" + render_table(rows))


if __name__ == "__main__":
    main()
