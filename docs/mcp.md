# MCP Integrations

| Integration | Owner | Configuration | Runtime boundary |
| --- | --- | --- | --- |
| gnomcp | Nix | `modules/mcp/gnomcp.nix`, `modules/mcp/registry.nix` | Fixed local stdio server; Hermes reaches it only through delegated OMP |
| OMP MCP registry | Nix + transport data | `modules/mcp/registry.nix`, `home/.omp/agent/mcp.json` | Seven configured servers: Atlassian, GitHub, Context7, Notion, gnomcp, UX/UI gates, Aside |
| Hermes coordinator | Nix registry projection | `modules/hermes.nix` | Five native MCP servers in the `omp-worker` profile; gnomcp and UX/UI gates remain delegation-only |
| UX/UI gates | External npm runtime | `home/.omp/agent/mcp.json` | Version-pinned npm invocation; Hermes uses it through delegated OMP |
| Aside | Homebrew cask + Nix wrapper | `modules/aside.nix`, `modules/mcp/registry.nix` | OMP JSON and Hermes command resolve through the packaged Aside CLI wrapper |

Credentials and authentication state are always user-local. Do not add API keys, OAuth state, or
machine-specific account files to this repository or the Nix store.

Update a fixed local server through its Nix module with its version, URL, and integrity hash. Treat
hosted and npm-backed services as external runtime dependencies: generated configuration does not
prove authentication, live tool discovery, connectivity, or current browser-session exposure.

`modules/mcp/registry.nix` is the client projection entrypoint. It imports OMP transport records
from the existing JSON source so npm updates and MCP security scanning keep their existing input
contract. The OMP registry retains all seven servers. Hermes projects five integrations natively:
Notion, GitHub, Context7, Atlassian, and Aside. `gnomcp` and `ux-ui-gates` are available only via
`delegate_task`'s `omp` route. Context7 and Atlassian reuse their OMP endpoint declarations, but
authentication syntax and state remain client-specific. The Hermes awareness prompt describes
configured OMP capabilities, not proof that any server is authenticated or usable.

## Hermes coordinator: five native integrations

The Hermes version is pinned in `flake.nix` / `flake.lock`. Nix generates
`~/.hermes/profiles/omp-worker/config.nix.yaml`; profile preparation overlays it onto the
private writable `config.yaml`. CLI and Slack expose the native MCP toolsets alongside
`delegation`, `cronjob`, `session_search`, `memory`, and `skills`. Repository inspection,
implementation, verification, `gnomcp`, UX/UI gates, and other OMP-only capabilities go through
`delegate_task`'s `omp` route. Other profiles and the default Hermes home are unchanged.

### Context7

Hermes uses the existing configured endpoint, `https://mcp.context7.com/mcp`, with the exact
server-native allowlist `resolve-library-id` and `query-docs`. Resolve a library ID first unless
the request already supplies one, then query its documentation. The OMP transport does not declare
a Context7 API-key header. Context7 documents Bearer API-key authentication for `/mcp` and remote
OAuth at `/mcp/oauth`; neither option is evidence that this configured endpoint has been
authenticated or reached. Its live availability remains unverified.

### Atlassian

Native Hermes reuses the OMP Atlassian URL, `https://mcp.atlassian.com/v1/mcp/authv2`, with
`auth: oauth`. Its exact allowlist is `atlassianUserInfo`, `getAccessibleAtlassianResources`,
`getJiraIssue`, `searchJiraIssuesUsingJql`, `getConfluenceContent`, and `searchConfluence`.
No deferred catalog or generic `discover`, `executeRead`, `executeWrite`, or
`executeDestructive` tools are exposed. The allowlist contains exact read/search tools from
Atlassian's current v2 catalog; because the configured endpoint is v1, actual tool discovery and
authentication remain unverified. The static allowlist is not evidence that every listed tool is
exposed by this endpoint.

Atlassian documents OAuth as an interactive flow in which the user reviews and grants consent.
Available tools and data depend on that consent, granted scopes, organization settings, and the
user's site access; the client allowlist does not narrow the authority granted at consent. Do not
copy an OMP token or OAuth state into Hermes. Atlassian's migration guide says v1 will automatically
expose v2 tools from 2027-03-01; this change leaves the existing OMP URL unchanged.

### Aside

