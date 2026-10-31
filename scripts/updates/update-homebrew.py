#!/usr/bin/env python3
"""Update Homebrew tap pins and compare versions of declared packages."""

import argparse
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess

TABLE_SPEC = importlib.util.spec_from_file_location(
    "version_table", Path(__file__).with_name("version_table.py")
)
VERSION_TABLE = importlib.util.module_from_spec(TABLE_SPEC)
TABLE_SPEC.loader.exec_module(VERSION_TABLE)


TAPS = {"homebrew-core": "Formula", "homebrew-cask": "Casks", "hashicorp-tap": "Formula"}


def prefetch(locked):
    reference = (
        f"github:{locked['owner']}/{locked['repo']}/{locked['rev']}"
        f"?narHash={locked['narHash']}"
    )
    result = subprocess.run(
        ["nix", "flake", "prefetch", "--json", reference],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return Path(json.loads(result.stdout)["storePath"])


def packages(source, directory):
    result = {path.stem: path for path in (source / directory).rglob("*.rb")}
    if directory == "Formula":
        for alias in (source / "Aliases").glob("*"):
            if alias.is_symlink() and alias.is_file():
                result[alias.name] = alias.resolve()
    return result


def inventory():
    result = subprocess.run(
        [
            "nix", "eval", "--impure", "--json", "--no-write-lock-file", "--expr",
            "import ./scripts/updates/homebrew-inventory.nix "
            "(builtins.getFlake (\"git+file:\" + toString ./. + \"?shallow=1\"))",
        ],
        check=True, stdout=subprocess.PIPE, text=True,
    )
    return json.loads(result.stdout)


def brew_environment():
    return {
        **os.environ,
        "HOMEBREW_DEVELOPER": "1",
        "HOMEBREW_NO_AUTO_UPDATE": "1",
        "HOMEBREW_NO_INSTALL_FROM_API": "1",
    }


def versions(tap, paths, brew="brew"):
    if not paths:
        return {}
    result = subprocess.run(
        [str(brew), "ruby", str(Path(__file__).with_name("homebrew-versions.rb"))],
        input=json.dumps({
            name: {"tap": tap, "path": str(path)} for name, path in paths.items()
        }),
        env=brew_environment(),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return json.loads(result.stdout)


def candidate_versions(tap, paths, brew):
    try:
        return versions(tap, paths, brew)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        message = (
            f"Unable to parse declared candidate packages from {tap} with the selected "
            "Homebrew runtime; update the brew-src pin to a compatible Homebrew version."
        )
        if detail:
            message += f"\n{detail.strip()}"
        raise RuntimeError(message) from error


def verify_brew_version(brew, lock):
    expected = lock["nodes"]["brew-src"]["original"]["ref"]
    try:
        result = subprocess.run(
            [str(brew), "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=brew_environment(),
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None)
        message = f"Unable to query selected Homebrew runtime version via {brew} --version."
        if detail:
            message += f"\n{detail.strip()}"
        raise RuntimeError(message) from error
    match = re.search(r"^Homebrew (\S+)", result.stdout or "", re.MULTILINE)
    if match is None:
        raise RuntimeError(f"Unable to determine Homebrew runtime version from {brew} --version.")
    actual = match.group(1)
    if actual != expected:
        raise RuntimeError(
            f"Selected Homebrew runtime is {actual}, but flake.lock pins brew-src to "
            f"{expected}; update the brew-src pin to match before updating Homebrew taps."
        )
    return actual


_DESCRIPTION_ONLY = re.compile(
    r"""^\s{2}(?P<field>desc|homepage|name)\s+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*$"""
)
_DEPENDENCY_CALL = re.compile(r"^\s*(?:depends_on|uses_from_macos)\b(.*)$")
_DEPENDENCY_STRING = re.compile(r"""["']([^"']+)["']""")
_PACKAGE_NAME = re.compile(r"[A-Za-z0-9@+_.-]+(?:/[A-Za-z0-9@+_.-]+)*\Z")
_SYSTEM_DEPENDENCY = re.compile(
    r"^\s*(?::(?:macos|linux|x11|java)\b|(?:macos|arch|xcode|linux)\s*:)",
    re.IGNORECASE,
)
_TAP_ALIASES = {
    "homebrew/core": "homebrew-core",
    "homebrew/cask": "homebrew-cask",
    "hashicorp/tap": "hashicorp-tap",
    "core": "homebrew-core",
    "cask": "homebrew-cask",
}
_NON_BUILD_RUBY_DIRS = {".github", "test", "tests", "spec", "specs"}


def normalized_recipe(path, ignore_metadata=True):
    source_lines = path.read_text().splitlines()
    # Line-based metadata removal is unsafe inside Ruby multiline literals:
    # apparent comments/DSL calls there are actual patch or installed-file bytes.
    # Fall back to exact content whenever lexical context is uncertain.
    source = "\n".join(source_lines)
    if re.search(r"<<[-~]?\s*['\"`]?[A-Za-z_]|%[qQwWiIxrs]?[({\[<|!/]|`", source) or any(
        len(re.findall(r"(?<!\\)[\"']", line)) % 2
        for line in source_lines
        if not line.lstrip().startswith("#")
    ):
        return source
    metadata_references = {
        field: any(
            re.search(rf"\b{field}\b", line)
            and not _DESCRIPTION_ONLY.fullmatch(line)
            and not line.lstrip().startswith("#")
            for line in source_lines
        )
        for field in ("desc", "homepage", "name")
    }
    lines = []
    for line in source_lines:
        if line.lstrip().startswith("#"):
            continue
        metadata = _DESCRIPTION_ONLY.fullmatch(line) if ignore_metadata else None
        if metadata and not metadata_references[metadata["field"]]:
            continue
        line = line.rstrip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def dependency_references(path):
    dependencies = set()
    unresolved = False
    if path is None:
        return dependencies, unresolved

    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _DEPENDENCY_CALL.match(line)
        if match is None:
            if re.search(r"\b(?:depends_on|uses_from_macos)\b", line):
                unresolved = True
            continue
        if _SYSTEM_DEPENDENCY.match(match.group(1)):
            continue
        values = {
            value for value in _DEPENDENCY_STRING.findall(match.group(1))
            if _PACKAGE_NAME.fullmatch(value)
        }
        dependencies.update(values)
        if not values and not _SYSTEM_DEPENDENCY.match(match.group(1)):
            unresolved = True
    return dependencies, unresolved


def dependency_target(name, package_maps):
    parts = name.split("/")
    if len(parts) > 1:
        tap = _TAP_ALIASES.get("/".join(parts[:-1]))
        if tap is None or parts[-1] not in package_maps[tap]:
            return None
        return tap, parts[-1]

    for tap in ("homebrew-core", "hashicorp-tap", "homebrew-cask"):
        if name in package_maps[tap]:
            return tap, name
    return None


def dependency_graph(old_packages, new_packages):
    package_maps = {}
    for tap in TAPS:
        package_maps[tap] = dict(old_packages[tap])
        package_maps[tap].update(new_packages[tap])

    graph = {}
    unresolved = set()
    for tap in TAPS:
        package_names = old_packages[tap].keys() | new_packages[tap].keys()
        for name in package_names:
            node = (tap, name)
            dependencies = set()
            unknown = False
            for path in (old_packages[tap].get(name), new_packages[tap].get(name)):
                references, unresolved_names = dependency_references(path)
                dependencies.update(references)
                unknown |= unresolved_names

            targets = set()
            for dependency in dependencies:
                target = dependency_target(dependency, package_maps)
                if target is None:
                    unknown = True
                else:
                    targets.add(target)
            graph[node] = targets
            if unknown:
                unresolved.add(node)
    return graph, unresolved, package_maps


def helper_files(source, package_paths):
    package_paths = set(package_paths.values())
    files = {}
    for path in source.rglob("*.rb"):
        relative = path.relative_to(source)
        if path in package_paths or any(part in _NON_BUILD_RUBY_DIRS for part in relative.parts):
            continue
        content = normalized_recipe(path, ignore_metadata=False)
        if content:
            files[relative.as_posix()] = content
    return files


def compare_url(tap, old, new):
    return (
        f"https://github.com/{new['owner']}/{new['repo']}/compare/"
        f"{old['rev']}...{new['rev']}"
    )


def analyze(before, after, declared, brew="brew"):
    lines = [
        "## Homebrew tap update",
        "",
        "Updates only " + ", ".join(f"`{tap}`" for tap in TAPS) + " in `flake.lock`.",
        "Package rows include only Homebrew packages declared by the Nix host configurations.",
        "Versions come from the pinned definitions, not the currently installed packages.",
        "Formula versions include Homebrew revisions (`_N`); cask versions target Apple Silicon.",
        "No local Homebrew update, upgrade, cleanup, or activation is performed.",
    ]
    old_sources = {}
    new_sources = {}
    old_packages = {}
    new_packages = {}
    old_helpers = {}
    new_helpers = {}
    candidate_versions_by_tap = {}
    for tap, directory in TAPS.items():
        old = before["nodes"][tap]["locked"]
        new = after["nodes"][tap]["locked"]
        new_sources[tap] = prefetch(new)
        old_sources[tap] = new_sources[tap] if old == new else prefetch(old)
        old_packages[tap] = packages(old_sources[tap], directory)
        new_packages[tap] = packages(new_sources[tap], directory)
        old_helpers[tap] = helper_files(old_sources[tap], old_packages[tap])
        new_helpers[tap] = helper_files(new_sources[tap], new_packages[tap])
        candidate_paths = {
            name: new_packages[tap][name]
            for name in declared[tap]
            if name in new_packages[tap]
        }
        candidate_versions_by_tap[tap] = candidate_versions(tap, candidate_paths, brew)

    changed_recipes = {
        (tap, name)
        for tap in TAPS
        for name in old_packages[tap].keys() | new_packages[tap].keys()
        if name not in old_packages[tap]
        or name not in new_packages[tap]
        or normalized_recipe(old_packages[tap][name])
        != normalized_recipe(new_packages[tap][name])
    }
    changed_helpers = {
        tap
        for tap in TAPS
        if old_helpers[tap] != new_helpers[tap]
    }
    graph, unresolved, package_maps = dependency_graph(old_packages, new_packages)

    package_impacts = {}
    relevant_taps = set()
    for tap in TAPS:
        for name in sorted(set(declared[tap])):
            root = (tap, name)
            if name not in package_maps[tap]:
                continue
            reachable = set()
            pending = [root]
            uncertain = False
            while pending:
                node = pending.pop()
                if node in reachable:
                    continue
                reachable.add(node)
                uncertain |= node in unresolved
                pending.extend(graph.get(node, ()))

            known_changes = reachable & changed_recipes
            known_helper_taps = {
                node_tap for node_tap, _package in reachable
                if node_tap in changed_helpers
            }
            uncertain_changes = uncertain and (
                bool(changed_recipes - known_changes)
                or bool(changed_helpers - known_helper_taps)
            )
            impacted_changes = set(known_changes)
            impacted_helper_taps = set(known_helper_taps)
            if uncertain_changes:
                raise RuntimeError(
                    f"Cannot establish dependency relevance for {tap}/{name}: "
                    "unresolved dependency declarations; refusing a speculative update PR."
                )
            if not impacted_changes and not impacted_helper_taps:
                continue

            sources = {changed_tap for changed_tap, _ in impacted_changes}
            sources.update(impacted_helper_taps)
            relevant_taps.update(sources)
            package_impacts[root] = {
                "own_changed": root in changed_recipes,
                "dependency_changed": any(node != root for node in impacted_changes),
                "helper_changed": bool(impacted_helper_taps),
                "sources": sources,
            }

    candidate_nodes = {
        tap: after["nodes"][tap]["locked"]
        for tap in TAPS
    }
    old_nodes = {
        tap: before["nodes"][tap]["locked"]
        for tap in TAPS
    }
    package_compares = {}
    for root, impact in package_impacts.items():
        source = next(
            tap for tap in TAPS if tap in impact["sources"]
        )
        package_compares[root] = compare_url(source, old_nodes[source], candidate_nodes[source])

    for tap in TAPS:
        if tap not in relevant_taps:
            after["nodes"][tap] = before["nodes"][tap]

    changed_rows = []
    for tap in TAPS:
        old_node = old_nodes[tap]
        new_node = after["nodes"][tap]["locked"]
        compare = compare_url(tap, old_node, new_node)
        lines.extend(["", f"### {tap}", ""])
        names = sorted(set(declared[tap]))
        direct_changes = {
            name for name in names
            if (tap, name) in changed_recipes and name in old_packages[tap]
        }
        old_paths = {
            name: old_packages[tap][name]
            for name in direct_changes
        }
        old_versions = versions(tap, old_paths, brew) if old_paths else {}
        new_versions = candidate_versions_by_tap[tap]
        rows = [{
            "dependency": f"{tap} tap",
            "previous": f"revision {old_node['rev']}",
            "next": f"revision {new_node['rev']}",
            "change": "Unchanged" if old_node == new_node else "Updated",
            "compare": compare,
        }]
        for name in names:
            root = (tap, name)
            old_present = name in old_packages[tap]
            new_present = name in new_packages[tap]
            own_changed = root in changed_recipes
            previous = (
                old_versions.get(name) if own_changed
                else new_versions.get(name) if old_present
                else None
            )
            current = new_versions.get(name) if new_present else None
            impact = package_impacts.get(root)
            if not old_present and not new_present:
                change = "Unavailable in both pinned taps"
            elif previous is None and current is None:
                change = "Unavailable in both pinned taps"
            elif previous is None:
                change = "Added"
            elif current is None:
                change = "Removed"
            elif own_changed and previous == current:
                change = "Definition only (version unchanged)"
            elif own_changed:
                change = "Version / revision"
            elif impact and (impact["dependency_changed"] or impact["helper_changed"]):
                change = "Dependency / helper updated"
            else:
                change = "Unchanged"
            row = {
                "dependency": name,
                "previous": previous,
                "next": current,
                "change": change,
                "compare": package_compares.get(root, compare),
            }
            rows.append(row)
            if impact:
                changed_rows.append(row)
        lines.append(VERSION_TABLE.render_table(rows))

    lines.extend(["", "Review, merge, and workstation activation remain manual.", ""])
    return "\n".join(lines), changed_rows


def summarize(before, after, declared, brew="brew"):
    return analyze(before, after, declared, brew)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--changes-file", type=Path)
    parser.add_argument(
        "--brew",
        default=os.environ.get("HOMEBREW_TEST_BREW", "brew"),
        help="Homebrew executable selected by the flake's brew-src pin",
    )
    args = parser.parse_args()
    lock = Path("flake.lock")
    before = json.loads(lock.read_text())
    try:
        verify_brew_version(args.brew, before)
    except RuntimeError as error:
        parser.error(str(error))
    subprocess.run(["nix", "flake", "update", *TAPS], check=True)
    candidate_after = json.loads(lock.read_text())
    after = json.loads(json.dumps(candidate_after))
    try:
        body, changes = analyze(before, after, inventory(), args.brew)
    except RuntimeError as error:
        parser.error(str(error))
    if after != candidate_after:
        lock.write_text(json.dumps(after, indent=2) + "\n")
    args.body_file.write_text(body)
    if args.changes_file:
        args.changes_file.write_text(json.dumps(changes, indent=2) + "\n")


if __name__ == "__main__":
    main()
