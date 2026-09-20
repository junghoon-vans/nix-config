# MCP Integrations

| Integration | Owner | Configuration | Runtime boundary |
| --- | --- | --- | --- |
| gnomcp | Nix | `modules/mcp/gnomcp.nix`, `home/.omp/agent/mcp.json` | Fixed local stdio server |
| Hosted MCP servers | OMP config | `home/.omp/agent/mcp.json` | Atlassian, GitHub, Context7, and Notion endpoints |
| Firecrawl | External npm runtime | `home/.omp/agent/mcp.json` | Version-pinned npm invocation |
| Aside | Homebrew cask | `home/.omp/agent/mcp.json` | Executable discovery depends on the local app installation |

Credentials and authentication state are always user-local. Do not add API keys, OAuth state, or
machine-specific account files to this repository or the Nix store.

Update a fixed local server through its Nix module with its version, URL, and integrity hash. Treat
hosted and npm-backed services as external runtime dependencies and verify their connection after
an approved activation.
