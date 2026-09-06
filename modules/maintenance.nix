{ config, ... }:

let
  userHome = config.users.users.${config.system.primaryUser}.home;
in
{
  launchd.agents.weekly-disk-maintenance = {
    serviceConfig = {
      Label = "com.nix-workstation.weekly-disk-maintenance";
      ProgramArguments = [ "${userHome}/.local/bin/weekly-disk-maintenance" ];
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
}
