"""Patch a new output copy; never mutate the explicitly supplied source app."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

import patch_kakaotalk as patcher


def output_path(source: Path, output: Path) -> Path:
    # Resolve existing parents before checking containment, including symlink aliases.
    output = output.parent.resolve(strict=True) / output.name
    if output == source or source in output.parents:
        raise patcher.PatchError('Output must be outside the source application')
    if any(p.name.casefold() == 'applications' or p.suffix.casefold() == '.app' for p in (output, *output.parents)):
        raise patcher.PatchError('Output must not be inside Applications or an application bundle')
    if tuple(part.casefold() for part in output.parts[:3]) == ('/', 'nix', 'store'):
        raise patcher.PatchError('Proprietary application output must not enter the Nix store')
    if os.path.lexists(output):
        raise patcher.PatchError(f'Output already exists; refusing to overwrite: {output}')
    patcher._require_local_path(output)
    return output


def patch_copy(source: Path, output: Path) -> Path:
    source = patcher._absolute(source)
    # Inspect the full version/build, universal layout, original hash and patch bytes.
    if patcher.inspect_app(source) != patcher.AppState.ORIGINAL:
        raise patcher.PatchError('Source must be the supported unmodified original application')
    output = output_path(source, patcher._absolute(output))
    patcher.verify_signature(source)
    original_entitlements = patcher.extract_entitlements(source)
    manifest = patcher.tree_manifest(source)

    # mkdir is exclusive: never merge into or replace an existing output directory.
    output.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix='.patch-', dir=output) as staging:
            app = Path(staging) / 'KakaoTalk.app'
            patcher._run(['/usr/bin/ditto', str(source), str(app)])
            if patcher.tree_manifest(app) != manifest:
                raise patcher.PatchError('Copied bundle differs from the verified source')
            patcher.verify_signature(app)
            executable, original = patcher._read_executable(app, patcher.TARGET)
            replacement = patcher.patched_executable(original)
            patcher._refuse_running_target(app)
            patcher._atomic_replace(executable, replacement)
            patcher.resign_app(app, original_entitlements)
            patcher.verify_unchanged_resources(app, source)
            if patcher.tree_manifest(source) != manifest:
                raise patcher.PatchError('Source changed during patching; refusing to publish output')
            destination = output / 'KakaoTalk.app'
            app.rename(destination)
        return destination
    except BaseException:
        # Only remove our empty reservation. Never recursively delete caller content.
        try:
            output.rmdir()
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='Create a patched, ad-hoc signed copy of KakaoTalk 26.9.0 (2006), '
        'universal x86_64/arm64. Does not install or launch it.'
    )
    parser.add_argument('--source', required=True, type=Path, help='explicit unmodified KakaoTalk.app input (read only)')
    parser.add_argument('--output', required=True, type=Path, help='new local directory; parent must exist; receives KakaoTalk.app')
    args = parser.parse_args(argv)
    try:
        destination = patch_copy(args.source.expanduser(), args.output.expanduser())
    except (patcher.PatchError, OSError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    print(f'PATCHED: {destination}; signature and original entitlements verified; source unchanged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
