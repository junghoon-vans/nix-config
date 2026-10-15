{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.omp;
  ompRelease = (builtins.fromJSON (builtins.readFile ../release-pins.json)).omp;
  omp = pkgs.stdenvNoCC.mkDerivation {
    pname = "omp";
    inherit (ompRelease) version;
    src = pkgs.fetchurl {
      url = "https://github.com/can1357/oh-my-pi/releases/download/v${ompRelease.version}/omp-darwin-arm64";
      inherit (ompRelease) hash;
    };
    dontUnpack = true;
    meta.mainProgram = "omp";
    installPhase = ''
      install -Dm755 "$src" "$out/bin/omp"
    '';
  };
in
{
  options.workstation.omp = {
    enable = lib.mkEnableOption "Oh My Pi";
    package = lib.mkOption {
      type = lib.types.package;
      default = omp;
      description = "Pinned OMP executable shared by interactive and ACP sessions.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
  };
}
