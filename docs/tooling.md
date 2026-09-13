# Tooling Inventory

This document is the navigation index for tooling managed by this repository. The declarations
and lockfiles named below are authoritative; this page explains ownership, versioning, and
update procedure.

## Ownership model

| Owner | What it manages | Version source | Mutable user state |
| --- | --- | --- | --- |
| Nix / nix-darwin | System packages, language runtimes, fixed release artifacts (including the APM CLI), macOS defaults | `flake.lock`, Nixpkgs, or an artifact pin and SRI hash in `modules/` or `packages/` | None |
| Home Manager | Static home-directory configuration | Repository revision | None |
| Homebrew | Formulae and casks deliberately outside Nixpkgs | Upstream Homebrew formula/cask revision | Homebrew cellar and application state |
| APM | Agent skill deployment and generated skill output | `apm.yml` and `apm.lock.yaml` | `~/.apm/` |
| User-local configuration | Credentials, OAuth sessions, API keys, machine overrides | User-owned | `~/.zshrc.local`, service-specific state directories |

Never make two owners manage the same path. In particular, Home Manager must not declare
APM-generated output or credential state.

## Activation commands

Run commands from the repository root. `make bootstrap HOST=<host>` enables the
Nix features required by the flake and activates a host. Use it only for the
first activation; later configuration changes use `make switch HOST=<host>`.
Supported values are `junghoonui-MacBookAir` and `junghoonui-MacBookPro`.

Bootstrap validates the repository path and supported host, then evaluates the
selected host with command-local Nix feature flags and `--no-write-lock-file`
before invoking `sudo` or changing `/etc/nix/nix.conf`. Invalid inputs or an
evaluation failure leave that configuration untouched.

When feature settings need changing, bootstrap saves the existing configuration
to a unique `nix.conf.backup.*` file (printing its path), preserves its ownership
and permissions, and atomically replaces it using a temporary file in the same
directory. Symlinks and non-regular configuration files are rejected rather than
replaced. A failed activation does not restore the old feature settings; the
backup remains available for manual recovery.

Run `python3 scripts/nix/test-bootstrap.py` for isolated bootstrap regression
checks. These use temporary configuration files and substitute Nix and sudo;
they do not activate or modify the workstation.

After successful activation, both commands copy the locked APM manifest and
lockfile to `~/.apm/` and install agent skills as the current user, outside
`sudo`. The setup script invokes `/run/current-system/sw/bin/apm` explicitly,
so a pre-existing Homebrew or user-local `apm` cannot shadow the Nix-managed CLI.
Installation uses `--frozen`, so it does not update dependency versions.
Generated output remains APM-owned. Do not manage it through Home Manager or Nix.
Run `make` without `sudo`.

## Nix inputs

All flake inputs are locked in `flake.lock`. Dependabot updates the Nix input graph; review
lockfile changes as dependency updates.

| Input | Purpose |
| --- | --- |
| `nixpkgs` | Nix package set for language runtimes and development tooling |
| `nix-darwin` | macOS system configuration |
| `home-manager` | Home-directory configuration |
| `nix-homebrew` | Declarative Homebrew taps and inventory |
| `protobuf36` | Protobuf source pinned to `v36.1` |
| `oh-my-zsh`, `spaceship-prompt`, `zsh-*` | Shell framework, theme, and plugins |
| `zed-gno` | Zed Gno extension source |
| `homebrew-core`, `homebrew-cask`, `homebrew-tw93` | Homebrew repositories and taps |

## Nix-managed fixed releases

These are Apple Silicon artifacts or source builds whose version/revision, URL, and integrity
hash must change together. The Nix declaration is the canonical pin location.

| Tool | Canonical pin | Source / package definition | Notes |
| --- | --- | --- | --- |
| OMP | `ompRelease` (`18.1.19`, `sha256-3vwdOY1qkPNJmNUSD7W1PPeuCMEN/5G4NMq1o7BGERk=`) | `modules/omp.nix` | Standalone `darwin-arm64` release binary; update version and integrity hash together |
| APM CLI | Release `0.30.0` | `packages/apm.nix` | Pinned Apple Silicon artifact; the system executable is `/run/current-system/sw/bin/apm` |
| Bun | `bunVersion` (`1.4.2`) | `modules/languages/bun.nix` | Standalone `darwin-aarch64` release binary |
| Protobuf | `protobuf36` flake input (`v36.1`) | `flake.nix`, `modules/languages/go.nix` | Source build; the flake input is the only version pin |
| Gno / gnokey | `gnoRelease` (`chain/pearl`) and source revision | `modules/languages/gno.nix` | Release binaries wrapped with the pinned `GNOROOT` source |
| gnopls | `gnoplsRev` | `modules/languages/gno.nix` | Source build with a pinned Go vendor hash |
| gnomcp | `gnomcpVersion` (`0.11.0`) | `modules/mcp/gnomcp.nix` | Local stdio MCP server |

## Nixpkgs language tooling

These versions follow the locked Nixpkgs revision rather than a per-tool release pin.

