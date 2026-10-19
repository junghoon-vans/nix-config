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

From the repository root:

```sh
make brew-update HOST=junghoonui-MacBookAir
```

Use `HOST=junghoonui-MacBookPro` on the Pro. The command updates only the two Homebrew
tap inputs in `flake.lock`, runs `darwin-rebuild switch` with sudo, then lists outdated
packages with Homebrew auto-update disabled. It does not upgrade installed packages or
run `setup-apm`. If updating the pins or activating the host fails, it stops before
running Homebrew.

Review the list, then explicitly upgrade all eligible installed packages or one named
formula/cask:

```sh
make brew-upgrade
# Or upgrade only Hermes:
make brew-upgrade PACKAGE=hermes-agent
```

These targets never run `brew update`. The upgrade target uses the already-activated
tap definitions and disables automatic tap updates. It does not update the lockfile
or activate the host. Homebrew's usual pinning and cask upgrade rules still apply;
self-updating and `version :latest` casks are normally skipped without `--greedy`.

Review and commit the changed `flake.lock` so both machines use the same tap revisions.
On the other machine, pull that commit and run `darwin-rebuild switch` for its host
before `make brew-upgrade`; do not run `make brew-update` again unless you intend to
advance the pins further.

### Manual equivalent

```sh
nix flake update homebrew-core homebrew-cask
sudo -H darwin-rebuild switch --flake .#junghoonui-MacBookAir
HOMEBREW_NO_AUTO_UPDATE=1 brew outdated
# After review:
HOMEBREW_NO_AUTO_UPDATE=1 brew upgrade
# Or: HOMEBREW_NO_AUTO_UPDATE=1 brew upgrade hermes-agent
```

If activation fails after the lockfile update, the new pins remain in `flake.lock`.
Resolve the activation error and retry the switch before upgrading packages.
These commands update formula/cask definitions and packages, not the Homebrew executable;
the latter is pinned separately by the `nix-homebrew` input.

When upgrading Hermes, wait for coding tasks to finish. After the upgrade, restart
its user LaunchAgent and confirm a Slack request works:

```sh
launchctl kickstart -k "gui/$(id -u)/ai.hermes.gateway"
```

The gateway checks required Hermes APIs at startup; a successful upgrade alone does not
prove the updated runtime is compatible.

Homebrew versions are mutable local state. Move a version-sensitive runtime to a Nix language
profile when every supported host must use the same version.

Removing an item from the inventory does not delete an existing Homebrew or user-local
installation. Cleanup requires separate approval. In particular, use
`/run/current-system/sw/bin/apm` for version-sensitive APM operations while legacy installations
remain.
