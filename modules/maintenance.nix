{ ... }:

{
  launchd.agents.weekly-disk-maintenance = {
    serviceConfig = {
      Label = "com.dotfiles.weekly-disk-maintenance";
      ProgramArguments = [ "/Users/junghoon/.local/bin/weekly-disk-maintenance" ];
      StartCalendarInterval = {
        Weekday = 1;
        Hour = 10;
        Minute = 0;
      };
      StandardOutPath = "/Users/junghoon/Library/Logs/weekly-disk-maintenance.log";
      StandardErrorPath = "/Users/junghoon/Library/Logs/weekly-disk-maintenance.error.log";
      ProcessType = "Background";
    };
  };
}