| Area | Packages | Enabled hosts |
| --- | --- | --- |
| Go | `go_1_25`, `gopls`, `golangci-lint`, `gofumpt`, Protobuf | Air, Pro |
| Gno | `gno`, `gnokey`, `gnopls` | Air, Pro |
| Node / TypeScript | `nodejs_24`, `corepack`, `pnpm`, `typescript`, `typescript-language-server`, `biome` | Air, Pro |
| Python | `python313`, `uv`, `pyright`, `ruff` | Air, Pro |
| Rust | `cargo`, `rustc`, `rustfmt`, `clippy`, `rust-analyzer`, `cargo-nextest` | Air, Pro |
| XML | `lemminx` | Air, Pro |
| Java | `temurin-bin-25`, `jdt-language-server` | Air only |
| Kotlin | `kotlin`, `kotlin-language-server` | Air only |

Host enablement is declared in `hosts/junghoonui-MacBookAir/default.nix` and
`hosts/junghoonui-MacBookPro/default.nix`.

Language profiles under `modules/languages/` are opt-in. Each host enables only
the profiles it needs through `workstation.languages.*.enable`; the locked
Nixpkgs revision is their version authority. `mise` remains for repository-local
`mise.toml` overrides.

## Homebrew-managed tooling

Homebrew activation does not update, upgrade, or clean packages automatically. Version changes
require explicit review and an approved Homebrew operation.

### Formulae

| Area | Formulae |
| --- | --- |
| Editors and VCS | `neovim`, `git`, `git-delta`, `gh`, `lazygit` |
| CI and development workflow | `act`, `actionlint`, `prek`, `go-task`, `tmux`, `hermes-agent` |
| Build and language support | `cmake`, `pkgconf`, `delve`, `marksman`, `bash-language-server`, `terraform-ls`, `yaml-language-server`, `shellcheck`, `shfmt`, `yamlfmt` |
| Cloud and infrastructure | `awscli`, `kubernetes-cli`, `helm`, `terraform`, `grpcurl` |
| Database clients | `mysql-client`, `libpq` |
| CLI utilities | `mole`, `bat`, `eza`, `ripgrep`, `ast-grep`, `fd`, `htop`, `jq`, `tldr`, `fzf`, `zoxide` |

### Casks

`aside`, `session-manager-plugin`, `orbstack`, `tailscale-app`, `karabiner-elements`,
`jordanbaird-ice`, `hop`, `headlamp`, `paseo`, `font-fira-code-nerd-font`, and
`font-d2coding` are declared in `modules/darwin.nix`.

### Maintenance

Activation installs missing declared formulae and casks, but never updates,
upgrades, or cleans Homebrew packages. There are no automatic Homebrew upgrades.
Review available upgrades first:

```sh
brew update
brew outdated
```

Apply upgrades only after review:

```sh
brew upgrade
brew upgrade neovim
```

Removing APM from the Homebrew inventory does not automatically delete an
existing Homebrew installation or a `~/.local/bin/apm` installation. Any later
cleanup or removal requires explicit approval. Until then, use
`/run/current-system/sw/bin/apm` for manual APM lock operations and other
version-sensitive commands rather than bare `apm`.

Homebrew versions are mutable local state. Move a version-sensitive runtime to
a Nix language profile when every supported host must use the same version.

## Agent, MCP, and editor tooling

| Tool or integration | Owner | Configuration | Versioning / runtime boundary |
| --- | --- | --- | --- |
| APM CLI | Nix | `packages/apm.nix` | Pinned `0.30.0` Apple Silicon artifact; invoke `/run/current-system/sw/bin/apm` |
| OMP ACP agent | Nix | `modules/omp.nix`, `home/.config/zed/settings.json` | Fixed OMP release; Zed invokes `/run/current-system/sw/bin/omp acp` |
| OMP skills | APM | `apm.yml`, `apm.lock.yaml`, `scripts/apm/setup-apm.sh` | Locked commits and content hashes; installed automatically by `make bootstrap` and `make switch`; generated output remains APM-owned |
| gnomcp | Nix | `modules/mcp/gnomcp.nix`, `home/.omp/agent/mcp.json` | Fixed release; OMP spawns a local stdio subprocess |
| Hosted MCP servers | OMP config | `home/.omp/agent/mcp.json` | Atlassian, GitHub, Context7, and Notion endpoints; credentials stay user-local |
| Firecrawl MCP | External npm runtime | `home/.omp/agent/mcp.json` | Invoked as `firecrawl-mcp@3.24.0`; npm dependency resolution is outside Nix |
| Aside MCP | Homebrew cask | `home/.omp/agent/mcp.json` | App installation is Homebrew-managed; executable discovery is environment-dependent |
| Aside preferences | Home Manager | `modules/aside.nix`, `scripts/aside/apply-settings.py` | Partial activation-time merge; OAuth, account catalogs, and runtime state stay local |
| Zed Gno support | Home Manager / Nix | `modules/home-manager.nix`, `home/.config/zed/settings.json` | Gno extension is flake-locked; `gnopls` is Nix-managed |
| Paseo OMP provider | Home Manager | `home/.paseo/config.json` | Invokes OMP from the shell environment |

