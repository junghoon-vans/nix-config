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
| `protobuf36` | Protobuf source pinned to `v36.1` |
| `oh-my-zsh`, `spaceship-prompt`, `zsh-*` | Shell framework, theme, and plugins |
| `zed-gno` | Zed Gno extension source |
| `homebrew-core`, `homebrew-cask` | Homebrew repositories and taps |

## Fixed releases

These artifacts or source builds require their version, source, and integrity hashes to change
together.

| Tool | Canonical pin | Definition | Notes |
| --- | --- | --- | --- |
| OMP | `ompRelease` (`18.2.1`, `sha256-rGc4aKFZi0vtqY3GziFI8kr6vEKBbHArLaxfefDYYd4=`) | `modules/omp.nix` | Apple Silicon release binary |
| APM CLI | Release `0.31.0` | `packages/apm.nix` | System executable is `/run/current-system/sw/bin/apm` |
| Bun | `bunVersion` (`1.4.2`) | `modules/languages/bun.nix` | `darwin-aarch64` release binary |
| Protobuf | `protobuf36` flake input (`v36.1`) | `flake.nix`, `modules/languages/go.nix` | Source build |
| Gno / gnokey | `gnoRev` and Go dependency hash | `modules/languages/gno.nix` | Both binaries use the same source revision |
| gnopls | `gnoplsRev` | `modules/languages/gno.nix` | Source build with pinned Go dependencies |
| Zed Gno WASI adapter | Wasmtime `v30.0.2` reactor adapter | `modules/home-manager.nix` | Architecture-independent WebAssembly |
| gnomcp | `gnomcpVersion` (`0.11.0`) | `modules/mcp/gnomcp.nix` | Local stdio MCP server |

Gno tools are built from a pinned commit rather than mutable `chain/mainnet` assets. The dependency
cache uses `proxyVendor` to retain the C sources needed for gnokey Ledger support. Installed
binaries report their source commit.

## Language profiles

These versions follow the locked Nixpkgs revision.

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

Host enablement lives in `hosts/*/default.nix`. Profiles under `modules/languages/` are opt-in;
`mise` remains available for repository-local `mise.toml` overrides.

## Updating

Keep each update focused. For fixed releases:

1. Change the canonical version or revision.
2. Update the source URL, SRI hash, and any required dependency hash.
3. Evaluate and build both supported hosts.
4. Run the resulting binary's version command.
5. Record the source, version, hashes, and verification in the pull request.

Do not use version-only automation for fixed artifacts whose hashes must be recalculated.
