{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.bun;
in
{
  options.workstation.languages.bun.enable = lib.mkEnableOption "the Bun runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.bun ];
  };
}
