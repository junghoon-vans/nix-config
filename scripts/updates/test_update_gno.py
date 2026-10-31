import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("update_gno", Path(__file__).with_name("update-gno.py"))
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class GnoUpdateTests(unittest.TestCase):
    def test_release_tag_resolves_commit_not_moving_target_branch(self):
        commit = "a" * 40
        with patch.object(updater.fixed_release, "github_json", side_effect=[
            {"tag_name": "v1.5.1", "target_commitish": "master"}, {"sha": commit},
        ]) as request:
            self.assertEqual(updater.latest_release("gnolang/gno"), ("v1.5.1", commit))
        self.assertEqual(request.call_args.args, ("/repos/gnolang/gno/commits/v1.5.1",))

    def test_rejects_nonstable_releases_before_resolving_source(self):
        for release in (
            {"tag_name": "v1.5.1-rc1"}, {"tag_name": "chain/mainnet"},
            {"tag_name": "v1.5.1", "draft": True},
            {"tag_name": "v1.5.1", "prerelease": True},
        ):
            with self.subTest(release=release), patch.object(updater.fixed_release, "github_json", return_value=release):
                with self.assertRaises(ValueError):
                    updater.latest_release("gnolang/gno")

    def test_network_failure_is_not_a_dependency_hash(self):
        result = subprocess.CompletedProcess([], 1, "", "error: unable to download dependencies")
        with patch.object(updater, "build", return_value=result), self.assertRaisesRegex(RuntimeError, "unable to download"):
            updater.dependency_hash(Path("unused"), 0)

    @unittest.skipUnless(shutil.which("nix"), "Nix is required to evaluate staged packages")
    def test_update_evaluates_staged_packages_before_publishing_pins(self):
        source = updater.ROOT
        original = (source / "modules/languages/gno.nix").read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "modules/languages/gno.nix"
            path.parent.mkdir(parents=True)
            path.write_text(original)
            checker = root / "scripts/validation/check-gnopls.py"
            checker.parent.mkdir(parents=True)
            shutil.copyfile(source / checker.relative_to(root), checker)
            for name in ("flake.nix", "flake.lock"):
                shutil.copyfile(source / name, root / name)
            run = subprocess.run
            evaluated = []

            def evaluate(module, selection):
                result = run(
                    ["nix", "eval", "--impure", "--offline", "--json", "--expr",
                     updater.expression(module, "builtins.map (package: package.drvPath) packages")],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                evaluated.extend(json.loads(result.stdout))
                return subprocess.CompletedProcess([], 0, "[]", "")

            prefetched = subprocess.CompletedProcess([], 0, '{"hash": "' + updater.FAKE_HASH + '"}', "")
            with patch.object(updater, "ROOT", root), \
                 patch.object(updater, "latest_release", side_effect=[("v1.5.1", "a" * 40), ("v0.1.0", "b" * 40)]), \
                 patch.object(updater.subprocess, "run", return_value=prefetched), \
                 patch.object(updater, "dependency_hash", return_value=updater.FAKE_HASH), \
                 patch.object(updater, "build", side_effect=evaluate):
                updater.main()
            self.assertEqual(updater.pin(path.read_text(), "gnoRev"), "a" * 40)
            self.assertEqual(updater.pin(path.read_text(), "gnoplsRev"), "b" * 40)
            self.assertEqual(len(evaluated), 2)
            self.assertTrue(all(value.startswith("/nix/store/") and value.endswith(".drv") for value in evaluated))

    def test_failed_build_preserves_all_pins(self):
        original = (updater.ROOT / "modules/languages/gno.nix").read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "modules/languages/gno.nix"
            path.parent.mkdir(parents=True)
            path.write_text(original)
            checker = root / "scripts/validation/check-gnopls.py"
            checker.parent.mkdir(parents=True)
            shutil.copyfile(updater.ROOT / checker.relative_to(root), checker)
            prefetched = subprocess.CompletedProcess([], 0, '{"hash": "sha256-new-source"}', "")
            with patch.object(updater, "ROOT", root), \
                 patch.object(updater, "latest_release", side_effect=[("v1.5.1", "a" * 40), ("v0.1.0", "b" * 40)]), \
                 patch.object(updater.subprocess, "run", return_value=prefetched), \
                 patch.object(updater, "dependency_hash", return_value="sha256-new-dependencies"), \
                 patch.object(updater, "build", side_effect=subprocess.CalledProcessError(1, "nix build")):
                with self.assertRaises(subprocess.CalledProcessError):
                    updater.main()
            self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
