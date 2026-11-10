import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import yaml


SPEC = importlib.util.spec_from_file_location("hermes_config", Path(__file__).with_name("prepare-config.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HermesRuntimeConfig(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / ".hermes"
        self.home.mkdir(mode=0o700)
        self.store = self.root / "nix-store"
        self.store.mkdir()
        self.defaults_path = self.store / "hermes-config.yaml"
        self.defaults = {
            "model": {"provider": "openai-codex", "default": "gpt-6.1-sol"},
            "approvals": {"mode": "manual", "unattended_mode": "deny"},
            "plugins": {"enabled": ["omp-acp-provider", "advanced-delegation"]},
        }
        self.defaults_path.write_text(yaml.safe_dump(self.defaults, sort_keys=False))
        self.runtime = self.home / "config.yaml"

    def check(self):
        MODULE.prepare_runtime_config(self.home, self.defaults_path)

    def write_defaults(self, path, values):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(values, sort_keys=False))

    def test_nix_overrides_declared_values_and_preserves_hermes_settings(self):
        source_content = self.defaults_path.read_bytes()
        self.runtime.write_text(yaml.safe_dump({
            "model": {"provider": "stale-provider", "temperature": 0.7},
            "plugins": {
                "enabled": ["local-plugin"],
                "entries": {"local-plugin": {"enabled": True}},
            },
            "api_key": "private-test-secret",
            "command_allowlist": ["git status"],
        }))
        self.runtime.chmod(0o600)

        self.check()

        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o600)
        self.assertEqual(self.runtime.stat().st_uid, os.getuid())
        self.assertEqual(
            yaml.safe_load(self.runtime.read_text()),
            {
                **self.defaults,
                "model": {**self.defaults["model"], "temperature": 0.7},
                "plugins": {
                    "enabled": ["omp-acp-provider", "advanced-delegation"],
                    "entries": {"local-plugin": {"enabled": True}},
                },
                "api_key": "private-test-secret",
                "command_allowlist": ["git status"],
            },
        )
        self.assertEqual(self.defaults_path.read_bytes(), source_content)

    def test_hermes_edits_survive_repeated_activation_and_changed_nix_values(self):
        self.runtime.write_text("command_allowlist:\n  - 'git status'\n")
        self.runtime.chmod(0o600)
        self.check()
        first = self.runtime.stat()

        self.check()

        repeated = self.runtime.stat()
        self.assertEqual(repeated.st_ino, first.st_ino)
        self.assertEqual(repeated.st_mtime_ns, first.st_mtime_ns)

        edited = yaml.safe_load(self.runtime.read_text())
        edited["model"].update(default="temporary-local-model", temperature=0.3)
        self.runtime.write_text(yaml.safe_dump(edited, sort_keys=False))

        next_defaults_path = self.store / "next-generation" / "hermes-config.yaml"
        next_defaults = {
            "model": {"provider": "new-provider", "default": "new-model"},
            "approvals": {"mode": "manual", "unattended_mode": "deny"},
            "plugins": {"enabled": ["omp-acp-provider", "advanced-delegation"]},
        }
        self.write_defaults(next_defaults_path, next_defaults)
        self.defaults_path = next_defaults_path
        self.check()

        self.assertEqual(
            yaml.safe_load(self.runtime.read_text()),
            {
                **next_defaults,
                "model": {**next_defaults["model"], "temperature": 0.3},
                "command_allowlist": ["git status"],
            },
        )

    def test_empty_and_scalar_overrides_preserve_unowned_mapping_keys(self):
        self.runtime.write_text(yaml.safe_dump({
            "model": "legacy-model",
            "compression": {"enabled": True, "summary_model": "local-model"},
            "mcp_servers": {"local": {"command": "local-mcp"}},
            "command_allowlist": ["git status"],
        }))
        self.runtime.chmod(0o600)
        self.write_defaults(self.defaults_path, {
            "model": {"default": "nix-model", "base_url": None},
            "compression": {"enabled": False},
            "mcp_servers": {},
            "command_allowlist": [],
        })

        self.check()

        self.assertEqual(yaml.safe_load(self.runtime.read_text()), {
            "model": {"default": "nix-model", "base_url": None},
            "compression": {"enabled": False, "summary_model": "local-model"},
            "mcp_servers": {"local": {"command": "local-mcp"}},
            "command_allowlist": [],
        })

    def test_shared_skill_roots_preserve_existing_paths_without_duplicates(self):
        self.runtime.write_text(yaml.safe_dump({
            "skills": {"external_dirs": ["/existing/skills", "/shared/skills"], "disabled": ["local"]},
        }))
        self.runtime.chmod(0o600)
        self.write_defaults(self.defaults_path, {
            "skills": {"external_dirs": ["/shared/skills", "/new/skills"]},
        })

        self.check()
        self.check()

        self.assertEqual(yaml.safe_load(self.runtime.read_text())["skills"], {
            "external_dirs": ["/existing/skills", "/shared/skills", "/new/skills"],
            "disabled": ["local"],
        })

    def test_managed_skill_generations_project_shared_collisions_without_losing_other_skills(self):
        old_root = self.store / "old-ego" / "share"
        stale_untracked_root = self.store / "untracked-old-ego" / "share"
        current_root = self.store / "current-ego" / "share"
        shared_root = self.root / "agents" / "skills"
        local_root = self.root / "local-skills"

        def add_skill(root, name, body):
            skill = root / name / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(f"---\nname: {name}\n---\n\n{body}\n")

        add_skill(current_root, "ego-browser", "canonical declared Ego skill")
        add_skill(shared_root, "ego-browser", "stale shared Ego copy")
        add_skill(shared_root, "review-notes", "unrelated shared skill")
        add_skill(local_root, "local-only", "unrelated external skill")

        self.runtime.write_text(yaml.safe_dump({
            "skills": {
                "external_dirs": [
                    str(old_root), str(stale_untracked_root), str(shared_root), str(local_root),
                ],
                "disabled": ["local"],
            },
            "nix_managed_skill_dirs": [str(old_root)],
            "nix_managed_skill_names": ["ego-browser"],
            "command_allowlist": ["git status"],
        }, sort_keys=False))
        self.runtime.chmod(0o600)
        self.write_defaults(self.defaults_path, {
            "skills": {"external_dirs": [str(current_root), str(shared_root)]},
            "nix_managed_skill_dirs": [str(current_root)],
            "nix_managed_skill_names": ["ego-browser"],
        })

        with patch.object(MODULE, "NIX_STORE_ROOT", self.store):
            self.check()
        first_runtime = self.runtime.stat()
        result = yaml.safe_load(self.runtime.read_text())
        external_dirs = result["skills"]["external_dirs"]

        self.assertNotIn(str(old_root), external_dirs)
        self.assertNotIn(str(stale_untracked_root), external_dirs)
        self.assertNotIn(str(shared_root), external_dirs)
        self.assertIn(str(current_root), external_dirs)
        self.assertIn(str(local_root), external_dirs)
        self.assertEqual(result["skills"]["disabled"], ["local"])
        self.assertEqual(result["command_allowlist"], ["git status"])
        self.assertEqual(result["nix_managed_skill_dirs"], [str(current_root)])
        self.assertEqual(shared_root.joinpath("ego-browser", "SKILL.md").read_text().splitlines()[-1],
                         "stale shared Ego copy")

        projection = next(
            Path(path) for path in external_dirs
            if path in result["nix_managed_skill_projection_sources"]
        )
        self.assertEqual(
            result["nix_managed_skill_projection_sources"][str(projection)],
            str(shared_root),
        )
        self.assertFalse((projection / "ego-browser").exists())
        self.assertEqual((projection / "review-notes" / "SKILL.md").read_text().splitlines()[-1],
                         "unrelated shared skill")

        # Hermes treats every external root as one tier: a same-name copy in
        # two roots makes the name ambiguous rather than preferring list order.
        ego_candidates = [
            skill for directory in external_dirs
            for skill in Path(directory).rglob("SKILL.md")
            if yaml.safe_load(skill.read_text().split("---", 2)[1]).get("name") == "ego-browser"
        ]
        self.assertEqual(len(ego_candidates), 1)
        self.assertEqual(ego_candidates[0].read_text().splitlines()[-1],
                         "canonical declared Ego skill")

        self.check()
        repeated = self.runtime.stat()
        self.assertEqual(repeated.st_ino, first_runtime.st_ino)
        self.assertEqual(repeated.st_mtime_ns, first_runtime.st_mtime_ns)
        self.assertEqual(yaml.safe_load(self.runtime.read_text())["skills"]["external_dirs"], external_dirs)

        projection_data = projection.parent / "user-owned-data"
        projection_data.write_text("keep")
        self.write_defaults(self.defaults_path, {
            "skills": {"external_dirs": [str(current_root), str(shared_root)]},
            "nix_managed_skill_dirs": [str(current_root)],
            "nix_managed_skill_names": [],
        })
        self.check()
        unfiltered = yaml.safe_load(self.runtime.read_text())
        self.assertIn(str(shared_root), unfiltered["skills"]["external_dirs"])
        self.assertFalse(projection.exists())
        self.assertFalse(projection.with_suffix(".json").exists())
        self.assertEqual(projection_data.read_text(), "keep")

    def test_projection_preserves_aliases_and_parent_child_shadowing(self):
        source_root = self.root / "external-skills"
        managed_names = [
            "directory-shadow",
            "category/path-shadow",
            "frontmatter-shadow",
            "hidden-child",
            "shadow-parent",
        ]

        def add_skill(relative, name, body):
            skill = source_root / relative / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(f"---\nname: {name}\n---\n\n{body}\n")

        add_skill(Path("directory-shadow"), "directory-name", "Shadowed by directory name.")
        add_skill(Path("category/path-shadow"), "path-name", "Shadowed by relative path.")
        add_skill(Path("category/frontmatter-candidate"), "frontmatter-shadow", "Shadowed by name.")
        add_skill(Path("category/parent"), "retained-parent", "Parent remains visible.")
        add_skill(Path("category/parent/hidden-child"), "hidden-child", "Child is shadowed.")
        add_skill(Path("category/shadow-parent"), "shadow-parent", "Parent and subtree are shadowed.")
        add_skill(Path("category/shadow-parent/visible-child"), "visible-child", "Must stay hidden.")
        # Excluded subtrees must not be inspected or re-exposed by parent links.
        (source_root / "category/shadow-parent/unused.md").symlink_to(
            self.root / "missing-excluded-reference.md"
        )
        add_skill(Path("nested/live-reader"), "nested-frontmatter", "Unshadowed nested skill.")

        parent_reference = source_root / "category/parent/references/retained.md"
        parent_reference.parent.mkdir(parents=True)
        parent_reference.write_text("Retained parent reference.\n")
        live_reference = source_root / "nested/live-reader/references/guide.md"
        live_reference.parent.mkdir(parents=True)
        live_reference.write_text("Live nested reference.\n")

        managed_root = self.store / "managed-skills"
        managed_root.mkdir()
        self.write_defaults(self.defaults_path, {
            "skills": {"external_dirs": [str(source_root)]},
            "nix_managed_skill_dirs": [str(managed_root)],
            "nix_managed_skill_names": managed_names,
        })

        self.check()
        result = yaml.safe_load(self.runtime.read_text())
        projection = Path(next(iter(result[MODULE.SKILL_PROJECTIONS_KEY])))

        self.assertFalse(projection.is_symlink())
        self.assertEqual(result[MODULE.SKILL_PROJECTIONS_KEY][str(projection)], str(source_root))
        self.assertEqual(result[MODULE.SKILL_NAMES_KEY], managed_names)
        for relative in (
            "directory-shadow",
            "category/path-shadow",
            "category/frontmatter-candidate",
            "category/parent/hidden-child",
            "category/shadow-parent",
        ):
            self.assertFalse((projection / relative).exists(), relative)

        partial_parent = projection / "category/parent"
        self.assertFalse(partial_parent.is_symlink())
        self.assertEqual(
            (partial_parent / "SKILL.md").read_text().splitlines()[-1],
            "Parent remains visible.",
        )
        self.assertEqual(
            (partial_parent / "references/retained.md").read_text(),
            "Retained parent reference.\n",
        )
        self.assertFalse((partial_parent / "references/retained.md").is_symlink())
        self.assertTrue((projection / "nested/live-reader").is_symlink())
        self.assertEqual(
            (projection / "nested/live-reader/references/guide.md").read_text(),
            "Live nested reference.\n",
        )

    def test_partial_projection_refreshes_content_and_path_per_profile(self):
        source_root = self.root / "update-source"
        partial_skill = source_root / "guide/partial-reader"
        partial_skill.mkdir(parents=True)
        (partial_skill / "SKILL.md").write_text("---\nname: partial-reader\n---\n\nVersion one.\n")
        hidden_child = partial_skill / "hidden-child"
        hidden_child.mkdir()
        (hidden_child / "SKILL.md").write_text("---\nname: hidden-child\n---\n\nShadowed child.\n")
        reference = partial_skill / "references/original.md"
        reference.parent.mkdir()
        reference.write_text("Reference version one.\n")

        managed_root = self.store / "managed-update-skills"
        managed_root.mkdir()
        self.write_defaults(self.defaults_path, {
            "skills": {"external_dirs": [str(source_root)]},
            "nix_managed_skill_dirs": [str(managed_root)],
            "nix_managed_skill_names": ["hidden-child"],
        })

        self.check()
        profile_a = yaml.safe_load(self.runtime.read_text())
        projection_a1 = Path(next(iter(profile_a[MODULE.SKILL_PROJECTIONS_KEY])))
        self.assertEqual(
            (projection_a1 / "guide/partial-reader/references/original.md").read_text(),
            "Reference version one.\n",
        )
        unrelated = projection_a1.parent / "user-owned-data"
        unrelated.write_text("keep")

        profile_b_home = self.root / "second-profile"
        profile_b_home.mkdir(mode=0o700)
        profile_b_config_path = MODULE.prepare_runtime_config(profile_b_home, self.defaults_path)
        profile_b = yaml.safe_load(profile_b_config_path.read_text())
        projection_b = Path(next(iter(profile_b[MODULE.SKILL_PROJECTIONS_KEY])))
        self.assertNotEqual(projection_a1, projection_b)
        self.assertEqual(projection_b.parent, profile_b_home / ".nix-managed-skills")

        reference.write_text("Reference version two.\n")
        self.check()
        profile_a_updated = yaml.safe_load(self.runtime.read_text())
        projection_a2 = Path(next(iter(profile_a_updated[MODULE.SKILL_PROJECTIONS_KEY])))
        self.assertNotEqual(projection_a1, projection_a2)
        self.assertFalse(projection_a1.exists())
        self.assertEqual(
            (projection_a2 / "guide/partial-reader/references/original.md").read_text(),
            "Reference version two.\n",
        )
        self.assertEqual(
            (projection_b / "guide/partial-reader/references/original.md").read_text(),
            "Reference version one.\n",
        )

        renamed_reference = reference.with_name("updated.md")
        reference.rename(renamed_reference)
        self.check()
        profile_a_renamed = yaml.safe_load(self.runtime.read_text())
        projection_a3 = Path(next(iter(profile_a_renamed[MODULE.SKILL_PROJECTIONS_KEY])))
        self.assertNotEqual(projection_a2, projection_a3)
        self.assertFalse((projection_a3 / "guide/partial-reader/references/original.md").exists())
        self.assertEqual(
            (projection_a3 / "guide/partial-reader/references/updated.md").read_text(),
            "Reference version two.\n",
        )
        self.assertEqual(unrelated.read_text(), "keep")

    def test_external_skill_symlink_escapes_are_refused(self):
        for case in ("outside-root", "sibling-skill"):
            with self.subTest(case=case):
                source_root = self.root / f"external-{case}"
                partial_skill = source_root / "partial-reader"
                partial_skill.mkdir(parents=True)
                (partial_skill / "SKILL.md").write_text("---\nname: partial-reader\n---\n\nParent.\n")
                hidden_child = partial_skill / "hidden-child"
                hidden_child.mkdir()
                (hidden_child / "SKILL.md").write_text("---\nname: hidden-child\n---\n\nHidden.\n")
                references = partial_skill / "references"
                references.mkdir()
                link = references / "escape.md"

                if case == "outside-root":
                    target = self.root / "external-secret.md"
                else:
                    sibling = source_root / "sibling-skill"
                    sibling.mkdir()
                    (sibling / "SKILL.md").write_text("---\nname: sibling-skill\n---\n\nSibling.\n")
                    target = sibling / "private-reference.md"
                target.write_text("Must not be projected into the parent skill.\n")
                link.symlink_to(os.path.relpath(target, link.parent))

                managed_root = self.store / f"managed-{case}"
                managed_root.mkdir()
                self.write_defaults(self.defaults_path, {
                    "skills": {"external_dirs": [str(source_root)]},
                    "nix_managed_skill_dirs": [str(managed_root)],
                    "nix_managed_skill_names": ["hidden-child"],
                })

                with self.assertRaisesRegex(RuntimeError, "escapes its (root|skill directory)"):
                    self.check()
                self.assertFalse(self.runtime.exists())

    def test_managed_server_generations_replace_remove_and_preserve_local_state(self):
        local = {"command": "local-mcp", "env": {"LOCAL_SETTING": "keep"}}
        self.runtime.write_text(yaml.safe_dump({
            "mcp_servers": {
                "local": local,
                "notion": {"command": "stale-notion"},
                "github": {"tools": {"exclude": ["get_me"]}},
                "retired": {"command": "retired-mcp"},
                "fresh": {"command": "stale-fresh", "headers": {"Authorization": "old"}},
            },
            "nix_managed_mcp_servers": ["retired"],
            "skills": {"external_dirs": ["/local/skills"]},
            "command_allowlist": ["git status"],
        }))
        self.runtime.chmod(0o600)
        auth = self.home / "mcp-oauth-tokens.json"
        auth.write_text('{"synthetic": "untouched"}')
        declared = {"fresh": {"url": "https://example.invalid/new-mcp", "tools": {"include": ["read"]}}}
        self.write_defaults(self.defaults_path, {
            **self.defaults,
            "mcp_servers": declared,
            "nix_managed_mcp_servers": ["fresh"],
        })
        self.check()
        result = yaml.safe_load(self.runtime.read_text())
        self.assertEqual(result["mcp_servers"], {"local": local, **declared})
        self.assertEqual(result["skills"], {"external_dirs": ["/local/skills"]})
        self.assertEqual(result["command_allowlist"], ["git status"])

        # The current ownership list is sufficient to remove a dynamically
        # introduced server on the next generation, without hard-coded names.
        self.write_defaults(self.defaults_path, {
            **self.defaults, "mcp_servers": {}, "nix_managed_mcp_servers": [],
        })
        self.check()
        self.assertEqual(yaml.safe_load(self.runtime.read_text())["mcp_servers"], {"local": local})
        before = self.runtime.stat()
        self.check()
        self.assertEqual(self.runtime.stat().st_ino, before.st_ino)
        self.assertEqual(auth.read_text(), '{"synthetic": "untouched"}')

    def test_invalid_managed_ownership_does_not_modify_profile(self):
        self.runtime.write_text("mcp_servers: {}\n")
        self.runtime.chmod(0o600)
        before = self.runtime.read_bytes()
        self.write_defaults(self.defaults_path, {"nix_managed_mcp_servers": "github"})
        with self.assertRaisesRegex(RuntimeError, "list of server names"):
            self.check()
        self.assertEqual(self.runtime.read_bytes(), before)

    def test_legacy_nix_store_symlink_is_replaced_without_touching_target(self):
        legacy_path = self.store / "previous-config.yaml"
        legacy_content = b"model:\n  provider: old\ncommand_allowlist:\n  - old command\n"
        legacy_path.write_bytes(legacy_content)
        self.runtime.symlink_to(legacy_path)

        with patch.object(MODULE, "NIX_STORE_ROOT", self.store):
            self.check()

        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual(legacy_path.read_bytes(), legacy_content)
        self.assertEqual(yaml.safe_load(self.runtime.read_text()), self.defaults)

    def test_non_store_runtime_symlink_is_refused(self):
        external = self.root / "external.yaml"
        external.write_text("command_allowlist:\n  - 'allow everything'\n")
        self.runtime.symlink_to(external)

        with self.assertRaisesRegex(RuntimeError, "outside the Nix store"):
            self.check()

        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual(external.read_text(), "command_allowlist:\n  - 'allow everything'\n")

    def test_external_symlink_alias_to_store_is_still_refused(self):
        legacy = self.store / "legacy.yaml"
        legacy.write_text("command_allowlist: []\n")
        alias = self.root / "external-alias.yaml"
        alias.symlink_to(legacy)
        self.runtime.symlink_to(alias)

        with patch.object(MODULE, "NIX_STORE_ROOT", self.store):
            with self.assertRaisesRegex(RuntimeError, "outside the Nix store"):
                self.check()

        self.assertTrue(self.runtime.is_symlink())
        self.assertEqual(legacy.read_text(), "command_allowlist: []\n")

    def test_world_readable_runtime_config_is_refused(self):
        self.runtime.write_text("command_allowlist: []\n")
        self.runtime.chmod(0o644)

        with self.assertRaisesRegex(RuntimeError, "group or other users"):
            self.check()

    def test_missing_runtime_config_materializes_private_defaults(self):
        source_content = self.defaults_path.read_bytes()

        self.check()

        self.assertTrue(self.runtime.is_file())
        self.assertFalse(self.runtime.is_symlink())
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o600)
        self.assertEqual(yaml.safe_load(self.runtime.read_text()), self.defaults)
        self.assertEqual(self.defaults_path.read_bytes(), source_content)


if __name__ == "__main__":
    unittest.main()
