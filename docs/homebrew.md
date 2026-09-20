# Homebrew

nix-darwin owns the declared Homebrew inventory in `modules/darwin.nix`. Activation installs
missing formulae and casks but never updates, upgrades, cleans, or removes packages automatically.
Those operations require explicit review and approval.

## Formulae

| Area | Formulae |
| --- | --- |
| Editors and VCS | `neovim`, `git`, `git-delta`, `gh`, `lazygit` |
| CI and workflow | `act`, `actionlint`, `prek`, `go-task`, `tmux`, `hermes-agent` |
| Build and language support | `cmake`, `pkgconf`, `delve`, `marksman`, `bash-language-server`, `terraform-ls`, `yaml-language-server`, `shellcheck`, `shfmt`, `yamlfmt` |
| Cloud and infrastructure | `awscli`, `kubernetes-cli`, `helm`, `terraform`, `grpcurl` |
| Database clients | `mysql-client`, `libpq` |
| CLI utilities | `mole`, `bat`, `eza`, `ripgrep`, `ast-grep`, `fd`, `htop`, `jq`, `tldr`, `fzf`, `zoxide` |

## Casks

Declared casks include `aside`, `session-manager-plugin`, `orbstack`, `tailscale-app`,
`karabiner-elements`, `jordanbaird-ice`, `hop`, `headlamp`, `paseo`, `zed`,
`font-fira-code-nerd-font`, and `font-d2coding`.

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