Hermes exposes only the exact server-native tools `browser_profiles`, `exec`, `repl`, and
`memory_search`; MCP sampling is disabled and the server is marked `trust: untrusted`.
The allowlist does not enable arbitrary Aside tools or bypass normal approval behavior: execution
tools remain subject to Hermes' standard approval surface and the user's existing Aside rules,
including the configured sandbox and prompts for outside-file access. The coordinator also requires
explicit user confirmation before browser submissions, destructive actions, purchases, or messages;
preserve the current logged-in session and tabs rather than switching profiles, clearing browser
data, or closing unrelated tabs.

The command is a Nix-packaged wrapper that forwards arguments to
`$HOME/.aside/cli/Aside CLI.app/Contents/MacOS/aside`; Hermes runs it with the `mcp` argument.
The Aside Homebrew app/CLI must therefore be installed and initialized locally. Browser work also
requires a user-configured browser profile and any intended site session in Aside. The wrapper
does not copy login state, and static configuration does not establish which profiles or logged-in
sessions are currently exposed.

### Notion and GitHub

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

### One-time user prerequisites after a separately approved activation

- Notion: run `hermes -p omp-worker mcp login notion` interactively and review the vendor's
  consent. Hermes stores MCP OAuth state in the active profile; do not copy another
  client's tokens or commit that state.
- GitHub: privately add `HERMES_GITHUB_TOKEN` to
  `~/.hermes/profiles/omp-worker/.env` using an editor/secret source, not a command-line
  token argument. Use a fine-grained PAT limited to selected repositories with read-only
  Metadata, Contents, Pull requests, Actions, and Checks permissions as needed for PR/CI
  inspection. Do not grant write permissions or reuse OMP's `!gh auth token` expression:
  Hermes expects a runtime `${HERMES_GITHUB_TOKEN}` placeholder, not shell substitution.
- Atlassian: only after activation is separately approved, run
  `hermes -p omp-worker mcp login atlassian` and review the OAuth consent in the browser.
  This consent is user-specific and separate from OMP authentication; do not copy its tokens
  or state between clients or profiles.
- Context7: the checked-in endpoint is configured without an API key and has not been tested
  live. Do not infer that it is authenticated or reachable from its generated URL. If the user
  later chooses an authentication method, keep its secret in that user's approved local secret
  store rather than the repository or Nix store.
- Aside: install and initialize the Aside app locally, then configure the intended browser
  profile/session in Aside. Do not copy or modify the user's browser profile as part of Hermes
  setup.
- Start a new profile session or restart the profile gateway only when separately approved.
  Verify discovered tools and any live vendor access only after the relevant user consent and
  approval. No activation, restart, OAuth consent, credential provisioning, live server call,
  profile mutation, or current-session inspection is performed as part of this change.

The five Nix-managed Hermes server names are derived from the registry declarations and currently
are `notion`, `github`, `context7`, `atlassian`, and `aside`. Profile preparation removes both
previously recorded names and the current generation's managed names before overlaying declarations,
then records the current list. This removes a retired managed server when its name disappears from
the registry. Historical `notion` and `github` entries are also cleaned from profiles created
before bookkeeping existed. Unrelated user-managed MCP entries and local settings remain intact;
user-owned `.env` and OAuth state files are never rewritten or copied.

`hermesRuntimeCheck` and preparation fixtures use synthetic/offline configuration and tool
discovery. They can verify generated filters, Hermes registration, CLI/Slack visibility, and
managed-entry replacement; they do not authenticate with vendors, establish live tool discovery,
or show what is exposed by a current Aside browser session. No live activation or gateway restart
was performed.

References: [Hermes MCP configuration](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference),
[Hermes MCP guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp),
[Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles),
[Notion tools](https://developers.notion.com/guides/mcp/mcp-supported-tools),
[GitHub remote configuration](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md),
[Context7 MCP clients, tools, and authentication](https://context7.com/docs/resources/all-clients.md),
[Atlassian supported tools](https://developer.atlassian.com/cloud/rovo-mcp/guides/supported-tools/),
[Atlassian OAuth](https://support.atlassian.com/atlassian-ai-gateway/docs/configure-oauth-2-1/),
and [Atlassian v1-to-v2 migration](https://support.atlassian.com/atlassian-ai-gateway/docs/how-to-upgrade-from-atlassian-mcp-v1-to-atlassian-mcp-v2/).
