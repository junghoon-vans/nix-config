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

## Skill inventory

The [generated skill inventory](skills.md) lists every skill declared in `apm.yml`, including
aliases, package paths, explicit selectors, pinned refs, and upstream source links. It does not
include machine-local skills or claim that declared skills are currently installed.

After editing `apm.yml`, run:

```sh
python3 -m pip install -r scripts/security/requirements.txt
make skills
make skills-check
```

The generator reuses the pinned PyYAML dependency used by skill inspection. It reads only the
manifest: no APM installation, upstream fetch, or workstation activation is needed. PR validation
rejects stale output, and the daily tagged-skill updater includes regenerated documentation in
its update PR.

## Updating skills

Dependencies backed by upstream tags are checked daily by
`.github/workflows/update-dependencies.yml`. The workflow updates `apm.yml`, regenerates
`apm.lock.yaml`, and opens a review pull request. Repositories without usable tags remain pinned
to reviewed commits and require a manual manifest and lockfile update.

The shared [update workflow permissions](nix-toolchain.md#update-workflow-permissions) also
apply to skill updates, including automatic validation without a workflow approval step.

After approval, deploy the locked output with an activation command such as:

```sh
make switch HOST=junghoonui-MacBookAir
```

A pre-existing Homebrew or `~/.local/bin/apm` must not determine lockfile behavior; use the
absolute Nix-managed executable for manual lockfile operations.
