# MCP Integrations

| Integration | Owner | Configuration | Runtime boundary |
| --- | --- | --- | --- |
| gnomcp | Nix | `modules/mcp/gnomcp.nix`, `modules/mcp/registry.nix` | Fixed local stdio server |
| OMP MCP registry | Nix + transport data | `modules/mcp/registry.nix`, `home/.omp/agent/mcp.json` | Atlassian, GitHub, Context7, Notion, gnomcp, UX/UI gates, Aside |
| Hermes coordinator | Nix registry projection | `modules/hermes.nix` | Native read-only Notion and GitHub; `omp-worker` only |
| UX/UI gates | External npm runtime | `home/.omp/agent/mcp.json` | Version-pinned npm invocation |
| Aside | Homebrew cask | `modules/aside.nix` | Sole OMP JSON owner; resolves the managed CLI wrapper |

Credentials and authentication state are always user-local. Do not add API keys, OAuth state, or
machine-specific account files to this repository or the Nix store.

Update a fixed local server through its Nix module with its version, URL, and integrity hash. Treat
hosted and npm-backed services as external runtime dependencies and verify their connection after
an approved activation.

`modules/mcp/registry.nix` is the client projection entrypoint. It imports transport
records from the existing JSON source so npm updates and MCP security scanning keep
their existing input contract. Endpoints are shared, not authentication syntax or state.
The Hermes system prompt is generated from the registry's capability descriptions:
other integrations are configured through the `omp` delegation route, not connected
natively to Hermes. Configured does not mean authenticated; the worker must verify
actual discovery and access before claiming a capability is usable.

## Hermes coordinator: Notion and GitHub

The Hermes version is pinned in `flake.nix` / `flake.lock`. Nix generates
`~/.hermes/profiles/omp-worker/config.nix.yaml`; profile preparation overlays it onto the
private writable `config.yaml`. CLI and Slack select `delegation`, `cronjob`,
`session_search`, `memory`, `skills`, `notion`, and `github`. Repository implementation,
other MCP capabilities and approved mutations go through `delegate_task`'s `omp` route.
Other profiles and the default Hermes home are unchanged.

Notion connects to `https://mcp.notion.com/mcp` with native `auth: oauth`.
Its server-native allowlist is `notion-search`, `notion-fetch`, `notion-get-self`,
`notion-get-tool-access`, `notion-query-data-sources`, and `notion-get-comments`.
Resource listing/reading stays enabled so vendor instructions and auth/bootstrap guidance
remain accessible; prompts and content mutation tools are not exposed. This is a client
tool restriction, not a reduction of permissions granted by the Notion OAuth consent.

GitHub connects to `https://api.githubcopilot.com/mcp/` with `X-MCP-Readonly: true`
and the `context,repos,pull_requests,actions` toolsets. Its server-native allowlist is
`get_me`, `search_repositories`, `list_pull_requests`, `search_pull_requests`,
`pull_request_read`, `actions_list`, `actions_get`, and `get_job_logs`.
Resources and prompts are disabled. No content-write, PR-write, merge, workflow dispatch,
or rerun tools are enabled. Read-only tool exposure does not narrow the underlying token.

GitHub prefers the modern stateless protocol (`protocol: stateless`) because the unified
`actions_list` / `actions_get` names require protocol negotiation at or above `2026-07-28`.
Hermes can fall back to a legacy handshake; a legacy-only response may omit these CI tools,
so verify the actual discovery after authentication rather than assuming CI access.

### One-time user prerequisites after an approved activation

- Notion: run `hermes -p omp-worker mcp login notion` interactively and review the vendor's
  consent. Hermes stores MCP OAuth state in the active profile; do not copy another
  client's tokens or commit that state.
- GitHub: privately add `HERMES_GITHUB_TOKEN` to
  `~/.hermes/profiles/omp-worker/.env` using an editor/secret source, not a command-line
  token argument. Use a fine-grained PAT limited to selected repositories with read-only
  Metadata, Contents, Pull requests, Actions, and Checks permissions as needed for PR/CI
  inspection. Do not grant write permissions or reuse OMP's `!gh auth token` expression:
  Hermes expects a runtime `${HERMES_GITHUB_TOKEN}` placeholder, not shell substitution.
- Start a new profile session and restart the profile gateway only when separately approved.
  Check the connection and available tools with `hermes -p omp-worker mcp list`, then
  exercise a known Notion document and GitHub PR/CI read. No credential provisioning,
  OAuth consent, gateway restart, or live vendor connection is performed by repository checks.

The `notion` and `github` names are Nix-owned whole entries: preparation removes their old
fields before overlaying declarations, and removes an entry when its declaration is deleted.
The `nix_managed_mcp_servers` runtime bookkeeping list records each generation's managed
names, so newly added and later retired entries are removed too. Historical Notion/GitHub
names are cleaned even on profiles predating bookkeeping. This prevents stale transports,
credentials or permissive filters from surviving a cutover. Other user-managed MCP servers
and local settings remain intact, but additional servers are not selected by the managed
CLI/Slack toolsets. Secrets and auth files are never rewritten.

`hermesRuntimeCheck` uses synthetic offline tool discovery to exercise the pinned Hermes
registration/filtering and CLI/Slack visibility, including Notion resources and GitHub token
placeholder expansion. This proves configuration compatibility, not external authorization
or live connectivity. Preparation regression tests cover entry replacement/deletion,
local-state preservation and idempotence.

References: [Hermes MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference),
[MCP authentication](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp),
[profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles),
[Notion tools](https://developers.notion.com/guides/mcp/mcp-supported-tools),
and [GitHub remote configuration](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md).