### Aside subscription preferences

`modules/aside.nix` declares ChatGPT subscription (`openai-codex`) model choices:
Luna/high for the default, Luna/medium for standard tasks, Sol/medium for deep
tasks, and Terra/high for visual tasks. Fast mode is off and no image-generation
model is selected. Each machine still requires its own ChatGPT OAuth connection
in Aside; Nix neither copies credentials nor guarantees subscription quota or
credit-free use of every Aside feature.

The same policy asks before tools run by default, keeps the sandbox and
outside-folder prompts enabled, disables context awareness (including typed-text
capture and screen OCR), analytics, routine suggestions, payments, and message
sending, and retains episodic memory for 30 days. Existing explicit tool rules,
other memory settings, MCP configuration, and all other undeclared fields survive.
Task-specific permissions can still override agent defaults. Shorter retention
allows Aside to expire older episodic memories; the merge itself deletes no memory
files.

Home Manager invokes `apply-aside-settings` after its write boundary. This is a
one-way merge at activation, not live or bidirectional sync, and `settings.json`
remains a writable regular file rather than a `home.file` symlink. The first
changed settings file is retained locally as `settings.json.pre-nix` (matching the
repository's backup suffix); later applications never overwrite that snapshot.
Settings, the backup, and an existing `models.json` are restricted to `0600`.
The merger never reads `credentials.json`, `accounts.json`, or `models.json`
contents and never copies them into the Nix store or repository.

The merger discovers an existing numeric profile under `~/.aside/u/` instead of
assuming account `0`. It does not create profiles before Aside initializes them.
If more than one profile exists, choose the intended local account explicitly:

```sh
apply-aside-settings --account 7 --dry-run
apply-aside-settings --account 7
```

These commands become available after an approved host activation. With exactly
one profile, omit `--account`. Quit Aside and disconnect CLI/MCP clients first:
an active browser or daemon defers the merge without killing processes or
overwriting live settings. Activation reports the deferral and continues; the
manual command returns a nonzero status until it can apply. Run it again after
closing Aside. Malformed settings or symlinked/shared files fail rather than being
replaced. Review the retained backup before any manual restore; the next
activation reapplies the declared fields.

## Update procedures

### Nix inputs and Nixpkgs packages

Use a focused dependency update. Inspect `flake.lock`, evaluate and build both supported hosts,
and report the resulting package behavior. Do not update unrelated inputs in the same change.

### Fixed release artifacts

Update one tool per pull request unless two tools have a real compatibility dependency.

1. Update only the canonical version or revision named in the package module.
2. Update the artifact URL, SRI hash, and any Go vendor hash required by that package.
3. Build both host configurations.
4. Run the resulting binary's `--version` or equivalent command.
5. Record source, version, hash update, and verification in the pull request.

Do not use version-only update bots for fixed artifacts: they cannot safely recalculate Nix
artifact hashes or Go vendor hashes.

### Homebrew inventory

Change the formula/cask declaration in `modules/darwin.nix`. Actual Homebrew update, upgrade,
cleanup, or package removal requires explicit approval and is not part of normal activation.

### Weekly disk maintenance

Each host config controls `workstation.maintenance.enable`, which installs the weekly reporting
LaunchAgent. `workstation.maintenance.mole.enable` and
`workstation.maintenance.dockerPrune.enable` independently opt into destructive cleanup after
the configured disk-usage threshold is reached. Both cleanup options default to disabled; enable
them only after approving cleanup on that specific host. Both current hosts explicitly enable the
Mole and Docker prune options.
`WEEKLY_DISK_DRY_RUN` may be unset (defaulting to `0`) or set exactly to `0` or `1`; `1` logs
cleanup commands without executing them. Any other value, including an explicit empty value,
aborts before the log directory is created or cleanup is attempted.

### APM skills

Change `apm.yml`, refresh and commit `apm.lock.yaml` using the Nix-managed CLI
at `/run/current-system/sw/bin/apm`, then activate and deploy:

```sh
make switch HOST=junghoonui-MacBookAir
```

This writes generated state under `~/.apm/`; APM owns that output. Do not manage
it through Home Manager, and use the absolute Nix path for any later manual
lockfile operation.

## Activation verification

After a toolchain migration, activate explicitly and verify command provenance before deleting
legacy user-local installations:

```sh
make switch HOST=junghoonui-MacBookAir
type -a omp gno gnokey gnopls gnomcp apm
omp --version
gno version
gnokey version
gnopls version
gnomcp version
/run/current-system/sw/bin/apm --version
```

The Nix-managed commands should resolve from `/run/current-system/sw/bin`. For APM,
use that absolute path even when `type -a apm` reports an older Homebrew or
`~/.local/bin` installation. User credentials, OAuth sessions, and API keys remain
outside this repository.
