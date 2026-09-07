# nix-config

Declarative configuration for Junghoon's macOS workstation.

## Ownership

| Concern | Owner |
| --- | --- |
| macOS defaults, Homebrew formulae/casks, LaunchAgents | nix-darwin |
| Home-directory configuration and shell framework | Home Manager |
| Global language runtime and tooling versions | Nixpkgs pinned by `flake.lock` |
| Oh My Pi skills | APM |
| GUI application installation | Homebrew through nix-darwin |
| Ecosystem installers not packaged by Nix | Explicit compatibility commands during migration |

A managed path has exactly one owner. APM-generated skill output is never declared as a Home Manager file.

## Layout

- `flake.nix`: pinned inputs and the host entrypoint.
- `hosts/junghoonui-MacBookAir` and `hosts/junghoonui-MacBookPro`: host-specific identity and module composition.
- `modules/darwin.nix`: Homebrew inventory and macOS defaults.
- `modules/home-manager.nix`: managed files in `$HOME` and the pinned Zsh framework.
- `modules/maintenance.nix`: weekly disk-maintenance LaunchAgent.
- `home/`: static Home Manager file payload.
- `apm.yml`: APM-owned Oh My Pi skills.

## Bootstrap

This configuration manages macOS and user settings after Nix is installed. It deliberately sets `nix.enable = false`, so Nix installation and daemon management remain external to this repository.

### Prerequisites

On a new Apple Silicon Mac:

1. Install Xcode Command Line Tools:

   ```sh
   xcode-select --install
   ```

2. Install Nix in multi-user mode using the [official Nix installation instructions](https://nix.dev/install-nix).
3. Clone this repository:

   ```sh
   git clone https://github.com/junghoon-vans/nix-config.git ~/workspace/nix-workstation
   cd ~/workspace/nix-workstation
   ```

### First activation

Use flakes explicitly so the command also works when they are not enabled globally:

```sh
sudo nix --extra-experimental-features "nix-command flakes" run --inputs-from . nix-darwin#darwin-rebuild -- switch --flake .#junghoonui-MacBookPro
```

`--inputs-from .` resolves `nix-darwin` from this repository's locked flake input rather than the moving `nix-darwin/master` ref.

The switch installs declared Homebrew packages, system language runtimes, Home Manager files,
and the pinned OMP and Gno toolchains from the Nix store. To deploy the separately managed APM
skill dependencies:

```sh
bootstrap-agent-skills .
```

`bootstrap-agent-skills` copies this repository’s APM manifest to `~/.apm/apm.yml` and deploys
the skill-only dependencies. Home Manager never owns APM output paths.

## Homebrew maintenance

`switch` installs declared formulae and casks when missing, but does not update Homebrew or upgrade installed packages. This keeps activation limited to the declared package inventory.

Review available Homebrew upgrades before applying them:

```sh
brew update
brew outdated
```

Upgrade all Homebrew packages only after review, or name one formula explicitly:

```sh
brew upgrade
brew upgrade neovim
```

Homebrew versions are local mutable state. Move a version-sensitive runtime from `modules/darwin.nix` to a Nix language profile when every machine must use the same version.

`cleanup = "none"` means removing a formula from `homebrew.brews` never uninstalls
an already-installed formula. When migrating a language runtime or tool to
`modules/languages/`, explicitly uninstall its Homebrew formula after reviewing
the target machine; do not use a global Homebrew cleanup. Confirm the Nix
binary wins with `type -a <tool>`.

## Languages

`modules/languages/` provides opt-in Nix profiles for global runtimes and their
language-specific tooling. Each host selects only the profiles it needs through
`workstation.languages.*.enable`. Nixpkgs revisions pinned by `flake.lock` are
the global version authority; mise is retained only for repository-local
`mise.toml` overrides.

## Safety

Homebrew activation does not remove packages omitted from the declaration (`cleanup = "none"`). Move to a destructive cleanup mode only after auditing the current machine's package inventory.
