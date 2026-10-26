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
