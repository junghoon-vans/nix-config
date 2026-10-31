# Oh My Pi

Nix installs the pinned OMP release from `modules/omp.nix`. Home Manager deploys the shared agent
configuration from `home/.omp/agent/` to `~/.omp/agent/`; Zed invokes
`/run/current-system/sw/bin/omp acp`.

## Shared and machine-local settings

The repository owns shared settings in `home/.omp/agent/config.yml`. Machine paths, credentials,
and other workstation-specific values must not be committed.

The managed shell config automatically adds this optional OMP overlay when the file exists:

```text
~/.omp/agent/config.local.yml
```

OMP reads it through the official `PI_CONFIG_FILES` setting. No file is created by activation, so
each machine opts in by creating only the settings it needs. For example, a checkout-specific
skill directory can differ between laptops:

```yaml
skills:
  customDirectories:
    - /absolute/path/on/this/machine/onbloc-meta/.agents/skills
```

Start a new shell and inspect the effective behavior by opening OMP from a nested repository and
reading a known skill:

```text
skill://pr-contribution-standards
```

The shell appends the local overlay to an existing `PI_CONFIG_FILES` path list and avoids adding it
twice in child shells. OMP loads later overlays with higher precedence. Map keys augment or
override shared settings; lists such as `skills.customDirectories` should be treated as replacing
the shared list.

If `~/.omp/agent/config.local.yml` does not exist, the shell leaves `PI_CONFIG_FILES`
unchanged. Once registered, an invalid or later-removed overlay is an OMP startup error; open a
new shell after fixing or removing the environment entry.

This automatic registration applies to OMP processes launched from the managed interactive shell.
GUI applications do not source `.zshrc`; a GUI launcher must pass `PI_CONFIG_FILES` itself or add
the same overlay with its OMP launch arguments.

## Hermes search and coding delegation

`modules/hermes.nix` exposes `fast`, `deep`, and `omp` through the official
`advanced-delegation` model map. `omp` replaces `coder`; there is no compatibility
alias. Saved prompts or task payloads using `option: coder` must use `option: omp`.
The provider ID remains `omp-acp` and model selection, authentication, retry settings,
and approval boundaries are unchanged.

Use `omp` for web search/검색 with actual retrieval and linked sources, as well as
repository inspection, coding, and verification. Web-only tasks need no repository;
repository tasks still require an absolute path within the configured roots and an
isolated worktree for changes. `fast` and `deep` reason over supplied context only.

The merged provider revision pinned in `flake.lock` includes `skills/search`.
The current upstream tree has a single root provider package; `providerSource`
therefore selects the input root, not the obsolete split-layout subdirectory.
The generated config connects its immutable Nix-store `skills` parent through
`skills.external_dirs`. Activation preserves existing external skill directories
and deduplicates repeated entries. Only the Nix-managed `omp-worker` profile
receives this configuration; other profiles are not automatically managed.

The packaged runtime check reads the Nix-generated YAML in a disposable home,
loads `search` with `skills_list` and `skill_view`, compares its full content with
the pinned source, and verifies the existing bundled `github` and `hermes-agent`
skills remain available alongside the `omp` delegation route. This is discovery
and routing validation, not a live web-search/model invocation. Plugin installation
is not OMP installation: the executable and its model/search authentication remain
external prerequisites. Build checks do not activate the live profile.

## Hermes ACP retry limit

`modules/hermes.nix` generates a Nix-store overlay with `retry.maxRetries: 3` and
`retry.baseDelayMs: 2000`, passed through the plugin's existing `args` as `acp --config <store-path>`.
Only OMP children launched by that Hermes profile receive this overlay; interactive OMP
and Zed keep their existing settings. No separate OMP home or credentials are created.

