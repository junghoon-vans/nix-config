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
  pluginSource = "${inputs.hermes-omp-acp}/delegator";
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
        You are the Slack interface to the local OMP coding worker. Use omp_task for
        all repository inspection, implementation and verification. OMP, not you,
        owns coding tools. Ask for the repository if it is ambiguous. Reuse the
        existing task for follow-up instructions; never repeat a failed or
        interrupted mutation blindly. Use omp_status to inspect retained state.
        Report the worktree, actual verification and failures faithfully. Never
        claim a task succeeded from a summary without the worker's evidence.
        Push, deployment and permission changes require explicit user approval.
        Additional OMP permission requests are denied, not relayed to Slack.
        Report permission_required and ask how to proceed; do not escalate permissions.
      '';
    };
    platform_toolsets = {
      slack = [ "omp-acp-delegator" ];
      cli = [ "omp-acp-delegator" ];
    };
    platforms.slack = {
      enabled = true;
      reply_to_mode = "first";
      extra = {
        reply_in_thread = true;
        reply_broadcast = false;
      };
    };
    plugins = {
      enabled = [ "omp-acp-delegator" ];
      entries.omp-acp-delegator.settings = {
        allowed_roots = cfg.repositoryRoots;
        timeout = 1800;
        omp_command = lib.getExe config.workstation.omp.package;
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
      default = inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system}.messaging.override {
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
      description = "Hermes intake model; OMP retains its own model role configuration.";
    };
    repositoryRoots = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "${home}/workspace" ];
      description = "Allowed canonical repository roots; not an OS sandbox.";
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
            PYTHONDONTWRITEBYTECODE = "1";
          }
          ''
            ${cfg.package.hermesVenv}/bin/python3 ${../scripts/hermes/check-runtime.py} \
              ${hermesConfig} ${pluginSource} ${lib.escapeShellArg cfg.package.version}
            touch "$out"
          '';
    };

    home-manager.users.${user} = { lib, ... }: {
      home = {
        file = {
          "${profilePath}/config.nix.yaml".source = hermesConfig;
          "${profilePath}/plugins/omp-acp-delegator".source = pluginSource;
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
