{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.hermes;
  user = config.system.primaryUser;
  home = config.users.users.${user}.home;
  yaml = pkgs.formats.yaml { };
  workerConfig = pkgs.writeText "hermes-omp-worker.json" (
    builtins.toJSON {
      command = lib.getExe (
        pkgs.callPackage ../packages/omp-acp.nix {
          bun = config.workstation.languages.bun.package;
        }
      );
      approval_config = yaml.generate "hermes-omp-approval.yaml" {
        tools = {
          approvalMode = "always-ask";
          approval = {
            bash = "prompt";
            edit = "prompt";
            write = "prompt";
            lsp = "prompt";
          };
        };
      };
      git = lib.getExe pkgs.git;
      allowed_roots = cfg.repositoryRoots;
      state_dir = "${home}/.hermes/omp-worker";
      timeout = 1800;
    }
  );
  gatewayConfig = pkgs.writeText "hermes-gateway.json" (
    builtins.toJSON {
      hermes = "${cfg.installPrefix}/bin/hermes";
      expected_version = cfg.version;
      home = "${home}/.hermes";
      environment_file = "${home}/.hermes/.env";
      config_defaults = "${hermesConfig}";
      plugin_source = "${../scripts/hermes/omp-worker}";
    }
  );
  gateway = pkgs.writeShellScript "hermes-slack-gateway" ''
    export PATH=${
      lib.makeBinPath [
        pkgs.git
        config.workstation.omp.package
      ]
    }:/run/current-system/sw/bin:/etc/profiles/per-user/${user}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
    export OMP_WORKER_CONFIG=${workerConfig}
    export PYTHONDONTWRITEBYTECODE=1
    exec ${cfg.installPrefix}/libexec/bin/python ${../scripts/hermes/gateway.py} ${gatewayConfig} "$@"
  '';
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
      '';
    };
    platform_toolsets = {
      slack = [ "omp-worker" ];
      cli = [ "omp-worker" ];
    };
    platforms.slack = {
      enabled = true;
      reply_to_mode = "first";
      extra = {
        reply_in_thread = true;
        reply_broadcast = false;
      };
    };
    plugins.enabled = [ "omp-worker" ];
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
    installPrefix = lib.mkOption {
      type = lib.types.str;
      default = "/opt/homebrew/opt/hermes-agent";
      description = "Nix-declared Homebrew Hermes installation.";
    };
    version = lib.mkOption {
      type = lib.types.str;
      default = "0.21.0";
      description = "Required Hermes API version; refuse an incompatible Homebrew runtime.";
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
    assertions = [
      {
        assertion = config.workstation.omp.enable && cfg.repositoryRoots != [ ];
        message = "The Hermes gateway requires OMP and at least one repository root.";
      }
    ];
    system.build = {
      hermesGateway = gateway;
      inherit hermesConfig;
    };

    home-manager.users.${user} = { lib, ... }: {
      home = {
        file = {
          ".hermes/config.nix.yaml".source = hermesConfig;
          ".hermes/plugins/omp-worker".source = ../scripts/hermes/omp-worker;
        };
        activation = {
          prepareHermes =
            lib.hm.dag.entryBetween [ "linkGeneration" "setupLaunchAgents" ] [ "writeBoundary" ]
              ''
                run ${cfg.installPrefix}/libexec/bin/python ${../scripts/hermes/migrate.py} ${lib.escapeShellArg home}
              '';
          hermesResourcesReady = lib.hm.dag.entryBetween [ "setupLaunchAgents" ] [ "linkGeneration" ] ''
            run ${gateway} --check
          '';
        };
      };
      launchd.agents.hermes = {
        enable = true;
        config = {
          Label = "ai.hermes.gateway";
          ProgramArguments = [ "${gateway}" ];
          RunAtLoad = true;
          KeepAlive.SuccessfulExit = false;
          ThrottleInterval = 30;
          WorkingDirectory = home;
          StandardOutPath = "${home}/.hermes/logs/gateway.log";
          StandardErrorPath = "${home}/.hermes/logs/gateway.error.log";
          ProcessType = "Background";
          ExitTimeOut = 30;
        };
      };
    };
  };
}
