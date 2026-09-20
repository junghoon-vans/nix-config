{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.languages.bun;
  bunRelease = (builtins.fromJSON (builtins.readFile ../../release-pins.json)).bun;

  bun = pkgs.stdenvNoCC.mkDerivation {
    pname = "bun";
    inherit (bunRelease) version;

    src = pkgs.fetchzip {
      url = "https://github.com/oven-sh/bun/releases/download/bun-v${bunRelease.version}/bun-darwin-aarch64.zip";
      inherit (bunRelease) hash;
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
