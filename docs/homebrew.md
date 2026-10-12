# Homebrew

nix-darwin owns the declared Homebrew inventory in `modules/darwin.nix`. Activation installs
missing formulae and casks but never updates, upgrades, cleans, or removes packages automatically.
Those operations require explicit review and approval.

## Inventory

See [Managed apps and tools](apps.md) for the generated formula, cask, and Mac App Store
tables, including host coverage and declaration locations. These tables come from evaluated
Nix configuration rather than a separately maintained package list.

After changing package declarations, run `make inventory` and include `docs/apps.md` in
the same change. `make check` verifies synchronization in CI.

## Reviewing upgrades

```sh
brew update
brew outdated
```

After review and explicit approval:

```sh
brew upgrade
brew upgrade neovim
```

Homebrew versions are mutable local state. Move a version-sensitive runtime to a Nix language
profile when every supported host must use the same version.

Removing an item from the inventory does not delete an existing Homebrew or user-local
installation. Cleanup requires separate approval. In particular, use
`/run/current-system/sw/bin/apm` for version-sensitive APM operations while legacy installations
remain.
