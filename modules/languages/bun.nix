{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.languages.bun;
  bunVersion = "1.4.2";

  bun = pkgs.stdenvNoCC.mkDerivation {
    pname = "bun";
    version = bunVersion;

    src = pkgs.fetchzip {
      url = "https://github.com/oven-sh/bun/releases/download/bun-v${bunVersion}/bun-darwin-aarch64.zip";
      hash = "sha256-Izz/X4ccPjHW7sXmYK7wPMOZLXxCMxyPcruhpjiK+k0=";
      stripRoot = false;
    };

    installPhase = ''
      install -Dm755 bun-darwin-aarch64/bun "$out/bin/bun"
    '';
  };
in
{
  options.workstation.languages.bun = {
    enable = lib.mkEnableOption "the Bun runtime";
    package = lib.mkOption {
      type = lib.types.package;
      internal = true;
      readOnly = true;
    };
  };

  config = {
    workstation.languages.bun.package = bun;
    environment.systemPackages = lib.optional cfg.enable bun;
  };
}
