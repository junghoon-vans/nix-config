# nix-config

My macOS workstation and personal AI agent harness, managed with Nix.

- **Workstation:** Apple Silicon macOS, with apps, shell, editor, and development
  tools declared through nix-darwin and Home Manager.
- **Agent harness:** Oh My Pi (OMP) role-based model routing, shared skills and MCP
  integrations, Zed and Paseo entry points, and a launchd-managed Hermes Slack gateway.

This is my personal setup, not a drop-in configuration for other machines. Review
the host and user settings before activating; credentials and machine-local state
stay separate from the repository. The harness declares agent orchestration, not
an OS sandbox or a guarantee that every service is running.

## Get started

1. Install Xcode Command Line Tools:

   ```sh
   xcode-select --install
   ```

2. Install Nix in multi-user mode with the [official instructions](https://nix.dev/install-nix).
3. Clone this repository:

   ```sh
   git clone https://github.com/junghoon-vans/nix-config.git ~/workspace/nix-config
   cd ~/workspace/nix-config
   ```

4. Bootstrap and activate the selected host. This enables the Nix features needed by the flake:

   ```sh
   make bootstrap HOST=junghoonui-MacBookAir
   ```

   After activation succeeds, the same command automatically installs the locked
   Oh My Pi agent skills as the current user.

## Everyday use

Re-activate an installed host and install the locked agent skills after changing this repository:

```sh
make switch HOST=junghoonui-MacBookAir
```

Supported host values: `junghoonui-MacBookAir` and `junghoonui-MacBookPro`.

Update the pinned Homebrew taps, then explicitly activate the host and inspect upgrades:

```sh
make brew-update
make switch HOST=junghoonui-MacBookAir
make brew-outdated
```

`brew-update` only changes the tap pins in `flake.lock`; it requires no `HOST` and
does not run a switch. Review and commit the lockfile changes before sharing them.
After reviewing `brew-outdated`, run `make brew-upgrade` for all eligible packages or
`make brew-upgrade PACKAGE=neovim` for one package. See the
[Homebrew guide](docs/homebrew.md) for lockfile sharing and the manual equivalent.

List every available command:

```sh
make help
```

## Guides

- [Tooling index](docs/tooling.md): ownership and links to focused operational guides.
- [Managed apps and tools](docs/apps.md): generated package inventory, hosts, and declaration locations.
- [Activation](docs/activation.md): bootstrap, switch, and provenance verification.
- [Nix toolchain](docs/nix-toolchain.md): inputs, fixed releases, and language profiles.
- [Homebrew](docs/homebrew.md): managed inventory and manual upgrade policy.
- [Oh My Pi](docs/omp.md): shared configuration and machine-local overlays.
- [APM](docs/apm.md): locked agent-skill deployment.
- [MCP integrations](docs/mcp.md): local and hosted MCP ownership.
- [Zed](docs/zed.md), [Aside](docs/aside.md), and [maintenance](docs/maintenance.md):
  feature-specific configuration and operational boundaries.
- [Contributing](CONTRIBUTING.md): change scope, validation, and pull-request expectations.
