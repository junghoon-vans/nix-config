flake:
let
  lib = flake.inputs.nixpkgs.lib;
  hosts = builtins.attrValues flake.darwinConfigurations;
  names =
    option:
    lib.unique (lib.concatMap (host: map (item: item.name) host.config.homebrew.${option}) hosts);
in
{
  homebrew-core = builtins.filter (name: !lib.hasPrefix "hashicorp/tap/" name) (names "brews");
  homebrew-cask = names "casks";
  hashicorp-tap = map (lib.removePrefix "hashicorp/tap/") (
    builtins.filter (lib.hasPrefix "hashicorp/tap/") (names "brews")
  );
}