This permits three session-level retries after the initial attempt. The generic backoff waits
approximately 1500–2000 ms, 3000–4000 ms, then 6000–8000 ms, including downward jitter;
OMP caps this backoff at 8 seconds. Provider timing hints and other error-specific paths can use different delays.
`retry.maxDelayMs` is an individual-wait ceiling, not a fixed retry interval or total deadline.
This does not cap lower-level
Codex transport retries, disable configured model fallbacks, or change Hermes's own retry
policy. Provider/approval defaults and the existing ACP approval mode are unchanged.

The `hermesRuntimeCheck` build uses temporary homes and a loopback-only synthetic Codex
endpoint: the ordinary ACP control sends one request with retries disabled, while the
Hermes launch arguments override that control and send exactly four. The check also verifies
the minimum backoff intervals without imposing scheduling-sensitive upper bounds. No live model
account or workstation activation is needed.

## Hermes gateway service ownership

Home Manager owns the `org.nixos.hermes.gateway-omp-worker` LaunchAgent definition, installation,
and activation. The agent launches the packaged Hermes CLI with
`--profile omp-worker gateway run --external-supervisor` and keeps
`HERMES_HOME=~/.hermes/profiles/omp-worker`; launchd owns process lifetime and restart. There is no
runtime plist under `/etc/hermes/launchd`.

Hermes's built-in service-management commands derive the canonical
`ai.hermes.gateway-omp-worker` label, not this custom job. Do not use `hermes gateway install`
or `uninstall` to manage it: installation can create a second, independently owned service.
`gateway stop` can still terminate the profile's process without unloading the custom job.
`hermes --profile omp-worker gateway restart` recognizes an externally supervised running
gateway, requests a graceful exit, and waits for launchd to bring up its replacement; it does
not own the custom service definition. Use launchctl for authoritative service status and restart.

Inspect the loaded LaunchAgent in the logged-in user's GUI domain:

```sh
launchctl print "gui/$(id -u)/org.nixos.hermes.gateway-omp-worker"
```

To force launchd to restart it:

```sh
launchctl kickstart -k "gui/$(id -u)/org.nixos.hermes.gateway-omp-worker"
```

During a Home Manager transition from the old managed label, activation processes the new or updated
agent before cleaning up agents removed from the previous generation. Home Manager boots out and
removes the old plist only if its installed bytes still match that previous-generation definition;
it preserves a diverged plist. The old and new agents may therefore overlap briefly. Hermes's
gateway host-lock conflict exits with status 75, which remains retryable with
`KeepAlive.SuccessfulExit=false`; this LaunchAgent also uses a 30-second `ThrottleInterval`.
A diverged old plist, or a canonical service not tracked by the previous Home Manager generation,
is not automatically deleted. Review such a competing service and obtain approval for manual
cleanup before activation; do not remove other profiles' services. No activation or live service
migration is performed by a build.

## Skill ownership

APM owns generated global skills. Project-local skills stay with their project. Use a local overlay
only to make an existing checkout's skills visible across nested Git workspaces; do not copy the
generated APM tree into Home Manager.

`skills.customDirectories` scans one directory level (`*/SKILL.md`). Point it at the directory
containing the individual skill directories, not at a skill itself. Exposing a large project skill
directory makes every valid skill below it available and may shadow another provider's skill with
the same name; use a small local bridge directory when only selected skills are required.

## Model routing

`home/.omp/agent/config.yml` owns daily, planning, review, security, worker, and
deep model roles and their effort levels. Paseo's saved profiles and provider
default in `home/.paseo/config.json` must match the corresponding OMP roles.

Before deploying a model change, confirm that the pinned OMP release in
`release-pins.json` supports the exact selector in the configuration and that
`omp models openai-codex --json` lists it for the account. Older clients can
hide models that Codex grants access to. Discovery and a successful Nix build
do not prove inference access; verify the selected model in an actual session
before relying on the routing.

## Updating OMP

Update `ompRelease` in `modules/omp.nix` together with its Apple Silicon artifact URL and SRI hash.
Build both hosts and run `omp --version` from the resulting configuration before activation.
