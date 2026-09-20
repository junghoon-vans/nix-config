# Agent Skills and APM

APM owns globally deployed agent skills and generated state. The repository owns only the locked
inputs and installation procedure:

| Concern | Source |
| --- | --- |
| Skill declarations | `apm.yml` |
| Locked revisions and hashes | `apm.lock.yaml` |
| Pinned CLI package | `release-pins.json`, `packages/apm.nix` |
| Installation | `scripts/apm/setup-apm.sh` |

`make bootstrap` and `make switch` copy the locked manifest and lockfile to `~/.apm/`, then run the
Nix-managed APM CLI as the current user with `--frozen`. Home Manager must not manage APM-generated
output.

## Updating skills

Dependencies backed by upstream tags are checked weekly by
`.github/workflows/update-dependencies.yml`. The workflow updates `apm.yml`, regenerates
`apm.lock.yaml`, and opens a review pull request. Repositories without usable tags remain pinned
to reviewed commits and require a manual manifest and lockfile update.

After approval, deploy the locked output with an activation command such as:

```sh
make switch HOST=junghoonui-MacBookAir
```

A pre-existing Homebrew or `~/.local/bin/apm` must not determine lockfile behavior; use the
absolute Nix-managed executable for manual lockfile operations.
