# Aside

`modules/aside.nix` declares shared model and privacy preferences while keeping OAuth, accounts,
credits, and runtime state local to each machine.

The policy selects ChatGPT subscription models, disables fast mode and image generation, asks
before tools run, keeps sandbox and outside-folder prompts enabled, and disables context awareness,
analytics, routine suggestions, payments, and message sending. Episodic memory retention is 30
days. Existing explicit tool rules and undeclared settings survive the merge.

Home Manager invokes `apply-aside-settings` after its write boundary. This is a one-way
activation-time merge, not synchronization. `settings.json` remains writable, and the first changed
file is retained as `settings.json.pre-nix`; later runs do not overwrite that backup. Settings and
backup files are restricted to `0600`. Credentials, accounts, and model catalog contents are never
copied into the repository or Nix store.

The merger discovers an existing numeric profile under `~/.aside/u/`. It does not create a profile
before Aside initializes one. With multiple profiles, select the intended account explicitly:

```sh
apply-aside-settings --account 7 --dry-run
apply-aside-settings --account 7
```

With exactly one profile, omit `--account`. Quit Aside and disconnect CLI/MCP clients first. Active
processes defer the merge without being killed; rerun the command after closing them. Malformed,
symlinked, or shared settings files fail rather than being replaced. Review the retained backup
before a manual restore because the next activation reapplies declared fields.
