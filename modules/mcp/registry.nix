{
  asideCommand ? "aside",
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
{
  omp = ompTransport // {
    mcpServers = ompTransport.mcpServers // {
      aside = ompTransport.mcpServers.aside // {
        command = asideCommand;
      };
    };
  };

  hermes = {
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
  };

  managedHermesServers = [
    "notion"
    "github"
  ];

  awareness = ''
    Native Hermes Notion tools read documents; native GitHub tools inspect PRs and CI.
    Their client allowlists are read-only, not proof of narrower OAuth/token permissions.
    OMP is configured with these MCP capabilities:
    ${builtins.concatStringsSep "\n" (
      builtins.map (name: "- ${name}: ${capabilities.${name}}") (
        builtins.attrNames ompTransport.mcpServers
      )
    )}
    Configured does not mean authenticated. Authentication and live discovery are unverified;
    verify actual tool availability and access in the delegated OMP session before claiming
    success. Use delegate_task with option omp for these additional capabilities and
    approved writes. Never copy OAuth state or tokens between clients or profiles.
  '';
}
