{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.node;
in
{
  options.workstation.languages.node.enable = lib.mkEnableOption "the Node.js runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.nodejs_24 ];
  };
}
