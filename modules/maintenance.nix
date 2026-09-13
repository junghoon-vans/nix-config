{ config, lib, ... }:

let
  cfg = config.workstation.maintenance;
  userHome = config.users.users.${config.system.primaryUser}.home;
in
{
  options.workstation.maintenance = {
    enable = lib.mkEnableOption "the weekly disk-maintenance LaunchAgent";
    mole.enable = lib.mkEnableOption "Mole cleanup during weekly disk maintenance";
    dockerPrune.enable = lib.mkEnableOption "Docker prune during weekly disk maintenance";
  };

  config = lib.mkIf cfg.enable {
    launchd.agents.weekly-disk-maintenance = {
      serviceConfig = {
        Label = "com.nix-workstation.weekly-disk-maintenance";
        ProgramArguments = [
          "${userHome}/.local/bin/weekly-disk-maintenance"
        ]
        ++ lib.optionals cfg.mole.enable [ "--mole-clean" ]
        ++ lib.optionals cfg.dockerPrune.enable [ "--docker-prune" ];
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
  };
}
