# Agent Skills and APM

Nix owns the APM executable/environment and machine-wide common/host deployment policy. APM owns
the skill payloads it deploys, whether authored here or fetched externally. This repository owns
the common machine inputs and installation procedure:

| Concern | Source |
| --- | --- |
| Skill declarations | `apm.yml` |
| Locked revisions and hashes | `apm.lock.yaml` |
| Pinned CLI package | `release-pins.json`, `packages/apm.nix` |
| Installation | `scripts/apm/setup-apm.sh` |

`make bootstrap` and `make switch` invoke `scripts/apm/setup-apm.sh` after activation. The script
uses the absolute Nix-managed APM executable pinned in `release-pins.json`, not a shell-resolved CLI.
It first stages `apm.yml`, `apm.lock.yaml`, and `skills/` together and runs
`apm install --global --target agent-skills --only apm --trust-bin --frozen --dry-run` with an
isolated staging HOME. Missing locks, manifest drift and changed local dependency content fail
before the machine's inputs, receipts or skills are touched.

After validation, the script copies those inputs to `~/.apm/` and executes the same frozen install
without `--dry-run`. APM resolves relative local paths from `~/.apm/apm.yml`; copying the complete
`skills/` tree preserves those paths and the tracked content hash. Both external and authored
skills are materialized by APM into `~/.agents/skills/`. The committed lock remains byte-for-byte
unchanged; a pre-existing machine lock does not override its dependency resolutions.

The lock is a portable resolution/deployment description, not machine ownership evidence.
The pinned APM release keeps user-scope ownership receipts under `~/.apm/deployment-receipts/`, bound to the
installation identity in `~/.apm-local/`. Setup retains these files and the existing narrow macOS
device-number reconciliation; it never imports another machine's receipts or uses `--force`.
APM preserves locally edited and unrelated skills on reinstall. Preflight is not a transaction:
network or deployment failures after validation can leave partially installed output; inspect
the APM error and retry the same locked inputs. Never delete receipts to force a retry.

## Public ownership interface

| Layer | Owns | Deployment boundary |
| --- | --- | --- |
| Nix machine common | Pinned APM executable, this manifest/lock, shared authored inputs | The only writer of the common `~/.apm/apm.yml` and lock |
| Nix host | Host-only packages and deployment policy | Must not silently widen host-only skills to all machines |
| Project root | Its own `apm.yml`, `apm.lock.yaml`, local skills and generated output | Run APM from that root **without** `--global`; output stays project-scoped |
| APM | Generated skills, dependency materialization and ownership receipts | Home Manager must not also declare APM-generated output in `home.file` |

Personal or organization project roots must not invoke this machine setup or copy their manifests
over `~/.apm/apm.yml`. Use the Nix-provided executable from each project, with that project's own
tracked lock and `apm install --frozen --target agent-skills --only apm`. Do not compose projects
by repeatedly replacing a shared global manifest. Runtime-specific discovery/exposure is a separate
consumer concern and must not create a second owner of deployed skill payloads.

### Host-only exception: officecli

`hosts/junghoonui-MacBookAir/presentations.nix` still owns the officecli skill through Home Manager.
Its payload is fetched from the versioned OfficeCLI release with a Nix integrity hash; the common
APM manifest intentionally excludes it. This is an explicit exception, not an APM-owned output.
Moving it to the shared manifest would deploy it on MacBookPro too. Removing the Nix declaration
before a locked host-selection mechanism is proven would lose the Air-only skill. A safe cutover
must prove equivalent payload pinning, a single global ownership ledger, and host selection before
removing this exception; project-scoped installs are not a substitute for machine host composition.
The pinned APM release's target filters select agent runtimes, not machine identities; a host-specific locked
manifest/composition contract is still needed. No host selection is inferred from the current shell.

## Isolated validation

```sh
apm_store="$(nix build --no-link --print-out-paths .#apm)"
nix develop --no-write-lock-file --command bash scripts/apm/check.sh "$apm_store/bin/apm"
```

The check creates a temporary HOME inside the checkout and removes it on exit. It exercises actual
APM materialization, committed-lock replay over an old machine lock, repeat installs, authored
skills, user edits, receipt/remount handling, invalid-input non-mutation, and common/host exclusion.
It does not activate Nix, install into the real HOME, or prove OfficeCLI host composition.

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
