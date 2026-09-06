{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.kotlin;
in
{
  options.workstation.languages.kotlin.enable = lib.mkEnableOption "the Kotlin compiler";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.kotlin ];
  };
}
