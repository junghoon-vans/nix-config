# Nix Toolchain

`flake.lock` is the authority for flake inputs and Nixpkgs-managed package versions. Dependabot
updates the input graph; review every lockfile change as a dependency update.

## Inputs

| Input | Purpose |
| --- | --- |
| `nixpkgs` | Language runtimes and development tooling |
| `nix-darwin` | macOS system configuration |
| `home-manager` | Home-directory configuration |
| `nix-homebrew` | Declarative Homebrew taps and inventory |
| `protobuf36` | Flake-pinned Protobuf source |
| `oh-my-zsh`, `spaceship-prompt`, `zsh-*` | Shell framework, theme, and plugins |
| `zed-gno` | Zed Gno extension source |
| `homebrew-core`, `homebrew-cask` | Homebrew repositories and taps |

## Fixed releases

Release artifacts keep their version and integrity hash in `release-pins.json`; source builds
keep compatibility-sensitive revisions and dependency hashes in their Nix module.

| Tool | Canonical pin | Definition | Notes |
| --- | --- | --- | --- |
| OMP | `release-pins.json` | `modules/omp.nix` | Apple Silicon release binary |
| APM CLI | `release-pins.json` | `packages/apm.nix` | System executable is `/run/current-system/sw/bin/apm` |
| Paseo | `release-pins.json` | `packages/paseo.nix` | Apple Silicon desktop app and bundled daemon |
| Bun | `release-pins.json` | `modules/languages/bun.nix` | Apple Silicon release binary |
| Protobuf | `protobuf36` flake input | `flake.nix`, `modules/languages/go.nix` | Source build |
| Gno / gnokey | `gnoRev` and Go dependency hash | `modules/languages/gno.nix` | Both binaries use the same source revision |
| gnopls | `gnoplsRev` | `modules/languages/gno.nix` | Source build with pinned Go dependencies |
| Zed Gno WASI adapter | Release URL and hash | `modules/home-manager.nix` | Architecture-independent WebAssembly |
| gnomcp | `release-pins.json` | `modules/mcp/gnomcp.nix` | Local stdio MCP server |

Gno tools are built from a pinned commit rather than mutable `chain/mainnet` assets. The dependency
cache uses `proxyVendor` to retain the C sources needed for gnokey Ledger support. Installed
binaries report their source commit.

## Language profiles

These versions follow the locked Nixpkgs revision.

| Area | Packages | Enabled hosts |
| --- | --- | --- |
| Go | `go_1_26`, `gopls`, `golangci-lint`, `gofumpt`, Protobuf | Air, Pro |
| Gno | `gno`, `gnokey`, `gnopls` | Air, Pro |
| Node / TypeScript | `nodejs_24`, `corepack`, `pnpm`, `typescript`, `typescript-language-server`, `biome` | Air, Pro |
| Python | `python313`, `uv`, `pyright`, `ruff` | Air, Pro |
| Rust | `cargo`, `rustc`, `rustfmt`, `clippy`, `rust-analyzer`, `cargo-nextest` | Air, Pro |
| XML | `lemminx` | Air, Pro |
| Java | `temurin-bin-25`, `jdt-language-server` | Air only |
| Kotlin | `kotlin`, `kotlin-language-server` | Air only |

Host enablement lives in `hosts/*/default.nix`. Profiles under `modules/languages/` are opt-in;
`mise` remains available for repository-local `mise.toml` overrides.

## Updating

`.github/workflows/update-dependencies.yml` checks release artifacts weekly. It opens one pull
request per changed tool, resolves the matching Apple Silicon artifact, and recalculates its Nix
SRI hash. Pull-request validation evaluates and builds both supported hosts; activation remains
manual.

Gno, gnopls, and the Zed WASI adapter remain manual because their revisions or runtime
compatibility require review. Change each source revision and its required source or dependency
hashes together, then build both hosts and exercise the resulting binary.
