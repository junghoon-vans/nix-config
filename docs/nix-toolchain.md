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
| `hermes-agent`, `hermes-omp-acp` | Upstream Hermes messaging package and pinned external ACP delegator source |
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
| Hermes | Tagged `hermes-agent` and `hermes-omp-acp` inputs + `flake.lock` hashes | `flake.nix`, `modules/hermes.nix` | Upstream messaging package with ACP SDK and external delegator; Apple Silicon macOS |

Gno tools are built from a pinned commit rather than mutable `chain/mainnet` assets. The dependency
cache uses `proxyVendor` to retain the C sources needed for gnokey Ledger support. Installed
binaries report their source commit.

### Hermes

Hermes and its messaging dependencies come from the upstream `hermes-agent` input.
The tagged `hermes-omp-acp` flake supplies the installed `omp-acp-provider` entry point
and bundled skills. `flake.lock` records its immutable revision and integrity hash.
Its Python overlay is composed with the Hermes interpreter's package scope; only the
provider distribution is added through `extraPythonPackages`. The official ACP SDK
comes from Hermes's sealed `messaging` and `acp` dependency groups, avoiding a duplicate
SDK on the launcher's `PYTHONPATH`. The runtime check launches that installed wrapper
and verifies distribution requirements, entry-point discovery, skills and loopback ACP.
Upstream Hermes supports Apple Silicon macOS as a Tier 2 platform.

The gateway uses the named `omp-worker` profile at `~/.hermes/profiles/omp-worker`, not the
default profile. `omp-worker` is a profile name; the provider plugin ID remains
`omp-acp-provider`. Home Manager owns the profile's `config.nix.yaml` and official
`plugins/advanced-delegation` link. The former `plugins/omp-acp-provider` source link
is no longer managed: discovery uses the installed Python entry point instead.
On activation Home Manager removes its old managed link; no activation is needed to build.
The private `.env`, authentication, sessions, and memories remain user-managed.
Logs also live under this profile. The launchd label follows Hermes's
official profile convention: `ai.hermes.gateway-omp-worker`.

Only this profile sets the Hermes core provider key
`providers.omp-acp.stale_timeout_seconds` to `1800` seconds for long-running OMP ACP calls.
This is a fixed 30-minute stale cap, not an activity-reset timeout. It does not change
the plugin settings, request timeout, other providers, or the default profile.

Before moving an existing default profile, stop its gateway and use the official full
backup/import commands. `profile create --clone-all` deliberately excludes session history
and cron jobs, and profile export excludes credentials, so neither is a full-state migration:

```sh
hermes -p default gateway stop
backup="$HOME/.local/state/hermes-migration/default-$(date +%Y%m%dT%H%M%S).zip"
mkdir -p "$(dirname "$backup")"
(umask 077; hermes backup --output "$backup" --keep 0)
hermes profile create omp-worker --no-alias
hermes -p omp-worker import "$backup" --force
hermes -p default gateway uninstall
hermes -p default config set SLACK_BOT_TOKEN ''
hermes -p default config set SLACK_APP_TOKEN ''
hermes profile use omp-worker
```

Keep the archive private: it includes credentials. The source history and memory remain
available for rollback; the old service and its Slack tokens are retired so only the new
profile owns the bot. Import preserves history data but does not rename default-profile
session identities, so existing channel threads must not be assumed to continue the same
session. Activation creates the profile if needed, installs the managed links, and overlays
Nix-owned settings onto its writable configuration while preserving unrelated user settings.
The gateway launches through the native Hermes CLI, which loads the profile's private `.env`;
the former custom launch wrapper and default-profile cleanup activation are no longer used.

Existing `~/.hermes/omp-worker` legacy task data is not automatically reattached to the
delegator. Additional ACP permission requests are denied, not relayed to Slack; permitted tools
retain their declared capabilities and may still write.

Slack's `allow_bots = "mentions"` accepts bot/app messages only when they explicitly mention
the assistant; existing mention requirements remain unchanged.

To upgrade Hermes, select a reviewed release tag in the `hermes-agent` input URL, run
`nix flake update hermes-agent`, and build both hosts before activation. Updating the lock
without changing the tagged URL does not select a newer release. Wait for active coding tasks
to finish before switching. `make brew-update` and `make brew-upgrade` do not manage Hermes;
Homebrew cleanup stays disabled, so an installed Homebrew Hermes is not automatically removed.

Changing this declaration does not activate the workstation. Activation remains a separate
manual step after review.

## Language profiles

Nixpkgs packages follow `flake.lock`; Bun, Gno tools, and Protobuf use the separate pins
listed above. The table names Nix package attributes, except where it names bundled binaries.

| Area | Packages | Enabled hosts |
| --- | --- | --- |
| Go | `go_1_26`, `gopls`, `golangci-lint`, `gofumpt`, Protobuf | Air, Pro |
| Gno | `gno`, `gnokey`, `gnopls` | Air, Pro |
| Node / TypeScript | `nodejs_24`, `corepack`, `pnpm`, `typescript`, `typescript-language-server`, `biome` | Air, Pro |
| Bun | `bun` (pinned release) | Air, Pro |
| Python | `python313`, `uv`, `pyright`, `ruff` | Air, Pro |
| Rust | `cargo`, `rustc`, `rustfmt`, `clippy`, `rust-analyzer`, `cargo-nextest` | Air, Pro |
| XML | `lemminx` | Air, Pro |
| Java | `temurin-bin-25`, `jdt-language-server` | Air only |
| Kotlin | `kotlin`, `kotlin-language-server` | Air only |

Host enablement lives in `hosts/*/default.nix`. Profiles under `modules/languages/` are opt-in;
`mise` remains available for repository-local `mise.toml` overrides.

### OMP language servers

