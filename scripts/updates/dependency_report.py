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


def root_inputs(document):
    """Resolve root input aliases, including root-relative follows paths."""
    nodes = document.get("nodes", {})
    root = document.get("root", "root")

    def resolve(reference, seen):
        if isinstance(reference, str):
            return reference
        path = tuple(reference)
        if path in seen:
            raise ValueError("Cyclic flake input follows path")
        current = root
        for name in path:
            target = nodes[current]["inputs"][name]
            current = resolve(target, seen | {path})
        return current

    return {name: resolve(target, set())
            for name, target in nodes.get(root, {}).get("inputs", {}).items()}


def flake_rows(before, after):
    old, new = before.get("nodes", {}), after.get("nodes", {})
    first_inputs, last_inputs = root_inputs(before), root_inputs(after)
    pairs = [(f"flake input {name}", old.get(first_inputs.get(name)),
              new.get(last_inputs.get(name)), "direct")
             for name in sorted(first_inputs.keys() | last_inputs.keys())]
    # Node IDs are lockfile-local. Match direct inputs by alias across snapshots.
    old_transitive = old.keys() - set(first_inputs.values())
    new_transitive = new.keys() - set(last_inputs.values())
    pairs.extend((f"transitive flake node {name}",
                  old.get(name) if name in old_transitive else None,
                  new.get(name) if name in new_transitive else None, "transitive")
                 for name in sorted(old_transitive | new_transitive))
    rows = []
    for name, a, b, scope in pairs:
        # Input-edge changes alone are not updates to the parent's own pin.
        if flake_pin(a) == flake_pin(b) and (a or {}).get("original") == (b or {}).get("original"):
            continue
        if not ((a or {}).get("locked") or (b or {}).get("locked")):
            continue
        first, last = (a or {}).get("locked"), (b or {}).get("locked")
        source = last or first or {}
        repository = (
            f"{source['owner']}/{source['repo']}"
            if source.get("type") == "github" and source.get("owner") and source.get("repo") else None
        )
        item = row(name, flake_pin(a), flake_pin(b), repository,
                   (first or {}).get("rev"), (last or {}).get("rev"))
        item["scope"] = scope
        if item["change"] == "Unchanged":
            item["change"] = "Input metadata changed (locked pin unchanged)"
        rows.append(item)
    return rows


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
                rows.extend(flake_rows(old, new))
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


def render_title(rows):
    """Name changed direct dependencies; transitive lock detail belongs in the body."""
    names = []
    for item in rows:
        if item.get("scope") == "transitive" or item["change"] in ("Unchanged", "Metadata unavailable"):
            continue
        name = item["dependency"]
        if name.startswith(("APM ref ", "APM lock ")):
            name = re.sub(r"^APM (?:ref|lock) ", "APM ", name)
            name = name.replace("https://github.com/", "").replace(".git /", " /")
        name = " ".join(name.split())
        if name not in names:
            names.append(name)
    if not names and any(item.get("scope") == "transitive" for item in rows):
        names.append("transitive flake locks")
    if not names:
        raise ValueError("No dependency changes; refusing an unchanged update title")
    prefix = "chore(deps): update "
    # GitHub limits PR titles to 256 characters. Keep full identities in the body.
    for count in range(len(names), 0, -1):
        suffix = f" (+{len(names) - count} more changed dependencies)" if count < len(names) else ""
        title = prefix + ", ".join(names[:count]) + suffix
        if len(title) <= 256:
            return title
    return prefix + f"{len(names)} changed dependencies"


def render_body(rows):
    direct = [item for item in rows if item.get("scope") != "transitive"]
    transitive = [item for item in rows if item.get("scope") == "transitive"]
    sections = ["## Dependency versions and pins"]
    if direct:
        sections.extend(["### Direct dependency updates", render_table(direct)])
    if transitive:
        sections.extend([
            "### Transitive flake lock changes",
            "These are dependency lock nodes, not updates to same-named root inputs.",
            render_table(transitive),
        ])
    return "\n\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", action="store_true", help="Print a changed-dependency title instead of the body")
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
    try:
        title = render_title(rows)
    except ValueError as error:
        parser.error(str(error))
    if args.title:
        print(title)
        return
    context = sys.stdin.read()
    print(context.rstrip() + "\n\n" + render_body(rows))


if __name__ == "__main__":
    main()
