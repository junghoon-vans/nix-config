{ inputs, ... }:

let
  user = {
    username = "junghoon";
    homeDirectory = "/Users/junghoon";
  };
in
{
  imports = [
    ../modules/darwin.nix
    ../modules/languages
    ../modules/omp.nix
    ../modules/mcp/gnomcp.nix
    ../modules/maintenance.nix
  ];

  nixpkgs.hostPlatform = "aarch64-darwin";
  # Home Manager docs include declaration paths from Nixpkgs modules. Link
  # those paths to the pinned source instead of serializing store paths.
  nixpkgs.overlays = [
    (final: prev: {
      nixosOptionsDoc =
        args:
        prev.nixosOptionsDoc (
          args
          // {
            transformOptions =
              option:
              let
                transformed = (args.transformOptions or final.lib.id) option;
                nixpkgsPath = "${toString inputs.nixpkgs.outPath}/";
              in
              transformed
              // {
                declarations = map (
                  declaration:
                  if final.lib.isAttrs declaration || !(final.lib.hasPrefix nixpkgsPath (toString declaration)) then
                    declaration
                  else
                    let
                      subpath = final.lib.removePrefix nixpkgsPath (toString declaration);
                    in
                    {
                      url = "https://github.com/NixOS/nixpkgs/blob/${inputs.nixpkgs.rev}/${subpath}";
                      name = "<nixpkgs/${subpath}>";
                    }
                ) transformed.declarations;
              };
          }
        );
    })
  ];

  nix.enable = false;

  security.pam.services.sudo_local.touchIdAuth = true;

  workstation = {
    omp.enable = true;
    mcp.gnomcp.enable = true;
    maintenance = {
      enable = true;
      mole.enable = true;
      dockerPrune.enable = true;
    };
  };

  users.users.${user.username}.home = user.homeDirectory;

  nix-homebrew = {
    enable = true;
    enableRosetta = false;
    autoMigrate = true;
    user = user.username;
    mutableTaps = true;
    taps = {
      "homebrew/homebrew-core" = inputs.homebrew-core;
      "homebrew/homebrew-cask" = inputs.homebrew-cask;
    };
  };

  home-manager = {
    useGlobalPkgs = true;
    useUserPackages = true;
    extraSpecialArgs = {
      inherit inputs;
      workstationUser = user;
    };
    users.${user.username} = import ../modules/home-manager.nix;
  };

  system = {
    primaryUser = user.username;
    configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;
    stateVersion = 6;
  };
}
