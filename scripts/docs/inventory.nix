flake:
let
  lib = flake.inputs.nixpkgs.lib;
  root = toString flake.outPath + "/";
  owned = option: builtins.filter (def: lib.hasPrefix root def.file) option.definitionsWithLocations;
  source = def: lib.removePrefix root def.file;
  packages =
    host: manager: option:
    lib.concatMap (
      def:
      map (pkg: {
        inherit host manager;
        name = pkg.pname or (lib.getName pkg);
        description = pkg.meta.description or "";
        declaration = source def;
      }) def.value
    ) (owned option);
  brew =
    host: manager: option:
    lib.concatMap (
      def:
      map (item: {
        inherit host manager;
        name = if builtins.isString item then item else item.name;
        description = "";
        declaration = source def;
      }) def.value
    ) (owned option);
  inventory =
    host: original:
    let
      darwin = original.extendModules {
        modules = [
          {
            home-manager.sharedModules = [
              ({ options, ... }: {
                options.inventoryPackages = lib.mkOption {
                  type = lib.types.listOf lib.types.attrs;
                  internal = true;
                };
                config.inventoryPackages = packages host "Home Manager" options.home.packages;
              })
            ];
          }
        ];
      };
      inherit (darwin) options;
      homes = darwin.config.home-manager.users;
    in
    brew host "Homebrew cask" options.homebrew.casks
    ++ brew host "Homebrew formula" options.homebrew.brews
    ++ lib.concatMap (
      def:
      lib.mapAttrsToList (name: id: {
        inherit host name;
        manager = "Mac App Store";
        description = "App Store ID: ${toString id}";
        declaration = source def;
      }) def.value
    ) (owned options.homebrew.masApps)
    ++ packages host "Nix system" options.environment.systemPackages
    ++ lib.concatMap (user: homes.${user}.inventoryPackages) (builtins.attrNames homes);
in
lib.concatLists (lib.mapAttrsToList inventory flake.darwinConfigurations)
