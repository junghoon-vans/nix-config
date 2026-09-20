# Tooling and Operations

This index maps each workstation feature to its owner, configuration, and focused guide. The
declarations and lockfiles referenced by those guides are authoritative.

## Ownership

| Owner | What it manages | Mutable user state |
| --- | --- | --- |
| Nix / nix-darwin | System packages, fixed releases, macOS defaults, LaunchAgents | None |
| Home Manager | Static home-directory and shell configuration | None |
| Homebrew | Deliberately mutable formulae and applications | Cellar and application state |
| APM | Locked agent-skill deployment and generated output | `~/.apm/` |
| User | Credentials, authentication, and machine-specific overrides | `~/.zshrc.local`, service state, OMP local overlay |

Each managed path has one owner. Home Manager must not declare APM-generated output, credentials,
authentication state, or machine-local overrides.

## Guides

| Feature | Guide | Canonical configuration |
| --- | --- | --- |
| Bootstrap, activation, and provenance checks | [Activation](activation.md) | `Makefile`, `scripts/nix/` |
| Nix inputs, fixed releases, and language profiles | [Nix toolchain](nix-toolchain.md) | `flake.lock`, `modules/`, `packages/` |
| Formulae, casks, and manual upgrades | [Homebrew](homebrew.md) | `modules/darwin.nix` |
| OMP shared settings and machine-local overlays | [Oh My Pi](omp.md) | `modules/omp.nix`, `home/.omp/agent/` |
| Agent skills and locked deployment | [APM](apm.md) | `apm.yml`, `apm.lock.yaml` |
| Local and hosted model-context servers | [MCP integrations](mcp.md) | `modules/mcp/`, `home/.omp/agent/mcp.json` |
| Gno language support | [Zed](zed.md) | `modules/home-manager.nix`, `home/.config/zed/` |
| Browser-agent preferences | [Aside](aside.md) | `modules/aside.nix`, `scripts/aside/` |
| Disk reports and cleanup boundaries | [Maintenance](maintenance.md) | `modules/maintenance.nix`, `scripts/maintenance/` |

## Common commands

```sh
make check
make bootstrap HOST=junghoonui-MacBookAir
make switch HOST=junghoonui-MacBookAir
make help
```

`bootstrap` and `switch` mutate workstation state and require explicit approval. `make check`,
Nix evaluation, and Nix builds are validation only.
