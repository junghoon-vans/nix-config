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
- `hosts/junghoonui-MacBookAir`: host-specific identity and module composition.
- `modules/darwin.nix`: Homebrew inventory and macOS defaults.
- `modules/home-manager.nix`: managed files in `$HOME` and the pinned Zsh framework.
- `modules/maintenance.nix`: weekly disk-maintenance LaunchAgent.
- `home/`: static dotfile payload formerly materialized by chezmoi.
- `apm.yml`: APM-owned Oh My Pi skills.

## Bootstrap

The Nix configuration installs the APM CLI through the declared Homebrew formula.
After the switch, bootstrap the pinned Oh My Pi release and deploy its skills:

```sh
sudo nix run nix-darwin/master#darwin-rebuild -- switch --flake .#junghoonui-MacBookAir
bootstrap-omp .
```

`bootstrap-omp` installs `@oh-my-pi/pi-coding-agent@18.1.11` through Bun, verifies
`omp`, and deploys the skill-only APM manifest. Home Manager never owns APM output paths.

## Languages

`modules/languages/` provides opt-in Nix profiles for global runtimes and their
language-specific tooling. Each host selects only the profiles it needs through
`workstation.languages.*.enable`. Nixpkgs revisions pinned by `flake.lock` are
the global version authority; mise is retained only for repository-local
`mise.toml` overrides.

## Safety

Homebrew activation does not remove packages omitted from the declaration (`cleanup = "none"`). Move to a destructive cleanup mode only after auditing the current machine's package inventory.
