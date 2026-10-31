# Local patches

Package-scoped patch records live in `patches/<package>/`. This directory is storage
and review documentation only: nothing here is imported by the flake or applied to
installed applications.

```text
patches/
  README.md
  kakaotalk/
    README.md          # Research record only; no patch included
```

## Layout and ownership

The existing `packages/` directory contains flat package expressions; `modules/`
owns workstation configuration. There is no existing patch collection or overlay
directory. Keep patch material together here without introducing a new package,
overlay, activation hook, or module. Each package directory owns its patch files and
README; add real `.patch` files only after reviewing their source and license.

Nixpkgs keeps patches adjacent to the owning package expression and references them
explicitly with relative paths. This repository uses the same package-scoped
ownership, but a separate root because this collection does not yet have package
expressions that consume it. If a package later moves into `packages/<package>/`,
move its patch files and record alongside it rather than maintaining two copies.

Observed reference (pinned revision):

- [Nixpkgs Bash expression](https://github.com/NixOS/nixpkgs/blob/0edcb15e46cdb83011f3e2ad10d01c36bffeaf07/pkgs/shells/bash/5.nix#L92-L101): appends `./pgrp-pipe-5.patch` to `patches` and declares `patchFlags`.
- [Adjacent patch](https://github.com/NixOS/nixpkgs/blob/0edcb15e46cdb83011f3e2ad10d01c36bffeaf07/pkgs/shells/bash/pgrp-pipe-5.patch).

## Required package record

Before adding or consuming a patch, record in that package's README:

- Purpose, upstream issue/PR and source URL pinned to a commit; local modifications.
- Exact target package version/build, supported OS and architectures.
- Input source/archive or original executable SHA-256, identifying exactly what was
  hashed; patch SHA-256 (or integrity hash for a remotely fetched patch).
- Patch author, license/SPDX identifier and redistribution permission, separately
  from the target application's license. Unknown permission blocks vendoring.
- Status: research-only, reviewed, or verified; actual validation commands, date,
  results and untested architectures. Never infer runtime success from a build.
- Upgrade procedure: recheck version and input hash, review upstream changes and
  rerun applicability/build/runtime checks. Reject unknown inputs rather than
  silently patching a newer release.
- Removal condition: upstream fix, no longer needed, incompatible target, or
  unverifiable provenance/license; remove the consumer together with the patch.

Store reviewable patch text and metadata only. Do not add proprietary application
bundles, original or patched executables, installers, private keys, credentials,
signing identities, entitlements exported from a local installation, or user state.

## Future Nix connection (not enabled)

For an ordinary source patch, a future expression in `packages/<package>.nix` can
append to an existing derivation's patches:

```nix
package.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ../patches/<package>/fix.patch ];
})
```

This is an illustrative path, not an existing file or runnable configuration.
Relative paths resolve from the consuming Nix file. Preserve existing patches and
review strip level/`patchFlags`; a source patch is normally applied during
`stdenv`'s patch phase. A binary application patcher is not a source `.patch` and
cannot be connected merely by placing it in `patches`.

Any future binary patching/signing workflow needs separate implementation approval,
input integrity and architecture checks, license review, and build/runtime proof.
This directory does not authorize installation, application modification, signing,
activation, or hosts/certificate changes.
