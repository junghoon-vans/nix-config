let
  ompTransport = builtins.fromJSON (builtins.readFile ../../home/.omp/agent/mcp.json);
  capabilities = {
    atlassian = "Jira and Confluence";
    github = "repository, issue, PR and CI workflows";
    context7 = "library and framework documentation";
    notion = "workspace documents and databases";
    slack = "Slack tools with user OAuth; ask for explicit confirmation before sending or scheduling messages";
    gnomcp = "Gno chain and realm tools";
    ux-ui-gates = "design doctrine, tokens and UI gates";
  };
in
rec {
  hermes = {
    context7 = {
      url = ompTransport.mcpServers.context7.url;
      tools = {
        include = [
          "resolve-library-id"
          "query-docs"
        ];
        resources = false;
        prompts = false;
      };
    };
    notion = {
      url = ompTransport.mcpServers.notion.url;
      auth = "oauth";
      tools = {
        include = [
          "notion-search"
          "notion-fetch"
          "notion-get-self"
          "notion-get-tool-access"
          "notion-query-data-sources"
          "notion-get-comments"
          "notion-create-pages"
          "notion-update-page"
          "notion-update-data-source"
          "notion-get-async-task"
        ];
        resources = true;
        prompts = false;
      };
    };
    github = {
      url = ompTransport.mcpServers.github.url;
      protocol = "stateless";
      headers = {
        Authorization = "Bearer \${HERMES_GITHUB_TOKEN}";
        X-MCP-Readonly = "true";
        X-MCP-Toolsets = "context,repos,pull_requests,actions";
      };
      tools = {
        include = [
          "get_me"
          "search_repositories"
          "list_pull_requests"
          "search_pull_requests"
          "pull_request_read"
          "actions_list"
          "actions_get"
          "get_job_logs"
        ];
        resources = false;
        prompts = false;
      };
    };
    atlassian = {
      url = ompTransport.mcpServers.atlassian.url;
      auth = "oauth";
      tools = {
        include = [
          "atlassianUserInfo"
          "getAccessibleAtlassianResources"
          "getJiraIssue"
          "searchJiraIssuesUsingJql"
          "getConfluenceContent"
          "searchConfluence"
        ];
        resources = false;
        prompts = false;
      };
    };
  };

  managedHermesServers = builtins.attrNames hermes;

  awareness = ''
    Native Hermes Notion tools read documents and allow page/row/schema writes; native
    GitHub tools inspect PRs and CI, while Atlassian remains read/search-only.
    Client allowlists filter tools, not OAuth/token permissions or arguments accepted by an
    allowed tool. Before changing data-source options, fetch the current schema, preserve
    existing options, and require the user's explicit confirmation before destructive
    changes, including trashing pages, removing options, dropping schema, or deleting content.
    Check notion-get-async-task for the status of asynchronous writes.
    Native Hermes Atlassian tools are allowlisted for identity/site discovery and Jira/
    Confluence read/search only; no write or destructive tools are enabled.
    Use Ego Lite for browser work, not an MCP browser server.
    Before browser submissions, destructive actions, purchases, or messages, obtain the
    user's explicit confirmation. Preserve logged-in sessions and existing tabs; do not
    log out, clear browser data, switch profiles, or close unrelated tabs.
    OMP is configured with these MCP capabilities:
    ${builtins.concatStringsSep "\n" (
      builtins.map (name: "- ${name}: ${capabilities.${name}}") (
        builtins.attrNames ompTransport.mcpServers
      )
    )}
    Configured does not mean authenticated. Native Hermes discovery and authentication are
    unverified; verify actual native tool availability and access in the active profile
    before claiming success. Atlassian uses the v2 flat tool catalog so the read/search
    allowlist can select exact tools; each client must reauthenticate for the v2 resource.
    Likewise verify OMP connectivity in its delegated session; offline fixtures are not
    live evidence. Native Hermes Context7 tools resolve library IDs and retrieve framework
    documentation. Use delegate_task with option omp for gnomcp, ux-ui-gates, repository work,
    and other OMP-only capabilities; allowlisted native Notion writes may be used directly.
    Never copy OAuth state or tokens between clients or profiles.
  '';
}
