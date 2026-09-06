{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.bun;
  bun = pkgs.stdenvNoCC.mkDerivation {
    pname = "bun";
    version = "1.4.2";

    src = pkgs.fetchzip {
      url = "https://github.com/oven-sh/bun/releases/download/bun-v1.4.2/bun-darwin-aarch64.zip";
      hash = "sha256-Izz/X4ccPjHW7sXmYK7wPMOZLXxCMxyPcruhpjiK+k0=";
      stripRoot = false;
    };

    installPhase = ''
      install -Dm755 bun-darwin-aarch64/bun "$out/bin/bun"
    '';
  };
in
{
  options.workstation.languages.bun.enable = lib.mkEnableOption "the Bun runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ bun ];
  };
}
