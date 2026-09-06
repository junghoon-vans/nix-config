{ inputs, pkgs, ... }:

let
  user = {
    name = "junghoon";
    homeDirectory = "/Users/junghoon";
  };
in
{
  imports = [
    ../../modules/darwin.nix
    ../../modules/languages
    ../../modules/omp.nix
    ../../modules/maintenance.nix
  ];

  nixpkgs.hostPlatform = "aarch64-darwin";
  nix.enable = false;

  workstation.languages = {
    gno.enable = true;
    go.enable = true;
    node.enable = true;
    typescript.enable = true;
    python.enable = true;
    rust.enable = true;
    java.enable = true;
    kotlin.enable = true;
    bun.enable = true;
    xml.enable = true;
  };

  workstation.omp.enable = true;

  users.users.${user.name}.home = user.homeDirectory;

  nix-homebrew = {
    enable = true;
    enableRosetta = true;
    autoMigrate = true;
    user = user.name;
    mutableTaps = true;
    taps = {
      "homebrew/homebrew-core" = inputs.homebrew-core;
      "homebrew/homebrew-cask" = inputs.homebrew-cask;
      "microsoft/homebrew-apm" = inputs.homebrew-microsoft-apm;
      "tw93/homebrew-tap" = inputs.homebrew-tw93;
    };
  };

  home-manager = {
    backupFileExtension = "pre-nix";
    useGlobalPkgs = true;
    useUserPackages = true;
    extraSpecialArgs = {
      inherit inputs;
      workstationUser = user;
    };
    users.${user.name} = import ../../modules/home-manager.nix;
  };

  system = {
    primaryUser = user.name;
    configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;
    stateVersion = 6;
  };
}