OMP includes server definitions, not the language-server executables. The enabled language
profiles install the executables on `PATH`; OMP starts them when the corresponding files
and project root markers match. Node and Bun projects use the JavaScript/TypeScript server.

| Language | Installed package | OMP command | Registration |
| --- | --- | --- | --- |
| Go | `gopls` | `gopls serve` | Built-in |
| Gno | `gnopls` | `gnopls serve` | `home/.omp/agent/lsp.yml` |
| JavaScript / TypeScript | `typescript-language-server` | `typescript-language-server --stdio` | Built-in |
| Python | `pyright`, `ruff` | `pyright-langserver --stdio`, `ruff server` | Built-in |
| Rust | `rust-analyzer` | `rust-analyzer` | Built-in |
| Java | `jdt-language-server` | `jdtls` | Built-in |
| Kotlin | `kotlin-language-server` | `kotlin-language-server` | Built-in `kotlin-lsp` definition with command/args overridden in `home/.omp/agent/lsp.yml` |
| XML | `lemminx` | `lemminx` | `home/.omp/agent/lsp.yml` |

`jdt-language-server` is the Nix package attribute; its executable and OMP server ID are
`jdtls`. The Nix package supplies its own pinned JDK launcher; `temurin-bin-25` remains the
Java development runtime. Java and Kotlin profiles are enabled only on Air.

The generated [package inventory](apps.md) uses package metadata names, so entries such as
`go`, `nodejs`, `python3`, and `temurin-bin` differ from the versioned Nix attributes above.
The `gno-toolchain` package supplies both `gno` and `gnokey`.

## Updating

`.github/workflows/update-dependencies.yml` checks release artifacts daily. It opens one pull
request per changed tool, resolves the matching Apple Silicon artifact, and recalculates its Nix
SRI hash. CI checks release-pin structure and SHA-256 hash syntax on Ubuntu. Changes limited
to `release-pins.json`, `.github/scripts/`, `.github/workflows/`, or `scripts/validation/`
skip the full macOS checks and both Darwin builds; CI scripts still receive shell syntax
checks. Configuration changes alongside them still run the full validation. The lightweight
path does not verify the downloaded artifact or runtime behavior. Trusted CI update PRs
request GitHub-managed auto-merge as described below; activation remains manual.

Gno and gnopls release updates also run through the daily workflow, including toolchain
builds and smoke checks before opening the PR. The Zed WASI adapter remains manual.
For manual updates, change each source revision and its source or dependency hashes
together, then build both hosts and exercise the resulting binary.

### CI update auto-merge

After creating or updating a PR, `scripts/updates/open-update-pr.sh` invokes
`enable-update-automerge.py` with the locally pushed commit OID. The same repository-scoped
App token requests **SQUASH** auto-merge through `enablePullRequestAutoMerge`, supplying
`expectedHeadOid` so GitHub rejects a changed head atomically. No direct merge, admin bypass,
CLI merge command, or fallback is used. Missing API support, API errors, or an unconfirmed
response fail the updater job rather than weakening this guard.

Eligibility requires an open, non-draft PR authored by `nix-config-dependabot[bot]`, with
both repositories exactly `junghoon-vans/nix-config`, base `main`, and the expected branch
and head. The script's exact branch-to-path allowlist mirrors the updater calls in
`update-dependencies.yml`: Homebrew, fixed releases, Gno, Hermes, tagged APM skills,
npm MCPs, and Paseo plugins. Every changed file must be an existing modified allowlisted
path. Empty, incomplete, renamed, added, deleted, and out-of-scope file sets are refused.
Human-authored, fork, and unknown-branch PRs remain manual.

Ordinary Dependabot updates use `dependabot-automerge.yml` and the same guarded helper,
with a separate `--source dependabot` trust domain. Only `dependabot[bot]` with GitHub user
ID `49699333` is accepted. Grouped `dependabot/nix/flake-inputs-<hash>` branches may modify
only `flake.nix` and `flake.lock`; grouped `dependabot/github_actions/github-actions-<hash>`
branches may modify only the four explicitly allowlisted repository workflow files.
The hash must be ten lowercase hexadecimal characters. The same repository, base, state,
head, complete file list, and modified-only guards apply; cross-ecosystem paths are refused.

The privileged `pull_request_target` workflow handles opened, reopened, synchronized, and
ready-for-review PRs. It checks out only the trusted base commit (`github.sha`), never the
PR head, and passes PR metadata through quoted environment variables. It never executes
PR code or consumes PR artifacts. Its job-scoped `GITHUB_TOKEN` has only Contents and
Pull requests write permissions; no CI App private key is used. Required PR validation
still runs separately on the ordinary PR event. This workflow becomes active only after
landing on `main`; existing PRs need a subsequent qualifying event.

Before rollout, the owner must separately approve enabling **Allow auto-merge** in repository
settings. Preserve the required `validate` protection on `main`; do not grant the App a bypass.
The helper does not change settings, protections, or required reviews. Until auto-merge is
enabled, GitHub rejects the request and the updater job fails after leaving its PR available
for manual review. An existing SQUASH request is idempotent; a different merge method is
refused rather than replaced. Updates to existing bot PRs are handled on the next updater run;
this does not retroactively enable all open PRs.

GitHub decides when its required checks and reviews permit merging, including when the PR
is already eligible at enable time. API rejection never falls back to an immediate merge.
The atomic guard covers the head OID, not simultaneous base/repository-setting changes;
repository protections remain essential. A failed read-back requires manual inspection,
not an automatic retry or direct merge. Disabling a PR's auto-merge alone is not a persistent
opt-out: a later updater run or qualifying Dependabot event can enable it again. Pause the
corresponding workflow before intervention.
Workstation activation and actual Homebrew package upgrades still require manual approval.

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
