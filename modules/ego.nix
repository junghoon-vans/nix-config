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
      description = "Pinned Ego Lite app, CLI, and official browser skill.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
  };
}
