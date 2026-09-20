# Agent Skills and APM

APM owns globally deployed agent skills and generated state. The repository owns only the locked
inputs and installation procedure:

| Concern | Source |
| --- | --- |
| Skill declarations | `apm.yml` |
| Locked revisions and hashes | `apm.lock.yaml` |
| Pinned CLI package | `packages/apm.nix` |
| Installation | `scripts/apm/setup-apm.sh` |

`make bootstrap` and `make switch` copy the locked manifest and lockfile to `~/.apm/`, then run the
Nix-managed APM CLI as the current user with `--frozen`. Home Manager must not manage APM-generated
output.

## Updating skills

1. Change `apm.yml`.
2. Refresh `apm.lock.yaml` with `/run/current-system/sw/bin/apm`.
3. Review and commit both files.
4. After approval, deploy with an activation command such as:

   ```sh
   make switch HOST=junghoonui-MacBookAir
   ```

A pre-existing Homebrew or `~/.local/bin/apm` must not determine lockfile behavior; use the
absolute Nix-managed executable.
