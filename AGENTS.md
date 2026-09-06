# Agent Guide

## Scope

This repository declares Junghoon's Apple Silicon macOS workstation. It is not a generic
NixOS configuration.

- `hosts/junghoonui-MacBookAir/` and `hosts/junghoonui-MacBookPro/` compose the supported hosts.
- `modules/` contains reusable nix-darwin and Home Manager modules.
- `home/` contains static payloads managed by Home Manager.
- `apm.yml` declares external Oh My Pi skills.
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
- LaunchAgent maintenance must default to the least destructive behavior. Changes that delete
  Docker images, containers, caches, or user data need explicit human approval.

## Approval Required

Do not run commands that mutate the workstation or external state without explicit approval:

- `darwin-rebuild switch`, `nix-darwin ... switch`, or an equivalent activation
- `bootstrap-agent-skills`
- `brew update`, `brew upgrade`, package removal, or Homebrew cleanup
- Docker prune/cleanup commands or the disk-maintenance script outside dry-run mode
- Credential, token, permission, or remote repository-setting changes

Read-only inspection and build/evaluation checks are allowed. Clearly distinguish an
inspection, evaluation, build, and activation in reports.

## Validation

Before committing a Nix configuration change:

1. Review the complete diff and run `git diff --check`.
2. Keep Nix files formatted with the repository's chosen formatter when one is available.
3. On a macOS environment with Nix, run:

   ```sh
   nix flake metadata --no-write-lock-file
   for host in junghoonui-MacBookAir junghoonui-MacBookPro; do
     nix eval ".#darwinConfigurations.${host}.config.system.build.toplevel.drvPath"
     nix build ".#darwinConfigurations.${host}.system"
   done
   ```

4. If the current environment cannot build Darwin (for example, a Linux worker), do not claim
   local build success. Report the limitation and verify the GitHub Actions result after push.
5. Report changed files, commands actually run, outcomes, and any approval needed for the next
   step.

## Git Workflow

Use Conventional Commits. Keep changes focused; do not combine host activation, dependency
updates, and unrelated dotfile edits in one change. Do not commit generated runtime state or
secrets.
