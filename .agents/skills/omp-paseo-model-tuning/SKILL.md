---
name: omp-paseo-model-tuning
description: Research and calibrate OMP model roles, reasoning effort, and matching Paseo profiles in this nix-config repository. Use when the user asks to compare new models or benchmarks, investigate LUNA max versus high or token efficiency, reassess agent model routing, check post-update availability, or synchronize OMP/Paseo model names and defaults. Also trigger for Korean requests such as 모델 조사, 모델 보정, 추론 강도, 모델 역할 설정, and Paseo 프로필 동기화. Do not use for unrelated model integrations or general Paseo troubleshooting.
---

# OMP / Paseo model calibration

Produce an evidence-backed decision, not an automatic upgrade. A newer model, lower token price, or lower reasoning setting does not establish a lower cost per successful task. Preserve demonstrated behavior until the evidence supports changing it.

## Scope and permissions

Distinguish three requests:

- **Research/check/recommend:** inspect and report; do not edit configuration, update binaries, launch inference, or reload services implicitly.
- **Apply configuration:** edit the repository in an isolated worktree; preserve user changes. This does not authorize workstation activation.
- **Benchmark:** agree on candidates, representative tasks, repetition count, provider/account route, and spending/usage bounds before running inference. A catalog check is not a benchmark.

Follow repository instructions. Do not run activation, setup-apm, service reload/restart, or credential changes without explicit approval. Do not expose credentials, copy local overrides into git, or send private code to a different provider to bypass availability. Commit/push/PR only when requested.

This is a repository-local authored skill under `.agents/skills/`, discovered in this checkout by OMP. It is not APM-generated content; do not register it as a remote dependency or claim it is installed globally. Paseo sessions using OMP in this checkout can discover it; other providers are outside this skill's deployment contract.

## 1. Establish the actual baseline

Read only the relevant sections of:

| File | Responsibility |
|---|---|
| `release-pins.json`, `modules/omp.nix` | OMP release, arm64 artifact URL and integrity hash |
| `home/.omp/agent/config.yml` | Roles, agent overrides, isolation and LSP |
| `home/.omp/agent/agents/frontend.md` | Frontend model, effort and UI verification instructions |
| `home/.paseo/config.json` | Profiles and provider default/additionalModels |
| `modules/home-manager.nix` | Ownership and deployment of configuration payloads |
| `home/.zshrc` | Loading of machine-local overlays |

Inspect the installed binary version and resolved executable path. Separate repository pins, installed binary, catalog contents, effective configuration, and successful inference; none proves the next. Inspect only model-related local overlay keys when necessary, without dumping secrets. Account for `PI_CONFIG_FILES`, profile selection and CLI overrides.

When a baseline value is not supplied or observed, mark it unknown. Do not infer an OMP role's current effort from its Paseo counterpart; existing drift is precisely what synchronization must detect.

Keep model identity, effort and display labels separate. `additionalModels` is for model IDs, labels and default selection, not profile reasoning; put Paseo effort in `thinkingOptionId`. Keep concrete OMP selectors in roles and agent overrides as aliases, rather than duplicating selectors during synchronization.

Read current OMP model/agent discovery documentation and CLI help before assuming options, precedence or alias behavior. Read current Paseo profile/provider docs for changes to that schema. Use the available documentation tools and relevant skills. Avoid relying on this document for version-specific API syntax.

If availability may depend on an old client, check the current stable release before declaring a model unavailable. For this Nix-owned OMP, update only its release pin and actual arm64 artifact hash when authorized; do not self-update the Nix store binary. Keep `flake.lock` and unrelated pins unchanged unless explicitly requested. Build and inspect the new binary by its explicit path before considering activation.

Query exact provider selectors and their supported reasoning levels. A catalog refresh updates a cache: disclose it if performed. Do not use fuzzy matches, invented model registrations, or an unapproved alternate provider as evidence of access. If a refreshed, updated client still lacks a selector, investigate release/catalog/provider discovery and report the precise missing layer.

## 2. Research evidence, including contrary results

Search current official release/model documentation, independent benchmark publishers, and firsthand user reports. Fetch source pages rather than treating search-generated summaries as established facts. A copied launch article is not an independent measurement. Read the benchmark methodology/version and effort settings, not just the headline score.

For each decisive claim record:

| Source/date | Exact model + effort | Provider/harness | Workload + metric | Result | Limitation |
|---|---|---|---|---|---|

Separate these evidence classes:

1. Locally observed configuration/catalog/inference facts.
2. Independent measurements with identifiable workload and settings.
3. Vendor-reported evaluations and internal tests.
4. Firsthand anecdotes with or without reproduction details.
5. Search snippets or inaccessible sources: leads only, not verified findings.

Look for regressions as well as improvements, especially coding correctness, scope discipline, tool use and unnecessary retries. If a page is inaccessible, try another supported retrieval method or independent source; disclose what remains unverified. Do not turn a handful of launch-day posts into a community consensus. Link sources in the final report and identify observation dates. Distinguish a benchmark site's deprecated label from an official API retirement notice.

Do not persist current prices, rankings or release candidates as timeless facts in this skill. Recheck them on every calibration.

## 3. Separate model generation from reasoning effort

Use the incumbent configuration as the control. For an incumbent `old-model:max`, compare in this order:

