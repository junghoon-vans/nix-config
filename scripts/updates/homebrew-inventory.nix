flake:
let
  lib = flake.inputs.nixpkgs.lib;
  hosts = builtins.attrValues flake.darwinConfigurations;
  names =
    option:
    lib.unique (lib.concatMap (host: map (item: item.name) host.config.homebrew.${option}) hosts);
in
{
  homebrew-core = names "brews";
  homebrew-cask = names "casks";
}
