import copy
import json
import unittest

from dependency_report import collect_rows
from version_table import render_table


class DependencyReportTests(unittest.TestCase):
    def report(self, path, before, after):
        if not isinstance(before, str):
            before = json.dumps(before)
        if not isinstance(after, str):
            after = json.dumps(after)
        return collect_rows({path: before}, {path: after})

    def test_all_fixed_release_packages_include_old_new_version_and_hash(self):
        for name, tag in (("apm", "v"), ("bun", "bun-v"), ("gnomcp", "v"),
                          ("omp", "v"), ("paseo", "v"), ("officecli", "v")):
            with self.subTest(package=name):
                rows = self.report("release-pins.json", {name: {"version": "1.0.0", "hash": "old"}},
                                   {name: {"version": "2.0.0", "hash": "new"}})
                self.assertEqual(rows[0]["previous"], "hash: old; version: 1.0.0")
                self.assertEqual(rows[0]["next"], "hash: new; version: 2.0.0")
                self.assertTrue(rows[0]["compare"].endswith(f"/{tag}1.0.0...{tag}2.0.0"))

    def test_gno_group_reports_full_revision_and_unchanged_gnopls(self):
        before = '  gnoRev = "' + "a" * 40 + '";\n  gnoplsRev = "' + "c" * 40 + '";\n'
        rows = self.report("modules/languages/gno.nix", before, before.replace("a" * 40, "b" * 40))
        self.assertEqual(rows[0]["previous"], "Rev: " + "a" * 40)
        self.assertEqual(rows[0]["next"], "Rev: " + "b" * 40)
        self.assertEqual(rows[1]["dependency"], "gnopls")
        self.assertEqual(rows[1]["change"], "Unchanged")
        self.assertEqual(rows[1]["previous"], rows[1]["next"])

    def test_gno_hash_only_change_is_not_hidden_by_unchanged_revision(self):
        before = '  gnoRev = "same";\n  gnoVendorHash = "old";\n'
        rows = self.report("modules/languages/gno.nix", before, before.replace('"old"', '"new"'))
        self.assertEqual(rows[0]["change"], "Updated")
        self.assertIn("VendorHash: old", rows[0]["previous"])
        self.assertIn("VendorHash: new", rows[0]["next"])

    def test_homebrew_hermes_and_dependabot_include_transitive_lock_nodes(self):
        for owner in ("homebrew-core", "hermes-agent", "nixpkgs"):
            with self.subTest(owner=owner):
                old = {"nodes": {owner: {"locked": {"type": "github", "owner": "org", "repo": owner,
                                                    "rev": "a" * 40, "narHash": "old"}},
                                 "transitive_2": {"locked": {"type": "tarball", "url": "https://example.test/old", "narHash": "x"}}}}
                new = copy.deepcopy(old)
                new["nodes"][owner]["locked"]["rev"] = "b" * 40
                new["nodes"]["transitive_2"]["locked"].update(url="https://example.test/new", narHash="y")
                rows = self.report("flake.lock", old, new)
                self.assertEqual([r["dependency"] for r in rows], [f"flake input {owner}", "flake input transitive_2"])
                self.assertIn("a" * 40, rows[0]["previous"])
                self.assertIn("b" * 40, rows[0]["next"])
                self.assertIn("https://example.test/old", rows[1]["previous"])
                self.assertIn("https://example.test/new", rows[1]["next"])
                self.assertIsNone(rows[1]["compare"])
    def test_hermes_tag_and_missing_lock_version_metadata_stay_distinct(self):
        old = {"nodes": {"hermes-agent": {"original": {"ref": "v0.20.0"},
                                         "locked": {"type": "github", "owner": "NousResearch", "repo": "hermes-agent", "rev": "old"}}}}
        new = copy.deepcopy(old)
        new["nodes"]["hermes-agent"]["original"]["ref"] = "v0.21.0"
        new["nodes"]["hermes-agent"]["locked"]["rev"] = "new"
        rows = self.report("flake.lock", old, new)
        self.assertIn("declared ref: v0.20.0", rows[0]["previous"])
        self.assertIn("declared ref: v0.21.0", rows[0]["next"])
        self.assertIn("rev: old", rows[0]["previous"])
        self.assertIn("rev: new", rows[0]["next"])


    def test_npm_group_reports_each_changed_server_and_exact_package_specs(self):
        old = {"mcpServers": {"first": {"command": "npx", "args": ["-y", "--package=@org/tool@1.0.0", "tool"]},
                              "second": {"command": "npx", "args": ["another@2.0.0"]},
                              "remote": {"url": "https://example.test"}}}
        new = copy.deepcopy(old)
        new["mcpServers"]["first"]["args"][1] = "--package=@org/tool@1.1.0"
        new["mcpServers"]["second"]["args"][0] = "another@3.0.0"
        rows = self.report("home/.omp/agent/mcp.json", old, new)
        self.assertEqual([r["dependency"] for r in rows], ["npm MCP first", "npm MCP second"])
        self.assertIn("@org/tool@1.0.0", rows[0]["previous"])
        self.assertIn("@org/tool@1.1.0", rows[0]["next"])
        self.assertIn("another@2.0.0", rows[1]["previous"])
        self.assertIn("another@3.0.0", rows[1]["next"])

    def test_tagged_skills_show_manifest_refs_and_lock_only_dependency_changes(self):
        before = 'dependencies:\n  apm:\n  - git: https://github.com/org/skills.git\n    path: skills/a\n    ref: v1.0.0\n'
        manifest_rows = self.report("apm.yml", before, before.replace("v1.0.0", "v2.0.0"))
        self.assertEqual(manifest_rows[0]["previous"], "v1.0.0")
        self.assertEqual(manifest_rows[0]["next"], "v2.0.0")
        before = 'dependencies:\n- repo_url: org/skills\n  virtual_path: skills/a\n  resolved_commit: old\n  version: unknown\n- repo_url: org/skills\n  virtual_path: skills/transitive\n  resolved_commit: old-transitive\n'
        after = before.replace("resolved_commit: old\n", "resolved_commit: new\n").replace("old-transitive", "new-transitive")
        rows = self.report("apm.lock.yaml", before, after)
        self.assertEqual([r["dependency"] for r in rows], ["APM lock org/skills / skills/a", "APM lock org/skills / skills/transitive"])
        self.assertIn("resolved_commit: old", rows[0]["previous"])
        self.assertIn("resolved_commit: new", rows[0]["next"])
        self.assertIn("new-transitive", rows[1]["next"])

    def test_plugins_include_grouped_unchanged_members_without_fabricated_versions(self):
        old = {"first": {"repository": "org/plugin", "revision": "a" * 40, "hash": "old"},
               "second": {"repository": "org/plugin", "revision": "c" * 40, "hash": "same"}}
        new = copy.deepcopy(old)
        new["first"].update(revision="b" * 40, hash="new")
        rows = self.report("modules/paseo-plugins.json", old, new)
        self.assertIn("revision: " + "a" * 40, rows[0]["previous"])
        self.assertIn("revision: " + "b" * 40, rows[0]["next"])
        self.assertEqual(rows[1]["change"], "Unchanged")

    def test_added_removed_missing_metadata_and_noop(self):
        rows = self.report("release-pins.json", {"gone": {"hash": "old"}}, {"new": {"hash": "new"}})
        self.assertEqual(rows[0]["change"], "Removed")
        self.assertIsNone(rows[0]["next"])
        self.assertEqual(rows[1]["change"], "Added")
        self.assertIsNone(rows[1]["previous"])
        self.assertIn("Not present / metadata unavailable", render_table(rows))
        self.assertEqual(collect_rows({"flake.lock": "{}"}, {"flake.lock": "{}"}), [])
        self.assertIn("No dependency pin changes", render_table([]))
        rows = self.report("flake.lock", {"nodes": {}},
                           {"nodes": {"unknown": {"locked": {"type": "github", "rev": "exact-pin"}}}})
        self.assertEqual(rows[0]["change"], "Added")
        self.assertIn("rev: exact-pin", rows[0]["next"])
        self.assertIsNone(rows[0]["compare"])

    def test_table_escapes_untrusted_markdown_and_rejects_unsafe_links(self):
        table = render_table([{"dependency": "a|b`[x]", "previous": "old\x00\r\n<script>", "next": "v2\\x",
                               "change": "same|different", "compare": "javascript:alert(1)"}])
        row = table.splitlines()[2]
        self.assertEqual(row.count("|"), 6)
        self.assertIn("a&#124;b&#96;&#91;x&#93;", row)
        self.assertIn("old&#92;u0000<br>&lt;script&gt;", row)
        self.assertNotIn("\x00", table)
        self.assertNotIn("javascript:", table)


if __name__ == "__main__":
    unittest.main()
