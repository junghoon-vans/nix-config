{
  config,
  lib,
  pkgs,
  ...
}:

let
  setupApm = pkgs.writeShellApplication {
    name = "setup-apm";
    runtimeInputs = [ pkgs.coreutils ];
    text = builtins.readFile ../scripts/apm/setup-apm.sh;
  };
in
{
  options.workstation.apm.enable = lib.mkEnableOption "APM dependency deployment";
  config = lib.mkIf config.workstation.apm.enable {
    environment.systemPackages = [ setupApm ];
  };
}
