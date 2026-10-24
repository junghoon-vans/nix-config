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
  providerSource = "${inputs.hermes-omp-acp}/model-provider";
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
    agent = {
      max_turns = 30;
      system_prompt = ''
        You coordinate workers through delegate_task. Use fast for quick answers
        and summaries of supplied context, and deep for careful reasoning,
        planning and review of supplied context. These routes call OpenAI directly.
        Use coder for all repository inspection, implementation and verification:
        it runs OMP through ACP, and OMP owns repository tools.
        Include complete requirements and relevant previous results in every task.
        For coder tasks, include the absolute repository path and only use repositories under:
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
      slack = [ "delegation" ];
      cli = [ "delegation" ];
    };
    platforms.slack = {
      enabled = true;
      reply_to_mode = "first";
      extra = {
        reply_in_thread = true;
        reply_broadcast = false;
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
            description = "Quick answers and summaries of supplied context through OpenAI; use coder for repository tools.";
            provider = "openai-codex";
            model = "openai/gpt-6-luna";
            fallback_providers = [ ];
          }
          {
            name = "deep";
            description = "Careful reasoning, planning and review of supplied context through OpenAI; use coder for repository tools.";
            provider = "openai-codex";
            model = cfg.model;
            fallback_providers = [ ];
          }
          {
            name = "coder";
            description = "Repository inspection, implementation and verification through the local OMP agent and its native tools.";
            provider = "omp-acp";
            model = "openai-codex/gpt-6.1-sol";
            fallback_providers = [ ];
          }
        ];
      };
    };
    plugins.enabled = [
      "omp-acp-provider"
      "advanced-delegation"
    ];
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
    mcp_servers = { };
    display = {
      tool_progress = "all";
      long_running_notifications = true;
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
      description = "Upstream Hermes messaging package with the official ACP SDK dependency.";
    };
    model = lib.mkOption {
      type = lib.types.str;
      default = "openai/gpt-6.1-sol";
      description = "Hermes coordinator and deep-route model; coder uses the separate OMP ACP provider.";
    };
    repositoryRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "${home}/workspace" ];
      description = "Repository roots included in coordinator instructions; not an enforced allowlist or OS sandbox.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    environment.variables.HERMES_OMP_ACP_COMMAND = lib.getExe config.workstation.omp.package;
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
            PYTHONDONTWRITEBYTECODE = "1";
            HERMES_OMP_ACP_COMMAND = lib.getExe config.workstation.omp.package;
          }
          ''
            ${cfg.package.hermesVenv}/bin/python3 ${../scripts/hermes/check-runtime.py} \
              ${hermesConfig} ${providerSource} ${delegationSource} ${lib.escapeShellArg cfg.package.version}
            touch "$out"
          '';
    };

    home-manager.users.${user} = { lib, ... }: {
      home = {
        file = {
          "${profilePath}/config.nix.yaml".source = hermesConfig;
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
          Label = "ai.hermes.gateway-${profileName}";
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
            HERMES_OMP_ACP_COMMAND = lib.getExe config.workstation.omp.package;
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
