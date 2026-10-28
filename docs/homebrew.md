# Homebrew

nix-darwin owns the declared Homebrew inventory in `modules/darwin.nix`. Activation installs
missing formulae and casks but never upgrades, cleans, or removes packages automatically.
Tap definitions come from the `homebrew-core` and `homebrew-cask` flake inputs. Update those
pins through Nix instead of trying to mutate Nix-store taps with `brew update`.

## Inventory

See [Managed apps and tools](apps.md) for the generated formula, cask, and Mac App Store
tables, including host coverage and declaration locations. These tables come from evaluated
Nix configuration rather than a separately maintained package list.

After changing package declarations, run `make inventory` and include `docs/apps.md` in
the same change. `make check` verifies synchronization in CI.

## Updating and reviewing upgrades

Update the tap pins from the repository root, without activating the host:

```sh
make brew-update
```

This changes only the `homebrew-core` and `homebrew-cask` inputs in `flake.lock`.
It requires no `HOST`, does not invoke sudo, and does not run Homebrew or activate
any system or Home Manager configuration. If the pin update fails, the command fails.

Review and commit `flake.lock`, then explicitly activate the host and inspect upgrades:

```sh
make switch HOST=junghoonui-MacBookAir
make brew-outdated
```

Use `HOST=junghoonui-MacBookPro` on the Pro. `make switch` applies the entire host
configuration, including Home Manager and services, and installs the locked agent
skills. It is intentionally separate from Homebrew pin updates. If activation fails,
resolve that error before proceeding to package upgrades.

`make brew-outdated` only lists upgrades using the currently activated tap definitions.
It disables automatic tap updates and does not change `flake.lock`, activate the
host, or upgrade packages. Running it before activation still uses the old tap definitions.

Review the list, then explicitly upgrade all eligible installed packages or one named
formula/cask:

```sh
make brew-upgrade
# Or upgrade only Neovim:
make brew-upgrade PACKAGE=neovim
```

The Homebrew targets never run `brew update`. The upgrade target uses the already-activated
tap definitions and disables automatic tap updates. It does not update the lockfile
or activate the host. Homebrew's usual pinning and cask upgrade rules still apply;
self-updating and `version :latest` casks are normally skipped without `--greedy`.

On the other machine, pull the committed lockfile and run `make switch HOST=<host>`,
then `make brew-outdated` and a reviewed upgrade. Do not run `make brew-update` again
unless you intend to advance the pins further.

### Manual equivalent

```sh
nix flake update homebrew-core homebrew-cask
sudo -H darwin-rebuild switch --flake .#junghoonui-MacBookAir
HOMEBREW_NO_AUTO_UPDATE=1 brew outdated
# After review:
HOMEBREW_NO_AUTO_UPDATE=1 brew upgrade
# Or: HOMEBREW_NO_AUTO_UPDATE=1 brew upgrade neovim
```

If activation fails after the lockfile update, the new pins remain in `flake.lock`.
Resolve the activation error and retry the switch before upgrading packages.
These commands update formula/cask definitions and packages, not the Homebrew executable.
The executable source is the `nix-homebrew/brew-src` input in `flake.lock`, overridden in
`flake.nix` independently of `nix-homebrew` so new cask DSL syntax can be supported without
upgrading unrelated dependencies. Both hosts use the locked source's tag for package
metadata; nix-homebrew still applies its self-update and Nix Ruby patches.

To update the executable, change `nix-homebrew.inputs.brew-src.url` in `flake.nix`, then run
`nix flake update nix-homebrew/brew-src`. Review the source hash and revision in `flake.lock`,
build both hosts, and parse any newly required cask syntax with the built Homebrew before
activation. Building does not change the active executable or taps; activation requires
separate approval. A tap-only update cannot fix an older active Homebrew parser.

Hermes is managed by its upstream Nix `messaging` package, not Homebrew. See
[Nix toolchain](nix-toolchain.md#hermes) for its pin, update procedure, and Slack verification.

Homebrew versions are mutable local state. Move a version-sensitive runtime to a Nix language
profile when every supported host must use the same version.

Removing an item from the inventory does not delete an existing Homebrew or user-local
installation. Cleanup requires separate approval. In particular, use
`/run/current-system/sw/bin/apm` for version-sensitive APM operations while legacy installations
remain.
