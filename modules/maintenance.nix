{ config, lib, ... }:

let
  cfg = config.workstation.maintenance;
  userHome = config.users.users.${config.system.primaryUser}.home;
  maintenanceEnvironment = {
    HOME = userHome;
    PATH = "${userHome}/.local/bin:/nix/var/nix/profiles/default/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
  };
in
{
  options.workstation.maintenance = {
    enable = lib.mkEnableOption "the weekly disk-maintenance LaunchAgent";
    mole.enable = lib.mkEnableOption "Mole cleanup during weekly disk maintenance";
    dockerPrune.enable = lib.mkEnableOption "daily cleanup of old unused Docker images and build cache";
    nixGc.enable = lib.mkEnableOption "weekly collection of unreferenced Nix store paths";
  };

  config = lib.mkIf cfg.enable {
    launchd.agents.weekly-disk-maintenance = {
      serviceConfig = {
        Label = "com.nix-workstation.weekly-disk-maintenance";
        ProgramArguments = [
          "${userHome}/.local/bin/weekly-disk-maintenance"
        ]
        ++ lib.optionals cfg.mole.enable [ "--mole-clean" ]
        ++ lib.optionals cfg.nixGc.enable [ "--nix-gc" ];
        EnvironmentVariables = maintenanceEnvironment;
        StartCalendarInterval = {
          Weekday = 1;
          Hour = 10;
          Minute = 0;
        };
        StandardOutPath = "${userHome}/Library/Logs/weekly-disk-maintenance.log";
        StandardErrorPath = "${userHome}/Library/Logs/weekly-disk-maintenance.error.log";
        ProcessType = "Background";
      };
    };

    launchd.agents.daily-docker-maintenance = lib.mkIf cfg.dockerPrune.enable {
      serviceConfig = {
        Label = "com.nix-workstation.daily-docker-maintenance";
        ProgramArguments = [
          "${userHome}/.local/bin/weekly-disk-maintenance"
          "--docker-prune"
        ];
        EnvironmentVariables = maintenanceEnvironment;
        StartCalendarInterval = {
          Hour = 10;
          Minute = 30;
        };
        StandardOutPath = "${userHome}/Library/Logs/daily-docker-maintenance.log";
        StandardErrorPath = "${userHome}/Library/Logs/daily-docker-maintenance.error.log";
        ProcessType = "Background";
      };
    };
  };
}
