{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.java;
in
{
  options.workstation.languages.java.enable = lib.mkEnableOption "the Temurin Java runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.temurin-bin-25 ];
  };
}
