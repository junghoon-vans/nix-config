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
skill://worktree-workflow
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

## Skill ownership

APM owns generated global skills. Project-local skills stay with their project. Use a local overlay
only to make an existing checkout's skills visible across nested Git workspaces; do not copy the
generated APM tree into Home Manager.

`skills.customDirectories` scans one directory level (`*/SKILL.md`). Point it at the directory
containing the individual skill directories, not at a skill itself. Exposing a large project skill
directory makes every valid skill below it available and may shadow another provider's skill with
the same name; use a small local bridge directory when only selected skills are required.

## Updating OMP

Update `ompRelease` in `modules/omp.nix` together with its Apple Silicon artifact URL and SRI hash.
Build both hosts and run `omp --version` from the resulting configuration before activation.
