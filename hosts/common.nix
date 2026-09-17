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
    enableRosetta = true;
    autoMigrate = true;
    user = user.username;
    mutableTaps = true;
    taps = {
      "homebrew/homebrew-core" = inputs.homebrew-core;
      "homebrew/homebrew-cask" = inputs.homebrew-cask;
      "tw93/homebrew-tap" = inputs.homebrew-tw93;
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
