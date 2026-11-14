{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.ego;
  egoLite = pkgs.callPackage ../packages/ego-lite.nix { };
in
{
  options.workstation.ego = {
    enable = lib.mkEnableOption "Ego Lite browser and agent CLI";
    package = lib.mkOption {
      type = lib.types.package;
      default = egoLite;
      description = "CLI launcher for a separately installed Ego Lite app and pinned official browser skill.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    system.checks.text = lib.mkAfter ''
      ${pkgs.bash}/bin/bash ${../scripts/ego/check-migration.sh} \
        ${lib.escapeShellArg config.users.users.${config.system.primaryUser}.home} /Applications || exit 1
    '';
  };
}
