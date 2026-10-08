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

`.github/workflows/update-dependencies.yml` checks release artifacts daily. It opens one pull
request per changed tool, resolves the matching Apple Silicon artifact, and recalculates its Nix
SRI hash. CI checks release-pin structure and SHA-256 hash syntax on Ubuntu. Changes limited
to `release-pins.json`, `.github/scripts/`, `.github/workflows/`, or `scripts/validation/`
skip the full macOS checks and both Darwin builds; CI scripts still receive shell syntax
checks. Configuration changes alongside them still run the full validation. The lightweight
path does not verify the downloaded artifact or runtime behavior; review the release before
merging. Activation remains manual.

Gno, gnopls, and the Zed WASI adapter remain manual because their revisions or runtime
compatibility require review. Change each source revision and its required source or dependency
hashes together, then build both hosts and exercise the resulting binary.

### Update workflow authentication

Release and tagged-skill updates use a dedicated GitHub App installation token for both
Git pushes and PR creation. The token is scoped to this repository with **Contents: Read
and write** and **Pull requests: Read and write** permissions and is revoked after each
job. The default `GITHUB_TOKEN` remains read-only and is used for upstream release queries.
No Actions write permission or personal access token is needed.

Before merging the authentication change, the repository owner must:

1. [Register a GitHub App](https://github.com/settings/apps/new) with a unique name and
   this repository's URL as its homepage. Disable **Active** under Webhook; no webhook
   delivery or OAuth callback is needed.
2. Grant repository permissions **Contents: Read and write** and **Pull requests: Read
   and write**. Leave other optional permissions unset. Limit installation to the owning
   account (**Only on this account**).
3. Select **Install App** and install it on **Only select repositories → nix-config**.
4. In the App's General settings, copy its **Client ID** and generate a private key.
5. In this repository's **Settings → Secrets and variables → Actions**, add:
   - Repository variable `DEPENDENCY_UPDATES_APP_CLIENT_ID`: the App's Client ID.
   - Repository secret `DEPENDENCY_UPDATES_APP_PRIVATE_KEY`: the complete generated PEM
     file, including its header, footer, and line breaks.

Keep the private key out of Git, PR descriptions, chat, and Home Manager declarations.
Missing configuration or insufficient installation permissions will fail token creation
before any update branch is pushed; there is no fallback to `GITHUB_TOKEN`.

The App's PR creation and branch updates trigger ordinary `pull_request` validation;
`validate.yml` no longer accepts workflow dispatches. This removes the duplicate validation
run and the approval-required PR run caused by `github-actions[bot]`. GitHub introduced
that approval requirement for default-token PRs in
[June 2026](https://github.blog/changelog/2026-06-11-bot-created-pull-requests-can-run-workflows-if-approved/).
External-contributor approval policies and lightweight release-pin-only validation remain
unchanged. Require successful validation before merging.

After merging and configuring the App, use **Actions → update dependencies → Run workflow**
or wait for the daily schedule. If an update is available, verify that the created or updated
PR starts `validate` without **Approve workflows to run**. Already-open PRs created by
`github-actions[bot]` may retain their old approval-required runs; verify a new App-authored
PR to confirm the cutover.

The old **Allow GitHub Actions to create and approve pull requests** repository setting
is no longer needed by these jobs. Disabling it is an optional owner-approved permission
change, not part of activation. To revoke App access, uninstall the App and remove its
repository variable and secret; subsequent update jobs will fail at token creation.
Workstation activation remains manual.
