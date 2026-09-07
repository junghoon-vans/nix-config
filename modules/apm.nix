{
  config,
  lib,
  pkgs,
  ...
}:

let
  bootstrapAgentSkills = pkgs.writeShellApplication {
    name = "bootstrap-agent-skills";
    runtimeInputs = [ pkgs.coreutils ];
    text = builtins.readFile ../scripts/apm/bootstrap-agent-skills.sh;
  };
in
{
  options.workstation.apm.enable = lib.mkEnableOption "APM dependency deployment";
  config = lib.mkIf config.workstation.apm.enable {
    environment.systemPackages = [ bootstrapAgentSkills ];
  };
}
