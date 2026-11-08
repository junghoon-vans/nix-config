#!/usr/bin/env python3
"""Overlay Nix-owned settings onto the writable Hermes configuration."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


NIX_STORE_ROOT = Path("/nix/store")
RUNTIME_CONFIG_NAME = "config.yaml"


def _signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _legacy_store_target(path, target):
    destination = Path(target)
    if not destination.is_absolute():
        destination = path.parent / destination
    lexical_store = Path(os.path.abspath(NIX_STORE_ROOT))
    lexical_destination = Path(os.path.abspath(destination))
    if lexical_destination == lexical_store or not lexical_destination.is_relative_to(lexical_store):
        return False
    try:
        store = NIX_STORE_ROOT.resolve()
        resolved = destination.resolve()
    except OSError:
        return False
    return resolved != store and resolved.is_relative_to(store)


def _runtime_state(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    target = os.readlink(path) if stat.S_ISLNK(info.st_mode) else None
    return (_signature(info), target)


def _read_runtime_config(path):
    state = _runtime_state(path)
    if state is None:
        return state, None, None

    info = path.lstat()
    if _signature(info) != state[0]:
        raise RuntimeError("The Hermes runtime config changed while it was being inspected.")
    if stat.S_ISLNK(info.st_mode):
        if os.readlink(path) != state[1]:
            raise RuntimeError("The Hermes runtime config changed while it was being inspected.")
        if info.st_uid != os.getuid():
            raise RuntimeError("The Hermes runtime config symlink must be user-owned.")
        if not _legacy_store_target(path, state[1]):
            raise RuntimeError("Refusing to replace a runtime config symlink outside the Nix store.")
        return state, None, None
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("The Hermes runtime config must be a regular file or legacy Nix-store symlink.")
    if info.st_uid != os.getuid():
        raise RuntimeError("The Hermes runtime config must be user-owned.")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077 or mode & 0o7000:
        raise RuntimeError("The Hermes runtime config must not be accessible by group or other users.")

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _signature(opened) != state[0]:
            raise RuntimeError("The Hermes runtime config changed while it was being read.")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return state, content, mode


def _load_config(content, description):
    import yaml

    try:
        value = yaml.safe_load(content.decode("utf-8")) if content is not None else {}
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise RuntimeError(f"Could not parse {description}: {error}") from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"{description} must contain a YAML mapping.")
    return value


def _managed_mcp_names(config):
    names = config.get("nix_managed_mcp_servers", [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise RuntimeError("nix_managed_mcp_servers must be a list of server names.")
    return names


SKILL_DIRS_KEY = "nix_managed_skill_dirs"
SKILL_NAMES_KEY = "nix_managed_skill_names"
SKILL_PROJECTIONS_KEY = "nix_managed_skill_projection_sources"


def _managed_skill_values(config, key, description):
    values = config.get(key, [])
    if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise RuntimeError(f"{key} must be a list of {description}.")
    return values


def _external_dirs(skills):
    values = skills.get("external_dirs", [])
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        return []
    return [value for value in values if value.strip()]


def _external_path(value, home):
    path = Path(os.path.expanduser(os.path.expandvars(value)))
    if not path.is_absolute():
        path = Path(home) / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_store_path(path, home):
    try:
        return _external_path(path, home).is_relative_to(Path(NIX_STORE_ROOT).resolve())
    except OSError:
        return False


def _skill_aliases(skill_dir, root):
    aliases = {skill_dir.name}
    try:
        aliases.add(skill_dir.relative_to(root).as_posix())
    except ValueError:
        pass
    metadata_path = skill_dir / "SKILL.md"
    try:
        with metadata_path.open(encoding="utf-8") as stream:
            content = stream.read(65536)
    except (OSError, UnicodeError):
        return aliases
    if not content.startswith("---\n"):
        return aliases
    end = content.find("\n---", 4)
    if end < 0:
        return aliases
    import yaml

    try:
        metadata = yaml.safe_load(content[4:end])
    except yaml.YAMLError:
        return aliases
    if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
        aliases.add(metadata["name"])
    return aliases


def _skill_projection_entries(source, managed_names):
    entries = []
    collision = False
    active = set()

    def visit(directory, relative):
        nonlocal collision
        resolved = directory.resolve()
        if resolved in active:
            return
        active.add(resolved)
        if (directory / "SKILL.md").is_file() and _skill_aliases(directory, source) & managed_names:
            collision = True
            active.remove(resolved)
            return
        if relative.parts:
            entries.append(["dir", relative.as_posix()])
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            child_relative = relative / child.name
            if child.is_dir():
                if (child / "SKILL.md").is_file() and _skill_aliases(child, source) & managed_names:
                    collision = True
                    continue
                visit(child, child_relative)
            else:
                entries.append(["link", child_relative.as_posix(), str(child.absolute())])
        active.remove(resolved)

    visit(source, Path())
    entries.sort()
    return entries, collision


def _actual_projection_entries(path):
    entries = []
    for directory, names, files in os.walk(path, followlinks=False):
        parent = Path(directory)
        for name in list(names):
            child = parent / name
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                entries.append(["link", relative, os.readlink(child)])
                names.remove(name)
            else:
                entries.append(["dir", relative])
        for name in files:
            child = parent / name
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                entries.append(["link", relative, os.readlink(child)])
            else:
                entries.append(["file", relative])
    return sorted(entries)


def _projection_base(home, create=False):
    base = Path(home) / ".nix-managed-skills"
    try:
        info = base.lstat()
    except FileNotFoundError:
        if not create:
            return None
        base.mkdir(mode=0o700)
        info = base.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("The managed skill projection directory must be private and user-owned.")
    return base


def _projection_manifest(path, base):
    if path.parent != base or not re.fullmatch(r"root-[0-9a-f]{64}", path.name):
        return None
    marker = base / f"{path.name}.json"
    try:
        marker_info = marker.lstat()
        path_info = path.lstat()
        if (not stat.S_ISREG(marker_info.st_mode) or marker_info.st_uid != os.getuid()
                or stat.S_IMODE(marker_info.st_mode) & 0o077
                or not stat.S_ISDIR(path_info.st_mode) or path_info.st_uid != os.getuid()):
            return None
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("path") != str(path) or value.get("version") != 1:
        return None
    if value.get("entries") != _actual_projection_entries(path):
        return None
    return value


def _remove_owned_projection(path_value, home):
    base = _projection_base(home)
    if base is None:
        return
    path = Path(path_value)
    manifest = _projection_manifest(path, base)
    if manifest is None:
        return
    shutil.rmtree(path)
    (base / f"{path.name}.json").unlink()


def _project_external_root(value, home, managed_names):
    source = _external_path(value, home)
    if not source.is_dir() or not managed_names:
        return value, None
    source = source.resolve()
    entries, collision = _skill_projection_entries(source, managed_names)
    if not collision:
        return value, None
    try:
        in_store = source.is_relative_to(Path(NIX_STORE_ROOT).resolve())
    except OSError:
        in_store = False
    if in_store and not entries:
        return None, None
    payload = json.dumps(
        [str(source), sorted(managed_names), entries],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    name = "root-" + hashlib.sha256(payload).hexdigest()
    base = _projection_base(home, create=True)
    projection = base / name
    marker = base / f"{name}.json"
    expected = {
        "version": 1,
        "path": str(projection),
        "source": str(source),
        "managed_names": sorted(managed_names),
        "entries": entries,
    }
    if projection.exists() or projection.is_symlink():
        if _projection_manifest(projection, base) != expected:
            raise RuntimeError(f"Refusing to replace an unowned managed skill projection: {projection}")
        return str(projection), str(value)
    if marker.exists() or marker.is_symlink():
        marker_info = marker.lstat()
        if (not stat.S_ISREG(marker_info.st_mode) or marker_info.st_uid != os.getuid()
                or stat.S_IMODE(marker_info.st_mode) & 0o077):
            raise RuntimeError(f"Refusing to replace an unowned managed skill projection marker: {marker}")
        try:
            partial = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError(f"Refusing to replace an unowned managed skill projection marker: {marker}")
        if partial != expected:
            raise RuntimeError(f"Refusing to replace an unowned managed skill projection marker: {marker}")
        marker.unlink()

    temporary = Path(tempfile.mkdtemp(prefix=".projection-", dir=base))
    marker_descriptor = -1
    marker_temporary = None
    try:
        for kind, relative, *target in entries:
            destination = temporary / relative
            if kind == "dir":
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.symlink_to(target[0])
        marker_descriptor, marker_temporary = tempfile.mkstemp(prefix=".marker-", dir=base)
        os.fchmod(marker_descriptor, 0o600)
        with os.fdopen(marker_descriptor, "w", encoding="utf-8") as stream:
            marker_descriptor = -1
            json.dump(expected, stream, ensure_ascii=False)
        os.replace(marker_temporary, marker)
        marker_temporary = None
        os.replace(temporary, projection)
        temporary = None
    finally:
        if marker_descriptor >= 0:
            os.close(marker_descriptor)
        if marker_temporary is not None:
            os.unlink(marker_temporary)
        if temporary is not None:
            shutil.rmtree(temporary)
    return str(projection), str(value)


def _reconcile_skills(home, previous, defaults, result):
    metadata_keys = (SKILL_DIRS_KEY, SKILL_NAMES_KEY)
    previous_projections = previous.get(SKILL_PROJECTIONS_KEY, {})
    if not isinstance(previous_projections, dict) or any(
        not isinstance(path, str) or not isinstance(source, str)
        for path, source in previous_projections.items()
    ):
        raise RuntimeError(f"{SKILL_PROJECTIONS_KEY} must be a mapping of projection paths to source paths.")
    if not any(key in previous or key in defaults for key in metadata_keys) and not previous_projections:
        previous_skills = previous.get("skills", {})
        declared_skills = defaults.get("skills", {})
        if isinstance(previous_skills, dict) and isinstance(declared_skills, dict):
            previous_dirs = previous_skills.get("external_dirs", [])
            declared_dirs = declared_skills.get("external_dirs")
            if isinstance(previous_dirs, list) and isinstance(declared_dirs, list):
                result["skills"]["external_dirs"] = list(dict.fromkeys([*previous_dirs, *declared_dirs]))
        return set(), set()

    previous_managed = _managed_skill_values(previous, SKILL_DIRS_KEY, "managed skill directories")
    current_managed = _managed_skill_values(defaults, SKILL_DIRS_KEY, "managed skill directories")
    current_names = _managed_skill_values(defaults, SKILL_NAMES_KEY, "managed skill names")
    previous_skills = previous.get("skills", {})
    declared_skills = defaults.get("skills", {})
    previous_dirs = _external_dirs(previous_skills) if isinstance(previous_skills, dict) else []
    declared_dirs = _external_dirs(declared_skills) if isinstance(declared_skills, dict) else []
    managed_paths = {
        os.path.normcase(str(_external_path(path, home)))
        for path in [*previous_managed, *current_managed]
    }
    source_by_projection = previous_projections
    unprojected = [source_by_projection.get(path, path) for path in previous_dirs]
    retained = [
        path for path in unprojected
        if os.path.normcase(str(_external_path(path, home))) not in managed_paths
        and not (_is_store_path(path, home) and not _external_path(path, home).exists())
    ]
    declared_ids = {os.path.normcase(str(_external_path(path, home))) for path in declared_dirs}
    for path in current_managed:
        identity = os.path.normcase(str(_external_path(path, home)))
        if identity not in declared_ids:
            declared_dirs.append(path)
            declared_ids.add(identity)
    combined = []
    seen_roots = set()
    for path in [*retained, *declared_dirs]:
        identity = os.path.normcase(str(_external_path(path, home)))
        if identity not in seen_roots:
            seen_roots.add(identity)
            combined.append(path)

    projections = {}
    effective_dirs = []
    managed_names = set(current_names)
    for path in combined:
        identity = os.path.normcase(str(_external_path(path, home)))
        if identity in managed_paths:
            projected, source = path, None
        else:
            projected, source = _project_external_root(path, home, managed_names)
        if projected is None:
            continue
        effective_dirs.append(projected)
        if source is not None:
            projections[projected] = source
    result.setdefault("skills", {})["external_dirs"] = effective_dirs
    result[SKILL_DIRS_KEY] = current_managed
    result[SKILL_NAMES_KEY] = current_names
    result[SKILL_PROJECTIONS_KEY] = projections
    old_projection_paths = set(previous_projections)
    new_projection_paths = set(projections)
    return old_projection_paths - new_projection_paths, new_projection_paths - old_projection_paths


def _replace_managed_mcp(previous, defaults):
    # Remember the previous generation's ownership, not its credentials. The
    # historical names also migrate profiles prepared before bookkeeping existed.
    names = set(_managed_mcp_names(previous)) | set(_managed_mcp_names(defaults))
    names.update(("notion", "github"))
    result = dict(previous)
    servers = previous.get("mcp_servers")
    if isinstance(servers, dict):
        result["mcp_servers"] = {
            name: value for name, value in servers.items() if name not in names
        }
    return result


def _overlay_config(previous, overrides):
    result = dict(previous) if isinstance(previous, dict) else {}
    for key, value in overrides.items():
        if isinstance(value, dict):
            result[key] = _overlay_config(result.get(key), value)
        else:
            result[key] = value
    return result


def _replace_runtime_config(path, content, prior_state):
    if _runtime_state(path) != prior_state:
        raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
    descriptor, temporary = tempfile.mkstemp(prefix=".config.yaml.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if _runtime_state(path) != prior_state:
            raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
        os.replace(temporary, path)
        temporary = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            os.unlink(temporary)


def prepare_runtime_config(home, defaults_path):
    import yaml

    runtime_path = Path(home) / RUNTIME_CONFIG_NAME
    state, previous_content, previous_mode = _read_runtime_config(runtime_path)
    defaults_path = Path(defaults_path)
    if not defaults_path.is_file():
        raise RuntimeError("The declared Nix Hermes config defaults are unavailable.")
    defaults = _load_config(defaults_path.read_bytes(), "the declared Nix Hermes config defaults")
    previous = _load_config(previous_content, "the existing Hermes runtime config")
    result = _overlay_config(_replace_managed_mcp(previous, defaults), defaults)
    if "nix_managed_mcp_servers" in previous or "nix_managed_mcp_servers" in defaults:
        result["nix_managed_mcp_servers"] = _managed_mcp_names(defaults)
    obsolete_projections, new_projections = _reconcile_skills(home, previous, defaults, result)
    content = yaml.safe_dump(result, sort_keys=False, allow_unicode=True).encode("utf-8")
    try:
        if previous_content == content and previous_mode == 0o600:
            if _runtime_state(runtime_path) != state:
                raise RuntimeError("The Hermes runtime config changed while it was being prepared.")
        else:
            _replace_runtime_config(runtime_path, content, state)
    except Exception:
        previous_projections = previous.get(SKILL_PROJECTIONS_KEY, {})
        for projection in new_projections - set(previous_projections):
            _remove_owned_projection(projection, home)
        raise
    for projection in obsolete_projections:
        _remove_owned_projection(projection, home)
    return runtime_path


def main():
    if len(sys.argv) != 3:
        raise RuntimeError("Usage: prepare-config.py PROFILE_HOME DEFAULTS")
    home = Path(sys.argv[1])
    info = home.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise RuntimeError("The Hermes home must be a user-owned directory not writable by others.")
    prepare_runtime_config(home, sys.argv[2])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Hermes configuration: {error}", file=sys.stderr)
        sys.exit(1)
