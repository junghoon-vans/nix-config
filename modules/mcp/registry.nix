{
  asideCommand,
}:
let
  ompTransport = builtins.fromJSON (builtins.readFile ../../home/.omp/agent/mcp.json);
  capabilities = {
    atlassian = "Jira and Confluence";
    github = "repository, issue, PR and CI workflows";
    context7 = "library and framework documentation";
    notion = "workspace documents and databases";
    gnomcp = "Gno chain and realm tools";
    ux-ui-gates = "design doctrine, tokens and UI gates";
    aside = "logged-in browser automation";
  };
in
rec {
  omp = ompTransport // {
    mcpServers = ompTransport.mcpServers // {
      aside = ompTransport.mcpServers.aside // {
        command = asideCommand;
      };
    };
  };

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
    aside = {
      command = asideCommand;
      args = [ "mcp" ];
      trust = "untrusted";
      sampling.enabled = false;
      tools = {
        include = [
          "browser_profiles"
          "exec"
          "repl"
          "memory_search"
        ];
        resources = false;
        prompts = false;
      };
    };
  };

  managedHermesServers = builtins.attrNames hermes;

  awareness = ''
    Native Hermes Notion tools read documents; native GitHub tools inspect PRs and CI.
    Their client allowlists are read-only, not proof of narrower OAuth/token permissions.
    Native Hermes Context7 tools resolve library IDs and retrieve framework documentation.
    Native Hermes Atlassian tools are allowlisted for identity/site discovery and Jira/
    Confluence read/search only; no write or destructive tools are enabled.
    Native Hermes Aside exposes browser profiles, browser control, and memory search.
    Before browser submissions, destructive actions, purchases, or messages, obtain the
    user's explicit confirmation. Preserve the logged-in session and existing tabs; do not
    log out, clear browser data, switch profiles, or close unrelated tabs.
    OMP is configured with these MCP capabilities:
    ${builtins.concatStringsSep "\n" (
      builtins.map (name: "- ${name}: ${capabilities.${name}}") (
        builtins.attrNames ompTransport.mcpServers
      )
    )}
    Configured does not mean authenticated. Native Hermes discovery and authentication are
    unverified; verify actual native tool availability and access in the active profile
    before claiming success. The Atlassian allowlist uses v2 catalog tool names while its
    shared OMP URL remains v1/authv2; v1 discovery and authentication are unverified.
    Likewise verify OMP connectivity in its delegated session; offline fixtures are not
    live evidence. Use delegate_task with option omp for gnomcp, ux-ui-gates, repository
    work, and approved writes. Never copy OAuth state or tokens between clients or profiles.
  '';
}
