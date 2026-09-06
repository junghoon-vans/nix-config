{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.languages.xml;
in
{
  options.workstation.languages.xml.enable = lib.mkEnableOption "the XML language server";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.lemminx ];
  };
}
