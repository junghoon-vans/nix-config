{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.go;
in
{
  options.workstation.languages.go.enable = lib.mkEnableOption "the Go runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.go_1_25 ];
  };
}
