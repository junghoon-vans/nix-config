# nix-config

Declarative configuration for Junghoon's Apple Silicon macOS workstations.

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

5. Deploy the locked Oh My Pi agent skills after activation:

   ```sh
   make setup-apm
   ```

## Everyday use

Re-activate an installed host after changing this repository:

```sh
make switch HOST=junghoonui-MacBookAir
```

Supported host values: `junghoonui-MacBookAir` and `junghoonui-MacBookPro`.

List every available command:

```sh
make help
```

## Guides

- [Tooling and operations](docs/tooling.md): ownership, managed tools, updates, Homebrew maintenance, and safety boundaries.
- [Contributing](CONTRIBUTING.md): change scope, validation, and pull-request expectations.
