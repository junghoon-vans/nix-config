# Activation

Run commands from the repository root. Supported hosts are
`junghoonui-MacBookAir` and `junghoonui-MacBookPro`.

## First activation

```sh
make bootstrap HOST=junghoonui-MacBookAir
```

Bootstrap validates the repository path and host, then evaluates the selected host with
command-local Nix feature flags and `--no-write-lock-file` before invoking `sudo` or changing
`/etc/nix/nix.conf`. Invalid inputs or an evaluation failure leave that configuration untouched.

When feature settings need changing, bootstrap saves the existing configuration to a unique
`nix.conf.backup.*` file, preserves its ownership and permissions, and atomically replaces it.
Symlinks and non-regular configuration files are rejected. A failed activation does not restore
the old feature settings; use the printed backup path for manual recovery.

## Later activations

```sh
make switch HOST=junghoonui-MacBookAir
```

Both commands install the locked APM skills after a successful activation. They invoke the
Nix-managed APM binary as the current user with `--frozen`; generated output remains APM-owned.
Run these targets without `sudo` because the scripts perform privilege escalation only where
required.

Activation changes workstation state and requires explicit approval. Evaluation and build checks
do not activate a host.

## Verification

Run the isolated bootstrap checks without modifying the workstation:

```sh
python3 -B -m unittest discover -s scripts/nix -p 'test_*.py'
```

After a toolchain migration and an approved activation, verify command provenance:

```sh
make switch HOST=junghoonui-MacBookAir
type -a omp gno gnokey gnopls gnomcp apm
omp --version
gno version
gnokey version
gnopls version
gnomcp version
/run/current-system/sw/bin/apm --version
```

Nix-managed commands should resolve from `/run/current-system/sw/bin`. Always use that absolute
path for APM when an older Homebrew or `~/.local/bin` installation is also present. Credentials,
OAuth sessions, and API keys remain outside this repository.
