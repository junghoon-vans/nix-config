# Contributing

## Scope

This repository configures Junghoon's Apple Silicon macOS workstations. Keep host-specific settings in `hosts/`; extract a module only when both hosts use it. Each managed path has one owner:

- nix-darwin: macOS defaults, Homebrew inventory, and LaunchAgents.
- Home Manager: home-directory files and shell configuration.
- APM: generated agent-skill state.
- User-local files: credentials, OAuth state, tokens, and machine-specific overrides.

Do not commit credentials, generated APM output, or machine-local overrides.

## Changes

- Keep `flake.lock` unchanged unless the change intentionally updates dependencies.
- Pin fetched Apple Silicon artifacts with an integrity hash.
- Do not enable Homebrew update or upgrade during activation.
- Treat Home Manager file changes as user-visible replacements; preserve configured backup behavior.
- Keep multi-step scripts in `scripts/<area>/`; Make targets should only invoke them.

## Validation

Review the complete diff and run:

```sh
git diff --check
nix fmt
nix flake metadata --no-write-lock-file
for host in junghoonui-MacBookAir junghoonui-MacBookPro; do
  nix eval ".#darwinConfigurations.${host}.config.system.build.toplevel.drvPath"
  nix build ".#darwinConfigurations.${host}.system"
done
```

Run the relevant command or scenario for behavior changes. Do not claim Darwin build success when the current environment cannot build it.

## Pull requests

Use focused Conventional Commit messages. Describe the changed files, commands actually run, outcomes, and any approval required for activation or destructive maintenance. Keep activation, dependency updates, and unrelated dotfile changes separate.
