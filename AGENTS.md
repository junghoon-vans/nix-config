# Agent Guide

## Scope

This repository declares Junghoon's Apple Silicon macOS workstation. It is not a generic
NixOS configuration.

- `hosts/junghoonui-MacBookAir/` and `hosts/junghoonui-MacBookPro/` compose the supported hosts.
- `modules/` contains reusable nix-darwin and Home Manager modules.
- `home/` contains static payloads managed by Home Manager.
- `apm.yml` declares external Oh My Pi skills and MCP servers.
- `flake.lock` is the authoritative dependency pin set.

Keep host-specific settings in the host module. Extract a module only when the setting is
actually reusable.

## Ownership Boundaries

Each managed path has exactly one owner:

| Concern | Owner |
| --- | --- |
| macOS defaults, Homebrew packages, LaunchAgents | nix-darwin |
| Home-directory files and shell configuration | Home Manager |
| APM-managed agent skills | APM |
| Credentials, authentication state, machine-local overrides | User-local files, never this repository |

Do not declare APM-generated output in `home.file`. Do not add tokens, private keys,
credential files, `gh` hosts files, or local overrides to the repository. Use a documented
local override such as `~/.zshrc.local` when machine-specific configuration is required.

## Change Rules

- Preserve the Apple Silicon target unless explicitly adding another host; downloaded
  artifacts must match the target architecture and have an integrity hash.
- Keep `flake.lock` unchanged unless the task explicitly updates dependencies. Explain
  every lockfile update in the commit or PR summary.
- Do not re-enable automatic Homebrew update or upgrade during `darwin-rebuild` activation.
  Package upgrades require explicit review.
- Treat `home.file` changes as potentially user-visible replacements. Preserve the configured
  backup behavior and document migrations when a path is renamed.
- Keep fetched release artifacts version-pinned and integrity-hashed.
- Use `release-pins.json` as the source of truth for release artifact versions and hashes;
  for other dependencies, use their declared owner (for example, `flake.lock`, `apm.yml`,
  or `apm.lock.yaml`). Reference that owner in documentation instead of copying version
  literals. `docs/*.md` must pass the version-drift guard; `docs/skills.md` is the existing
  generated exception, checked against `apm.yml` by `make skills-check`. Do not add manual
  exceptions or weaken checks to accommodate prose.
- LaunchAgent maintenance must default to the least destructive behavior. Changes that delete
  Docker images, containers, caches, or user data need explicit human approval.
- Extract multi-step shell scripts into focused executable files under `scripts/<area>/`; Nix
  modules should only load or invoke them. Keep trivial one- or two-command derivation phases
  inline.

## Approval Required

Do not run commands that mutate the workstation or external state without explicit approval:

- `darwin-rebuild switch`, `nix-darwin ... switch`, or an equivalent activation
- `setup-apm`
- `brew update`, `brew upgrade`, package removal, or Homebrew cleanup
- Docker prune/cleanup commands or the disk-maintenance script outside dry-run mode
- Credential, token, permission, or remote repository-setting changes

Read-only inspection and build/evaluation checks are allowed. Clearly distinguish an
inspection, evaluation, build, and activation in reports.

## Validation

For every change, including documentation and agent instructions, after the final edit and
before committing or pushing:

1. Review the complete diff for scope, credentials, private identifiers and local-environment
   details; run `git diff --check`.
2. Run the narrow documentation guard, then the full repository check from the repository root:

   ```sh
   python3 -B scripts/validation/check-doc-version-drift.py
   make check
   ```

   For release-pin changes also run `python3 -B scripts/validation/check-release-pins.py`;
   for generated skill inventory changes run `make skills-check`. A narrow check is not a
   substitute for `make check`. Any subsequent edit invalidates the prior validation:
   rerun the applicable checks on the final tree before commit/push.
3. For Nix configuration or runtime changes, keep Nix files formatted with the repository's
   formatter and run the relevant CI checks from `.github/workflows/validate.yml`.
   On macOS with Nix, evaluate and build both supported hosts:

   ```sh
   nix flake metadata --no-write-lock-file
   for host in junghoonui-MacBookAir junghoonui-MacBookPro; do
     nix eval ".#darwinConfigurations.${host}.config.system.build.toplevel.drvPath"
     nix build --no-link --no-write-lock-file ".#darwinConfigurations.${host}.system"
   done
   ```

   For Hermes/provider/delegation runtime changes, also build
   `nix build --no-link --no-write-lock-file ".#darwinConfigurations.${host}.config.system.build.hermesRuntimeCheck"`
   for both hosts. For APM deployment changes, run the isolated-HOME check used by CI:

   ```sh
   apm_store="$(nix build --no-link --print-out-paths .#apm)"
   nix develop --no-write-lock-file --command bash scripts/apm/check.sh "$apm_store/bin/apm"
   ```

   Documentation/instruction-only changes still require step 2, but do not require additional
   Darwin builds, runtime checks or live deployment merely because documentation changed.
4. Report commands actually run, observed outcomes and environment limitations. Never infer
   success from memory, an earlier tree, a narrow check or skipped jobs. If Darwin cannot be
   built locally, report that limitation rather than claiming local build success.
5. After push, verify the remote PR head matches the pushed commit and inspect its current CI
   once (for example, `gh pr view --json headRefOid,statusCheckRollup`). Distinguish local
   success from CI pending, failed or skipped; claim all checks passed only with observed
   successful required checks for that exact head. Include the commit and CI URL in the report.

## Git Workflow

Use Conventional Commits. Keep changes focused; do not combine host activation, dependency
updates, and unrelated dotfile edits in one change. Do not commit generated runtime state or
secrets.