1. `old-model:max` versus `new-model:max`: generation change.
2. `new-model:max` versus `new-model:high`: reasoning change.
3. Lower settings only for roles whose workload justifies them.

Do not infer `new:high >= old:max` from `new:max` benchmark results. Similarly, a high-effort improvement in workflow automation does not establish coding parity or superiority over max. Rounded equal aggregate scores do not imply identical behavior, and a benchmark's price-class rank is not a global rank.

Keep four quantities distinct:

- Output/reasoning tokens for one response.
- Total input, cached input, output and reasoning tokens across the completed task, including tool loops and rework. Check whether reported output already includes reasoning before summing.
- API cost using the applicable context tier, cache rates and actual usage.
- Codex subscription usage/limits, which cannot be inferred from API prices.

Lower effort can require more retries; max can therefore be efficient per successful task. Conversely, max is not automatically best for every small task. Output tokens/second excludes time to first token, reasoning latency, tool time and retries; it is not end-to-end completion speed. Shorter visible answers do not prove fewer reasoning tokens. API context limits do not establish Codex context limits.

When evidence is insufficient, keep the incumbent effort for correctness-sensitive implementation and label proposed lower settings as provisional. A migration candidate is not a proven optimum.

## 4. Optional controlled local comparison

Only after benchmark authorization, use identical repository snapshots, prompts, instructions, tools, completion criteria and provider routes. Run edit-producing trials in separate disposable worktrees. Prevent activation, pushes, credential access and destructive operations within trials.

Choose tasks representative of the changed role: scoped implementation with behavioral verification for task, relevant-file discovery with known coverage for scout, and exact mechanical work for tiny. Define the quality gate before seeing results. Repeat candidates and vary run order; record failures, timeouts and unsuccessful runs rather than dropping them. Report sample size and limitations instead of overclaiming significance from a small sample.

Capture requested and observed concrete model/effort, success/quality, total tokens with cache/reasoning accounting, elapsed time, tool calls and repair attempts. Treat unsupported usage fields as unknown, never zero. Attribute price-derived estimates separately from provider-reported costs. Prefer cost/time per accepted outcome to raw token minimization. Store reusable aggregate decisions only if requested; keep private prompts, logs and machine-local state out of git.

## 5. Recommend coherent OMP and Paseo settings

Preserve user preferences unless they explicitly change them. The baseline policy for this repository is:

- SOL-family main; ASTRA-class models only for explicitly selected deep work.
- No automatic expensive fallback or always-on advisor.
- Ordinary plan/review should not silently select ASTRA.
- Frontend retains its existing Claude model/effort and browser verification contract unless frontend selection is in scope.
- A previous LUNA generation may remain when availability or measured task behavior supports it, not because older supposedly means cheaper.

These are routing preferences, not permanent endorsements of a specific generation. Re-evaluate exact models and efforts from evidence.

Put concrete selectors and supported effort in `modelRoles`; quote aliases in `task.agentModelOverrides`. Cover default, plan, review, security, task, smol, tiny and slow when proposing a complete routing table. Map task/scout/sonic/reviewer/security-reviewer to their corresponding roles. Preserve `task.isolation`, `task.enableLsp`, unrelated configuration, and frontend frontmatter. Check implicit fallback behavior if a role is omitted.

For Paseo, synchronize both `daemon.agentProfiles` and `agents.providers.omp.additionalModels` default. Keep `provider: omp` and existing modes unless a mode change was requested. Reuse profile IDs for the same purpose where practical; explicitly report repurposed IDs. Use labels such as `Worker · <exact model generation> · max`, matching actual model and thinking fields. Keep a small Daily/Worker/Review/Deep/UI set unless another profile is useful to the user. Additional models merge/label discovery; they do not grant access. Avoid replacing the whole `models` list. A profile's name does not enforce read-only review, and changed saved profiles do not alter running agents.

Exclude Aside and other model consumers unless explicitly requested.

## 6. Apply and verify only the requested scope

For requested edits, inspect current schema/callsites, make the smallest coherent change and validate using the actual updated OMP binary. Verify config loading, aliases and concrete role selection without confusing discovery with inference. Use a bounded inference smoke only when authorized; observe the concrete model instead of trusting its self-identification. Check effective overlays and profile/CLI precedence.

For Nix changes, follow repository formatting, diff review and both-host evaluation/build requirements. Report inspection, evaluation, build, inference smoke and activation separately. A successful build is not activation, and source config is not necessarily what a running Paseo daemon has loaded.

Do not change release pins merely to submit a recommendation. When preparing a requested PR, include evidence-driven changes, verification actually run, remaining uncertainty and any approval needed for activation.

## Output contract

Answer in the user's language; prefer tables. Include:

1. **Decision:** retain/migrate/provisional, with dated scope and uncertainty.
2. **Evidence:** incumbent versus candidate, exact effort and workload, tokens/cost/time, linked sources and caveats.
3. **OMP:** role, current selection, proposed selection, reasoning, rationale/confidence.
4. **Paseo:** profile label, model, thinking, ID preservation/replacement and provider default.
5. **Execution state:** what was inspected/refreshed/edited/built/called/activated, and what remains unverified.

For a narrow research question, show only affected rows rather than inventing a complete migration. Explicitly correct earlier recommendations when new evidence undermines them. Do not label a configuration optimal without defining the objective and providing matching evidence.
