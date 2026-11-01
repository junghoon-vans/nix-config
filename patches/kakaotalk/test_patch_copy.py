"""Filesystem boundary tests; no proprietary application or signing required."""

from pathlib import Path
import plistlib
import tempfile
import unittest

import patch_copy
from patch_copy import patcher


class OutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'KakaoTalk.app'
        self.source.mkdir()

    def test_rejects_source_and_nested_output(self):
        for output in (self.source, self.source / 'patched'):
            with self.subTest(output=output), self.assertRaises(patcher.PatchError):
                patch_copy.output_path(self.source, output)

    def test_rejects_symlink_alias_into_source(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(patcher.PatchError):
            patch_copy.output_path(self.source, alias / 'patched')
        self.assertFalse((self.source / 'patched').exists())

    def test_rejects_existing_output_without_touching_content(self):
        output = self.root / 'output'
        output.mkdir()
        sentinel = output / 'keep'
        sentinel.write_bytes(b'caller content')
        with self.assertRaises(patcher.PatchError):
            patch_copy.output_path(self.source, output)
        self.assertEqual(sentinel.read_bytes(), b'caller content')

    def test_rejects_dangling_output_symlink(self):
        output = self.root / 'output'
        output.symlink_to(self.root / 'missing')
        with self.assertRaises(patcher.PatchError):
            patch_copy.output_path(self.source, output)
        self.assertTrue(output.is_symlink())

    def test_rejects_installation_bundle_and_store_destinations(self):
        applications = self.root / 'Applications'
        bundle = self.root / 'Other.app'
        applications.mkdir()
        bundle.mkdir()
        for output in (applications / 'patched', bundle / 'patched', Path('/nix/store/patched')):
            with self.subTest(output=output), self.assertRaises(patcher.PatchError):
                patch_copy.output_path(self.source, output)

    def test_rejects_case_variants_on_case_insensitive_filesystems(self):
        for name in ('applications', 'Other.APP'):
            parent = self.root / name
            parent.mkdir()
            with self.subTest(parent=parent), self.assertRaises(patcher.PatchError):
                patch_copy.output_path(self.source, parent / 'patched')

    def test_unsupported_version_leaves_no_output_and_preserves_source(self):
        contents = self.source / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        info = plistlib.dumps({
            'CFBundleIdentifier': patcher.TARGET.bundle_id,
            'CFBundleShortVersionString': 'unsupported',
            'CFBundleVersion': patcher.TARGET.build,
        })
        (contents / 'Info.plist').write_bytes(info)
        binary = contents / 'MacOS/KakaoTalk'
        binary.write_bytes(b'not a production executable')
        output = self.root / 'output'
        with self.assertRaisesRegex(patcher.PatchError, 'CFBundleShortVersionString'):
            patch_copy.patch_copy(self.source, output)
        self.assertFalse(output.exists())
        self.assertEqual((contents / 'Info.plist').read_bytes(), info)
        self.assertEqual(binary.read_bytes(), b'not a production executable')

    def test_unknown_binary_fails_before_creating_output(self):
        contents = self.source / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': patcher.TARGET.bundle_id,
            'CFBundleShortVersionString': patcher.TARGET.version,
            'CFBundleVersion': patcher.TARGET.build,
        }))
        (contents / 'MacOS/KakaoTalk').write_bytes(b'unsupported Mach-O')
        output = self.root / 'output'
        with self.assertRaises(patcher.PatchError):
            patch_copy.patch_copy(self.source, output)
        self.assertFalse(output.exists())
        self.assertEqual((contents / 'MacOS/KakaoTalk').read_bytes(), b'unsupported Mach-O')


if __name__ == '__main__':
    unittest.main()
