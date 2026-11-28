import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dependency_report

SPEC = importlib.util.spec_from_file_location("hermes_updater", Path(__file__).with_name("update-hermes.py"))
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)

OLD_REV = "a" * 40
NEW_REV = "b" * 40
UPSTREAM = "sha256-Y3jmi5nLLgGOGqcm9rgvyGbmcFJQk1Ro3+IsymICoiQ="
ACTUAL = "sha256-W5V/4xsKZKolR2MQL5GN9GBa7844IPNmKVTTcLaZnvI="
FAKE = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
PROBE = "/nix/store/3iyf3x1mfl7lik8ic34zigr4y6ins942-hermes-agent-pnpm-deps.drv"


class HermesUpdates(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.flake = self.root / "flake.nix"
        self.flake.write_text('hermes-agent.url = "github:NousResearch/hermes-agent/v0.23.3";\n')
        self.lock = self.root / "flake.lock"
        self.write_lock("v0.23.3", OLD_REV)
        self.hashes = self.root / "modules/hermes-pnpm-hashes.json"
        self.hashes.parent.mkdir()
        self.hashes.write_text(json.dumps({OLD_REV: ACTUAL}))
        self.baseline = {path: path.read_bytes() for path in (self.flake, self.lock, self.hashes)}
        self.commands = []
        self.build_error = False
        self.diagnostic = self.mismatch()

    def write_lock(self, tag, rev):
        source = {"type": "github", "owner": "NousResearch", "repo": "hermes-agent"}
        self.lock.write_text(json.dumps({"root": "root", "nodes": {
            "root": {"inputs": {"hermes-agent": "hermes-agent_2"}},
            "hermes-agent_2": {"locked": {**source, "rev": rev}, "original": {**source, "ref": tag}},
        }}))

    def mismatch(self, drv=PROBE, actual=ACTUAL, expected=FAKE, action="msg"):
        return "@nix " + json.dumps({"action": action, "level": 0, "msg": (
            f"error: hash mismatch in fixed-output derivation '{drv}':\n"
            f"         specified: {expected}\n            got:    {actual}"
        )}) + "\n"

    def nix(self, args, *, cwd, **kwargs):
        self.assertEqual(cwd, self.root)
        self.commands.append(args)
        if args[1:3] == ["flake", "update"]:
            self.assertIn("/v9.8.7\"", self.flake.read_text())
            self.write_lock("v9.8.7", NEW_REV)
            return subprocess.CompletedProcess(args, 0)
        if args[1] == "eval":
            return subprocess.CompletedProcess(args, 0, json.dumps({"outputHash": UPSTREAM, "probe": PROBE}))
        if PROBE + "^out" in args:
            return subprocess.CompletedProcess(args, 1, stderr=self.diagnostic)
        if self.build_error:
            self.assertEqual(json.loads(self.hashes.read_text()).get(NEW_REV), ACTUAL)
            raise subprocess.CalledProcessError(1, args)
        self.assertTrue(args[-1].endswith(".workstation.hermes.package.hermesNpmLib.pnpmDeps"))
        self.assertEqual(json.loads(self.hashes.read_text()), self.expected_pins)
        return subprocess.CompletedProcess(args, 0)

    def update(self, tag="v9.8.7"):
        with (
            patch.object(updater.fixed_release, "github_json", return_value={"tag_name": tag}),
            patch.object(updater.subprocess, "run", side_effect=self.nix),
            contextlib.redirect_stderr(io.StringIO()),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return updater.update(self.root)

    def assert_unchanged(self):
        self.assertEqual({path: path.read_bytes() for path in self.baseline}, self.baseline)

    def test_future_revision_pin_is_built_and_old_revision_is_preserved(self):
        self.diagnostic = (
            "@nix " + json.dumps({"action": "msg", "level": 0, "msg": f"❌ \x1b[31;1m{PROBE}^out\x1b[0m"})
            + "\n" + self.diagnostic
        )
        self.expected_pins = {OLD_REV: ACTUAL, NEW_REV: ACTUAL}
        self.assertEqual(self.update(), "v9.8.7")
        self.assertEqual(json.loads(self.hashes.read_text()), self.expected_pins)
        self.assertEqual(len(self.commands), 4)
        path = "modules/hermes-pnpm-hashes.json"
        report = dependency_report.render_body(dependency_report.collect_rows(
            {path: self.baseline[self.hashes]}, {path: self.hashes.read_bytes()},
        ))
        self.assertIn(NEW_REV, report)
        self.assertIn(ACTUAL, report)
        self.assertNotIn(OLD_REV, report)

    def test_matching_upstream_hash_is_not_overridden(self):
        self.diagnostic = self.mismatch(actual=UPSTREAM)
        self.expected_pins = {OLD_REV: ACTUAL}
        self.assertEqual(self.update(), "v9.8.7")
        self.assertEqual(self.hashes.read_bytes(), self.baseline[self.hashes])

    def test_current_release_does_not_relock_or_rebuild(self):
        self.assertEqual(self.update("v0.23.3"), "v0.23.3")
        self.assertEqual(self.commands, [])
        self.assert_unchanged()

    def test_untrusted_or_ambiguous_diagnostics_are_not_accepted(self):
        for diagnostic in (
            "error: registry unreachable\n",
            self.mismatch(drv=PROBE.replace("hermes-agent", "other")),
            self.mismatch(expected=UPSTREAM),
            self.mismatch(actual="sha256-" + "x" * 43 + "="),
            self.mismatch(action="result"),
            self.mismatch() * 2,
            self.mismatch() + '@nix {"action":"msg","level":0,"msg":"other build error"}\n',
        ):
            with self.subTest(diagnostic=diagnostic):
                self.diagnostic = diagnostic
                self.commands.clear()
                with self.assertRaises(subprocess.CalledProcessError):
                    self.update()
                self.assertEqual(len(self.commands), 3)
                self.assert_unchanged()

    def test_failed_verification_leaves_no_candidate_to_publish(self):
        self.build_error = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.update()
        self.assert_unchanged()
