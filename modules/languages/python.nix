{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.python;
in
{
  options.workstation.languages.python.enable = lib.mkEnableOption "the Python runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.python313 ];
  };
}
