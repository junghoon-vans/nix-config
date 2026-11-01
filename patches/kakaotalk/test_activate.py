"""Synthetic filesystem tests for the installed-app activation transaction.

Every KakaoTalk.app in this module is a temporary fixture with fake metadata,
a marker executable, and fake signing data; no proprietary app or system path
is read or mutated.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import activate
from patch_copy import patcher


_ORIGINAL_V1 = b'fixture-original-executable-v1'
_PATCHED_V1 = b'fixture-patched-executable-v1'
_ORIGINAL_V2 = b'fixture-original-executable-v2'
_PATCHED_V2 = b'fixture-patched-executable-v2'


class ActivationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.app_parent = self.root / 'installed'
        self.app_parent.mkdir()
        self.app = self.app_parent / 'KakaoTalk.app'
        self.state = self.root / 'private-state'
        self._write_app(self.app)

        self.patches = ExitStack()
        self.addCleanup(self.patches.close)

        def trusted_fixture_parents(path):
            # Validate fixture ancestors, but do not reject the build sandbox's
            # unrelated global temporary-directory ancestors.
            for candidate in (Path(path), *Path(path).parents):
                if candidate != self.root and self.root not in candidate.parents:
                    break
                info = candidate.lstat()
                unsafe_write = info.st_mode & 0o002 or (
                    info.st_mode & 0o020 and info.st_gid not in (0, 80)
                )
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or info.st_uid not in (0, os.geteuid())
                    or unsafe_write
                ):
                    raise patcher.PatchError(f'Unsafe fixture parent directory: {candidate}')

        self.patches.enter_context(patch.object(
            activate, '_trusted_parents', side_effect=trusted_fixture_parents,
        ))
        self.patches.enter_context(patch.object(patcher, '_require_local_path', return_value=None))
        self.patches.enter_context(patch.object(patcher, '_refuse_running_target', return_value=None))
        self.patches.enter_context(patch.object(patcher, 'verify_signature', return_value=None))
        self.patches.enter_context(patch.object(patcher, 'extract_entitlements', return_value=b'fixture entitlements'))
        self.patches.enter_context(patch.object(patcher, 'inspect_app', side_effect=self._inspect_fixture))
        self.patches.enter_context(patch.object(patcher, '_read_executable', side_effect=self._read_fixture_executable))
        self.patches.enter_context(patch.object(patcher, 'patched_executable', side_effect=self._patch_fixture_executable))
        self.patches.enter_context(patch.object(patcher, 'resign_app', side_effect=self._sign_fixture))
        self.patches.enter_context(patch.object(patcher, '_run', side_effect=self._run_fixture_command))
        self.patches.enter_context(patch.object(activate, '_running', return_value=None))

    @staticmethod
    def _executable(app):
        return app / 'Contents' / 'MacOS' / 'KakaoTalk'

    @staticmethod
    def _write_app(app, executable=_ORIGINAL_V1, resource=b'fixture-resource-v1'):
        contents = app / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Resources').mkdir()
        signature = contents / '_CodeSignature'
        signature.mkdir()
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': patcher.TARGET.bundle_id,
            'CFBundleShortVersionString': patcher.TARGET.version,
            'CFBundleVersion': patcher.TARGET.build,
        }))
        (contents / 'MacOS' / 'KakaoTalk').write_bytes(executable)
        (contents / 'Resources' / 'fixture.dat').write_bytes(resource)
        (signature / 'CodeResources').write_bytes(b'fixture-original-signature')

    @staticmethod
    def _inspect_fixture(app, target=patcher.TARGET):
        data = ActivationTransactionTests._executable(app).read_bytes()
        if data in (_ORIGINAL_V1, _ORIGINAL_V2):
            return patcher.AppState.ORIGINAL
        if data in (_PATCHED_V1, _PATCHED_V2):
            return patcher.AppState.PATCHED
        raise patcher.PatchError(f'Unsupported synthetic fixture executable: {data!r}')

    @staticmethod
    def _read_fixture_executable(app, target=patcher.TARGET):
        executable = ActivationTransactionTests._executable(app)
        return executable, executable.read_bytes()

    @staticmethod
    def _patch_fixture_executable(data, target=patcher.TARGET):
        replacements = {_ORIGINAL_V1: _PATCHED_V1, _ORIGINAL_V2: _PATCHED_V2}
        try:
            return replacements[data]
        except KeyError as error:
            raise patcher.PatchError('Unsupported synthetic fixture executable') from error

    @staticmethod
    def _sign_fixture(app, entitlements):
        code_resources = app / 'Contents' / '_CodeSignature' / 'CodeResources'
        code_resources.write_bytes(b'fixture-signed:' + ActivationTransactionTests._executable(app).read_bytes())

    @staticmethod
    def _run_fixture_command(command, **kwargs):
        if command[0] == '/usr/bin/ditto':
            shutil.copytree(Path(command[1]), Path(command[2]), symlinks=True)
            return None
        if command[:2] == ['/bin/chmod', '-RN']:
            return None
        raise AssertionError(f'Unexpected production command in fixture: {command!r}')

    def _record(self):
        return json.loads((self.state / 'current.json').read_text())

    def _backup_for(self, record):
        return self.state / record['transaction'] / 'output' / 'KakaoTalk.app'

    def _transactions(self):
        return sorted(path.name for path in self.state.glob('transaction-*'))

    def _assert_original_v1_installed(self):
        self.assertEqual(self._executable(self.app).read_bytes(), _ORIGINAL_V1)
        self.assertEqual((self.app / 'Contents' / 'Resources' / 'fixture.dat').read_bytes(), b'fixture-resource-v1')

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_first_publish_keeps_verified_original_backup(self):
        result = activate.activate(self.app, self.state)

        self.assertTrue(result.startswith('PATCHED: '), result)
        self.assertEqual(self._executable(self.app).read_bytes(), _PATCHED_V1)
        record = self._record()
        backup = self._backup_for(record)
        self.assertEqual(self._executable(backup).read_bytes(), _ORIGINAL_V1)
        self.assertEqual((backup / 'Contents' / 'Resources' / 'fixture.dat').read_bytes(), b'fixture-resource-v1')
        self.assertEqual(record['patcher'], activate.PATCHER_ID)
        self.assertEqual(record['patched'], patcher.tree_manifest(self.app))
        self.assertEqual(record['original'], patcher.tree_manifest(backup))
        self.assertTrue(record['transaction'].startswith('transaction-'))

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_same_patcher_repeated_activation_is_a_verified_no_op(self):
        activate.activate(self.app, self.state)
        record_bytes = (self.state / 'current.json').read_bytes()
        installed_manifest = patcher.tree_manifest(self.app)
        backup = self._backup_for(self._record())
        backup_manifest = patcher.tree_manifest(backup)

        result = activate.activate(self.app, self.state)

        self.assertTrue(result.startswith('UNCHANGED: '), result)
        self.assertEqual((self.state / 'current.json').read_bytes(), record_bytes)
        self.assertEqual(self._transactions(), [self._record()['transaction']])
        self.assertEqual(patcher.tree_manifest(self.app), installed_manifest)
        self.assertEqual(patcher.tree_manifest(backup), backup_manifest)

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_no_op_rejects_group_writable_installed_executable(self):
        activate.activate(self.app, self.state)
        executable = self._executable(self.app)
        executable.chmod(0o664)

        with self.assertRaisesRegex(patcher.PatchError, 'unsafe permissions'):
            activate.activate(self.app, self.state)

        self.assertEqual(executable.read_bytes(), _PATCHED_V1)
        self.assertEqual(executable.stat().st_mode & 0o777, 0o664)
        self.assertEqual(len(self._transactions()), 1)

    def test_symlinked_source_executable_is_refused(self):
        executable = self._executable(self.app)
        external = self.root / 'external-executable'
        external.write_bytes(_ORIGINAL_V1)
        executable.unlink()
        executable.symlink_to(external)

        with self.assertRaises(patcher.PatchError):
            activate.activate(self.app, self.state)

        self.assertTrue(executable.is_symlink())
        self.assertEqual(external.read_bytes(), _ORIGINAL_V1)
        self.assertFalse((self.state / 'current.json').exists())

    def test_symlinked_journal_is_refused(self):
        self.state.mkdir(mode=0o700)
        target = self.root / 'journal-target'
        target.write_text('{}')
        (self.state / 'current.json').symlink_to(target)

        with self.assertRaisesRegex(patcher.PatchError, 'Unsafe activation journal'):
            activate.activate(self.app, self.state)

        self.assertTrue((self.state / 'current.json').is_symlink())
        self.assertEqual(self._executable(self.app).read_bytes(), _ORIGINAL_V1)

    def test_symlinked_lock_is_refused(self):
        self.state.mkdir(mode=0o700)
        target = self.root / 'lock-target'
        target.write_bytes(b'')
        (self.state / 'lock').symlink_to(target)

        with self.assertRaises(OSError):
            activate.activate(self.app, self.state)

        self.assertTrue((self.state / 'lock').is_symlink())
        self.assertEqual(self._executable(self.app).read_bytes(), _ORIGINAL_V1)

    def test_missing_application_is_skipped_without_creating_state(self):
        result = activate.activate(self.app_parent / 'missing.app', self.state)

        self.assertEqual(result, 'SKIP: KakaoTalk is not installed')
        self.assertFalse(self.state.exists())

    def test_unsupported_original_is_rejected_before_staging(self):
        (self._executable(self.app)).write_bytes(b'unsupported synthetic executable')

        with self.assertRaises(patcher.PatchError):
            activate.activate(self.app, self.state)

        self.assertEqual(self._executable(self.app).read_bytes(), b'unsupported synthetic executable')
        self.assertEqual(self._transactions(), [])
        self.assertFalse((self.state / 'current.json').exists())

    def test_running_source_is_not_staged_or_replaced(self):
        original_manifest = patcher.tree_manifest(self.app)
        with patch.object(activate, '_running', side_effect=patcher.PatchError('synthetic app is running')):
            with self.assertRaisesRegex(patcher.PatchError, 'synthetic app is running'):
                activate.activate(self.app, self.state)

        self.assertEqual(patcher.tree_manifest(self.app), original_manifest)
        self.assertEqual(self._transactions(), [])
        self.assertFalse((self.state / 'current.json').exists())

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_failed_publication_preserves_original_and_retry_recovers_journal(self):
        with patch.object(activate, '_swap', side_effect=OSError('synthetic exchange failure')):
            with self.assertRaisesRegex(OSError, 'synthetic exchange failure'):
                activate.activate(self.app, self.state)

        self._assert_original_v1_installed()
        failed_record = self._record()
        failed_transaction = failed_record['transaction']
        self.assertEqual(self._executable(self._backup_for(failed_record)).read_bytes(), _PATCHED_V1)

        result = activate.activate(self.app, self.state)

        self.assertTrue(result.startswith('PATCHED: '), result)
        active_record = self._record()
        self.assertNotEqual(active_record['transaction'], failed_transaction)
        self.assertEqual(self._executable(self.app).read_bytes(), _PATCHED_V1)
        self.assertEqual(self._executable(self._backup_for(active_record)).read_bytes(), _ORIGINAL_V1)
        self.assertEqual(self._transactions(), sorted((failed_transaction, active_record['transaction'])))

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_post_publish_validation_failure_atomically_restores_original(self):
        verify = activate._verify

        def fail_published_app(app, manifest, expected):
            if app == self.app and expected == patcher.AppState.PATCHED:
                raise patcher.PatchError('synthetic post-publication validation failure')
            return verify(app, manifest, expected)

        with patch.object(activate, '_verify', side_effect=fail_published_app):
            with self.assertRaisesRegex(patcher.PatchError, 'post-publication validation failure'):
                activate.activate(self.app, self.state)

        self._assert_original_v1_installed()
        record = self._record()
        self.assertEqual(self._executable(self._backup_for(record)).read_bytes(), _PATCHED_V1)
        self.assertEqual(patcher.tree_manifest(self.app), record['original'])

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_rollback_restores_recorded_original(self):
        activate.activate(self.app, self.state)
        record = self._record()
        backup = self._backup_for(record)

        result = activate.activate(self.app, self.state, rollback=True)

        self.assertTrue(result.startswith('RESTORED: '), result)
        self.assertEqual(self._executable(self.app).read_bytes(), _ORIGINAL_V1)
        self.assertEqual(patcher.tree_manifest(self.app), record['original'])
        self.assertEqual(self._executable(backup).read_bytes(), _PATCHED_V1)
        self.assertEqual((self.state / 'current.json').exists(), True)

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_update_is_backed_up_before_repatch_and_old_backup_is_preserved(self):
        activate.activate(self.app, self.state)
        first_record = self._record()
        first_backup = self._backup_for(first_record)
        first_backup_manifest = patcher.tree_manifest(first_backup)

        self._executable(self.app).write_bytes(_ORIGINAL_V2)
        (self.app / 'Contents' / 'Resources' / 'fixture.dat').write_bytes(b'fixture-resource-v2')
        (self.app / 'Contents' / '_CodeSignature' / 'CodeResources').write_bytes(b'fixture-original-signature-v2')

        result = activate.activate(self.app, self.state)

        self.assertTrue(result.startswith('PATCHED: '), result)
        second_record = self._record()
        self.assertNotEqual(first_record['transaction'], second_record['transaction'])
        self.assertEqual(self._executable(self.app).read_bytes(), _PATCHED_V2)
        second_backup = self._backup_for(second_record)
        self.assertEqual(self._executable(second_backup).read_bytes(), _ORIGINAL_V2)
        self.assertEqual((second_backup / 'Contents' / 'Resources' / 'fixture.dat').read_bytes(), b'fixture-resource-v2')
        self.assertEqual(patcher.tree_manifest(first_backup), first_backup_manifest)
        self.assertEqual(self._executable(first_backup).read_bytes(), _ORIGINAL_V1)
        self.assertCountEqual(self._transactions(), [first_record['transaction'], second_record['transaction']])

    def test_symlink_state_path_is_refused(self):
        target = self.root / 'real-state-target'
        target.mkdir(mode=0o700)
        self.state.symlink_to(target, target_is_directory=True)
        original_manifest = patcher.tree_manifest(self.app)

        with self.assertRaises(patcher.PatchError):
            activate.activate(self.app, self.state)

        self.assertEqual(patcher.tree_manifest(self.app), original_manifest)
        self.assertEqual(list(target.iterdir()), [])

    def test_insecure_state_permissions_are_refused(self):
        self.state.mkdir(mode=0o755)
        self.state.chmod(0o755)
        original_manifest = patcher.tree_manifest(self.app)

        with self.assertRaises(patcher.PatchError):
            activate.activate(self.app, self.state)

        self.assertEqual(patcher.tree_manifest(self.app), original_manifest)
        self.assertFalse((self.state / 'lock').exists())

    def test_already_patched_without_our_journal_is_refused(self):
        self._executable(self.app).write_bytes(_PATCHED_V1)

        with self.assertRaisesRegex(patcher.PatchError, 'unknown patcher'):
            activate.activate(self.app, self.state)

        self.assertEqual(self._executable(self.app).read_bytes(), _PATCHED_V1)
        self.assertFalse((self.state / 'current.json').exists())

    @unittest.skipUnless(sys.platform == 'darwin', 'activation uses Darwin RENAME_SWAP for real directory exchange')
    def test_rollback_refuses_modified_installed_app_without_touching_backup(self):
        activate.activate(self.app, self.state)
        record = self._record()
        backup = self._backup_for(record)
        (self.app / 'Contents' / 'Resources' / 'fixture.dat').write_bytes(b'concurrent post-publish edit')

        with self.assertRaises(patcher.PatchError):
            activate.activate(self.app, self.state, rollback=True)

        self.assertEqual((self.app / 'Contents' / 'Resources' / 'fixture.dat').read_bytes(), b'concurrent post-publish edit')
        self.assertEqual(self._executable(self.app).read_bytes(), _PATCHED_V1)
        self.assertEqual(self._executable(backup).read_bytes(), _ORIGINAL_V1)

    def test_concurrent_source_update_during_staging_is_not_overwritten(self):
        prepare = activate._prepare

        def prepare_then_update(app, output):
            staged = prepare(app, output)
            (app / 'Contents' / 'Resources' / 'fixture.dat').write_bytes(b'concurrent updater resource')
            return staged

        with patch.object(activate, '_prepare', side_effect=prepare_then_update):
            with self.assertRaisesRegex(patcher.PatchError, 'no longer matches the transaction'):
                activate.activate(self.app, self.state)

        self.assertEqual(self._executable(self.app).read_bytes(), _ORIGINAL_V1)
        self.assertEqual((self.app / 'Contents' / 'Resources' / 'fixture.dat').read_bytes(), b'concurrent updater resource')
        self.assertFalse((self.state / 'current.json').exists())
        transactions = self._transactions()
        self.assertEqual(len(transactions), 1)
        staged = self.state / transactions[0] / 'output' / 'KakaoTalk.app'
        self.assertEqual(self._executable(staged).read_bytes(), _PATCHED_V1)


if __name__ == '__main__':
    unittest.main()
