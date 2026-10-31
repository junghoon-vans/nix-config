{
  config,
  lib,
  inputs,
  pkgs,
  ...
}:

let
  cfg = config.workstation.hermes;
  user = config.system.primaryUser;
  home = config.users.users.${user}.home;
  profileName = "omp-worker";
  profilePath = ".hermes/profiles/${profileName}";
  profileHome = "${home}/${profilePath}";
  yaml = pkgs.formats.yaml { };
  providerSource = inputs.hermes-omp-acp;
  delegationSource = "${inputs.hermes-official-plugins}/advanced-delegation";
  hermesPackages = inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system};
  # Hermes 0.22.5 attaches Linux ELF fixups to its Darwin pm artifacts too.
  # Keep the upstream artifact pins, but do not run auto-patchelf on Mach-O.
  pmPackages = lib.mapAttrs' (
    name: package:
    lib.nameValuePair (lib.removePrefix "pm-" name) (package.overrideAttrs { dontAutoPatchelf = true; })
  ) (lib.filterAttrs (name: _: lib.hasPrefix "pm-" name) hermesPackages);
  supportPython = pkgs.python3.withPackages (ps: [
    ps.pyyaml
  ]);
  ompAcpConfig = yaml.generate "hermes-omp-acp-config.yaml" {
    retry = {
      maxRetries = 3;
      baseDelayMs = 2000;
    };
  };
  gatewayPath = "${
    lib.makeBinPath [
      pkgs.git
      config.workstation.omp.package
      cfg.package
    ]
  }:/run/current-system/sw/bin:/etc/profiles/per-user/${user}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin";
  hermesConfig = yaml.generate "hermes-config.nix.yaml" {
    model = {
      provider = "openai-codex";
      default = cfg.model;
    };
    providers."omp-acp".stale_timeout_seconds = 1800;
    skills.external_dirs = [
      "${providerSource}/skills"
      "${home}/.agents/skills"
    ];
    # This Home Manager-owned profile runs separately from the default host gateway.
    gateway.standalone = true;
    agent = {
      max_turns = 30;
      system_prompt = ''
        You coordinate workers through delegate_task. Use fast for quick answers
        and summaries of supplied context, and deep for careful reasoning,
        planning and review of supplied context. These routes call OpenAI directly.
        Use omp for current web search and all repository inspection, implementation
        and verification. It runs OMP through ACP with OMP's native search and coding
        tools; fast and deep do not fetch external evidence or inspect repositories.
        For search/검색, include the question, freshness requirements and requested
        sources. Require actual search, linked citations and explicit uncertainty;
        never invent search results. A web-only task does not require a repository.
        Include complete requirements and relevant previous results in every task.
        For repository tasks on omp, include the absolute repository path and only use repositories under:
        ${lib.concatStringsSep "\n" cfg.repositoryRoots}
        Ask which repository to use when ambiguous. Each delegation starts fresh:
        do not assume a previous OMP session or worktree is resumed. For changes,
        require the worker to create or reuse an isolated Git worktree and report
        its path, branch, actual verification and any failures. Never repeat a
        failed or interrupted mutation blindly or infer success from prose alone.
        Push, deployment and permission changes require explicit user approval.
        Additional OMP permission requests are denied, not relayed to Slack.
        Report blocked operations and ask how to proceed; do not escalate permissions.
      '';
    };
    platform_toolsets = {
      slack = [
        "delegation"
        "cronjob"
        "session_search"
        "memory"
        "skills"
      ];
      cli = [
        "delegation"
        "cronjob"
        "session_search"
        "memory"
        "skills"
      ];
    };
    platforms.slack = {
      enabled = true;
      reply_to_mode = "first";
      extra = {
        rich_blocks = true;
        reply_in_thread = true;
        reply_broadcast = false;
        require_mention = true;
        strict_mention = true;
        thread_require_mention = true;
        allow_bots = "mentions";
      };
    };
    delegation = {
      backend = "model_map";
      fallback_providers = [ ];
      backends.model_map = {
        default = "fast";
        options = [
          {
            name = "fast";
            description = "Quick answers and summaries of supplied context through OpenAI; use omp for web search and repository tools.";
            provider = "openai-codex";
            model = "gpt-6-luna";
            fallback_providers = [ ];
          }
          {
            name = "deep";
            description = "Careful reasoning, planning and review of supplied context through OpenAI; use omp for web search and repository tools.";
            provider = "openai-codex";
            inherit (cfg) model;
            fallback_providers = [ ];
          }
          {
            name = "omp";
            description = "Current web search with linked sources, repository inspection, implementation and verification through OMP and its native tools.";
            provider = "omp-acp";
            model = "openai-codex/gpt-6.1-sol";
            fallback_providers = [ ];
          }
        ];
      };
    };
    plugins = {
      enabled = [
        "omp-acp-provider"
        "advanced-delegation"
      ];
      entries.omp-acp-provider.settings = {
        command = lib.getExe config.workstation.omp.package;
        args = [
          "acp"
          "--config"
          "${ompAcpConfig}"
          "--approval-mode"
          "yolo"
        ];
        mcp_enabled = true;
      };
    };
    approvals = {
      mode = "manual";
      timeout = 300;
      unattended_mode = "deny";
      single_query_mode = "deny";
    };
    terminal = {
      backend = "local";
      cwd = home;
    };
    unauthorized_dm_behavior = "ignore";
    kanban.dispatch_in_gateway = false;
    cron.wrap_response = false;
    mcp_servers = { };
    display = {
      tool_progress = "all";
      long_running_notifications = true;
      platforms.slack = {
        tool_progress = "off";
      };
    };
  };
