{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.languages.typescript;
in
{
  options.workstation.languages.typescript.enable =
    lib.mkEnableOption "the TypeScript compiler and language server";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = with pkgs; [
      typescript
      typescript-language-server
      biome
    ];
  };
}
