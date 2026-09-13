{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.omp;
  ompRelease = {
    version = "18.1.19";
    hash = "sha256-3vwdOY1qkPNJmNUSD7W1PPeuCMEN/5G4NMq1o7BGERk=";
  };
  omp = pkgs.stdenvNoCC.mkDerivation {
    pname = "omp";
    inherit (ompRelease) version;
    src = pkgs.fetchurl {
      url = "https://github.com/can1357/oh-my-pi/releases/download/v${ompRelease.version}/omp-darwin-arm64";
      inherit (ompRelease) hash;
    };
    dontUnpack = true;
    installPhase = ''
      install -Dm755 "$src" "$out/bin/omp"
    '';
  };
in
{
  options.workstation.omp = {
    enable = lib.mkEnableOption "Oh My Pi";
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ omp ];
  };
}