in
{
  options.workstation.hermes = {
    enable = lib.mkEnableOption "the local Slack to OMP ACP gateway";
    package = lib.mkOption {
      type = lib.types.package;
      default = hermesPackages.messaging.override {
        inherit pmPackages;
        version = lib.removePrefix "v" (builtins.fromJSON (builtins.readFile ../flake.lock))
        .nodes.hermes-agent.original.ref;
        extraDependencyGroups = [
          "messaging"
          "acp"
        ];
      };
      description = "Upstream Hermes messaging package with its official ACP dependency group.";
    };
    model = lib.mkOption {
      type = lib.types.str;
      default = "gpt-6.1-sol";
      description = "Hermes coordinator and deep-route model; omp uses the separate OMP ACP provider.";
    };
    repositoryRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "${home}/workspace" ];
      description = "Repository roots included in coordinator instructions; not an enforced allowlist or OS sandbox.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    assertions = [
      {
        assertion = config.workstation.omp.enable && cfg.repositoryRoots != [ ];
        message = "The Hermes gateway requires OMP and at least one repository root.";
      }
    ];
    system.build = {
      inherit hermesConfig;
      hermesRuntimeCheck =
        pkgs.runCommand "hermes-runtime-check"
          {
            HERMES_INSTALL_ROOT = "${cfg.package}/share/hermes-agent";
            HERMES_BUNDLED_PLUGINS = "${cfg.package}/share/hermes-agent/plugins";
            HERMES_BUNDLED_SKILLS = "${cfg.package}/share/hermes-agent/skills";
            PYTHONDONTWRITEBYTECODE = "1";
          }
          ''
            ${cfg.package.hermesVenv}/bin/python3 ${../tests/hermes/test_packaged_runtime.py} \
              ${hermesConfig} ${providerSource} ${delegationSource} ${lib.escapeShellArg cfg.package.version} \
              ${lib.getExe config.workstation.omp.package} \
              ${
                config.home-manager.users.${user}.home.activationPackage
              }/LaunchAgents/org.nixos.hermes.gateway-${profileName}.plist
            touch "$out"
          '';
    };

    home-manager.users.${user} = { lib, ... }: {
      home = {
        file = {
          "${profilePath}/config.nix.yaml".source = hermesConfig;
          "${profilePath}/SOUL.md".source = ../home/.hermes/profiles/omp-worker/SOUL.md;
          # Partial overlay for the profile's default English UI; keep the scheduler's name intact.
          "${profilePath}/locales/en.yaml".source = yaml.generate "hermes-slack-locale.yaml" {
            platform.slack.handoff.seed = "*{name}*";
          };
          "${profilePath}/plugins/omp-acp-provider".source = providerSource;
          "${profilePath}/plugins/advanced-delegation".source = delegationSource;
        };
        activation = {
          prepareHermes =
            lib.hm.dag.entryBetween [ "linkGeneration" "setupLaunchAgents" ] [ "writeBoundary" ]
              ''
                run ${pkgs.bash}/bin/bash ${../scripts/hermes/prepare-profile.sh} \
                  ${lib.getExe cfg.package} ${lib.escapeShellArg "${home}/.hermes"} ${lib.escapeShellArg profileName}
              '';
          prepareHermesConfig =
            lib.hm.dag.entryBetween [ "setupLaunchAgents" ] [ "linkGeneration" "prepareHermes" ]
              ''
                run ${supportPython}/bin/python3 ${../scripts/hermes/prepare-config.py} \
                  ${lib.escapeShellArg profileHome} ${hermesConfig}
              '';
        };
      };
      launchd.agents.hermes = {
        enable = true;
        config = {
          # Outside Hermes's ai.hermes.gateway-* namespace: only Home Manager owns this job.
          Label = "org.nixos.hermes.gateway-${profileName}";
          ProgramArguments = [
            (lib.getExe cfg.package)
            "--profile"
            profileName
            "gateway"
            "run"
            "--external-supervisor"
          ];
          EnvironmentVariables = {
            HERMES_HOME = profileHome;
            PATH = gatewayPath;
            PYTHONDONTWRITEBYTECODE = "1";
          };
          RunAtLoad = true;
          KeepAlive.SuccessfulExit = false;
          ThrottleInterval = 30;
          WorkingDirectory = home;
          StandardOutPath = "${profileHome}/logs/gateway.log";
          StandardErrorPath = "${profileHome}/logs/gateway.error.log";
          ProcessType = "Background";
          ExitTimeOut = 30;
        };
      };
    };
  };
}
