"""Runtime-only installed-app transaction. Never invoked by a Nix build."""

import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from patch_copy import patch_copy, patcher

APP = Path('/Applications/KakaoTalk.app')
STATE = Path('/Library/Application Support/nix-kakaotalk')
PATCHER_ID = os.environ.get('NIX_KAKAOTALK_PATCHER_ID', 'development')


def _trusted_parents(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        # /Applications commonly permits the privileged macOS admin group (gid 80).
        unsafe_write = info.st_mode & 0o002 or (info.st_mode & 0o020 and info.st_gid not in (0, 80))
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or unsafe_write:
            raise patcher.PatchError(f'Unsafe parent directory: {parent}')


def _secure_directory(path):
    _trusted_parents(path.parent)
    if not os.path.lexists(path):
        path.mkdir(mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise patcher.PatchError(f'State must be a private, owned real directory: {path}')
    patcher._require_local_path(path)


def _swap(left, right):
    # RENAME_SWAP is one atomic namespace operation; neither app path disappears.
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    swap = libc.renameatx_np
    swap.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    swap.restype = ctypes.c_int
    if swap(-2, os.fsencode(left), -2, os.fsencode(right), 0x00000002):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _running(app):
    patcher._refuse_running_target(app)


def _prepare(app, output):
    return patch_copy(app, output)


def _seal(app):
    # ditto preserves ACLs/owners. Never publish user-writable or privileged files as root.
    patcher._run(['/bin/chmod', '-RN', str(app)])
    for directory, dirs, files in os.walk(app, followlinks=False):
        for path in (Path(directory), *(Path(directory) / name for name in dirs + files)):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                os.chown(path, os.geteuid(), os.getegid(), follow_symlinks=False)
                continue
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise patcher.PatchError(f'Unsafe staged entry: {path}')
            os.chown(path, os.geteuid(), os.getegid(), follow_symlinks=False)
            os.chmod(path, 0o755 if stat.S_ISDIR(info.st_mode) or info.st_mode & 0o111 else 0o644)


def _verify_sealed(app):
    for directory, dirs, files in os.walk(app, followlinks=False):
        for path in (Path(directory), *(Path(directory) / name for name in dirs + files)):
            info = path.lstat()
            if info.st_uid != os.geteuid():
                raise patcher.PatchError(f'Published bundle is not owned by the activation user: {path}')
            if not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o6022:
                raise patcher.PatchError(f'Published bundle has unsafe permissions: {path}')


def _record(state):
    path = state / 'current.json'
    if not os.path.lexists(path):
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077:
        raise patcher.PatchError('Unsafe activation journal')
    record = json.loads(patcher._read_regular_bytes(path))
    transaction = record['transaction']
    if not isinstance(transaction, str) or not transaction.startswith('transaction-') or Path(transaction).name != transaction:
        raise patcher.PatchError('Invalid activation journal transaction')
    return record


def _journal(state, record):
    descriptor, name = tempfile.mkstemp(prefix='.journal-', dir=state)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, state / 'current.json')
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def _verify(app, manifest, expected):
    if patcher.tree_manifest(app) != manifest or patcher.inspect_app(app) != expected:
        raise patcher.PatchError(f'Application no longer matches the transaction: {app}')
    patcher.verify_signature(app)


def _rollback(app, state, record):
    if record is None:
        raise patcher.PatchError('No managed original backup is recorded')
    transaction = state / record['transaction']
    _secure_directory(transaction)
    backup = transaction / 'output' / 'KakaoTalk.app'
    _verify(app, record['patched'], patcher.AppState.PATCHED)
    _verify(backup, record['original'], patcher.AppState.ORIGINAL)
    _running(app)
    _swap(app, backup)
    try:
        _verify(app, record['original'], patcher.AppState.ORIGINAL)
    except BaseException:
        _swap(app, backup)
        raise
    # Keep the journal: a crash before/after this point is distinguishable by manifests.
    return 'RESTORED: original KakaoTalk; the next switch will reapply the patch'


def activate(app: Path, state: Path, rollback: bool = False) -> str:
    app = patcher._absolute(app)
    state = patcher._absolute(state)
    _trusted_parents(app.parent)
    if not os.path.lexists(app):
        if rollback:
            raise patcher.PatchError('Installed application is absent; refusing rollback')
        return 'SKIP: KakaoTalk is not installed'
    patcher._app_paths(app)
    patcher._require_local_path(app)
    _secure_directory(state)
    if state.stat().st_dev != app.parent.stat().st_dev:
        raise patcher.PatchError('Application and backup state must share a filesystem for atomic exchange')
    lock = os.open(state / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise patcher.PatchError('Unsafe activation lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise patcher.PatchError('Another KakaoTalk transaction is running') from error
        record = _record(state)
        if rollback:
            return _rollback(app, state, record)
        current = patcher.inspect_app(app)
        if current == patcher.AppState.PATCHED:
            if record is None or record['patcher'] != PATCHER_ID:
                raise patcher.PatchError('Already patched by another/unknown patcher; rollback explicitly before migrating')
            _verify(app, record['patched'], patcher.AppState.PATCHED)
            _verify_sealed(app)
            _secure_directory(state / record['transaction'])
            _verify(state / record['transaction'] / 'output' / 'KakaoTalk.app', record['original'], patcher.AppState.ORIGINAL)
            return 'UNCHANGED: same original and patcher; verified installed app and backup'
        _running(app)
        original = patcher.tree_manifest(app)
        identity = (app.stat().st_dev, app.stat().st_ino)
        transaction = Path(tempfile.mkdtemp(prefix='transaction-', dir=state))
        # Retain failed staging and all old backups; never recursively delete caller data.
        staged = _prepare(app, transaction / 'output')
        _seal(staged)
        patched = patcher.tree_manifest(staged)
        _verify(staged, patched, patcher.AppState.PATCHED)
        _verify_sealed(staged)
        _verify(app, original, patcher.AppState.ORIGINAL)
        _running(app)
        if identity != (app.stat().st_dev, app.stat().st_ino):
            raise patcher.PatchError('Installed app was replaced during staging')
        record = {'transaction': transaction.name, 'patcher': PATCHER_ID, 'original': original, 'patched': patched}
        # Write intent before exchange. After a crash the app + backup manifests identify the side.
        _journal(state, record)
        _swap(app, staged)
        try:
            _verify(app, patched, patcher.AppState.PATCHED)
            _verify(staged, original, patcher.AppState.ORIGINAL)
        except BaseException:
            # Restore only our known published bytes, never overwrite a concurrent updater.
            if patcher.tree_manifest(app) != patched:
                raise patcher.PatchError(f'Concurrent app change after publication; original retained at {staged}')
            _swap(app, staged)
            raise
        return f'PATCHED: {app}; original retained at {staged}'
    finally:
        os.close(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Switch-managed KakaoTalk activation; fixed installed path, private original backup')
    parser.add_argument('--rollback', action='store_true', help='restore the verified original; next switch reapplies')
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise patcher.PatchError('Run as root (normally via darwin-rebuild switch)')
        print(activate(APP, STATE, args.rollback))
        return 0
    except (patcher.PatchError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'WARNING: KakaoTalk {"rollback failed" if args.rollback else "activation skipped"}: {error}', file=sys.stderr)
        return 1 if args.rollback else 0


if __name__ == '__main__':
    raise SystemExit(main())
