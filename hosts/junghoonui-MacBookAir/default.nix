{ inputs, pkgs, ... }:

{
  imports = [
    ../../modules/darwin.nix
    ../../modules/maintenance.nix
  ];

  nixpkgs.hostPlatform = "aarch64-darwin";
  nix.settings.experimental-features = "nix-command flakes";

  users.users.junghoon = {
    name = "junghoon";
    home = "/Users/junghoon";
  };

  nix-homebrew = {
    enable = true;
    enableRosetta = true;
    autoMigrate = true;
    user = "junghoon";
    mutableTaps = false;
    taps = {
      "homebrew/homebrew-core" = inputs.homebrew-core;
      "homebrew/homebrew-cask" = inputs.homebrew-cask;
      "microsoft/homebrew-apm" = inputs.homebrew-microsoft-apm;
      "tw93/homebrew-tap" = inputs.homebrew-tw93;
    };
  };

  home-manager = {
    useGlobalPkgs = true;
    useUserPackages = true;
    extraSpecialArgs = { inherit inputs; };
    users.junghoon = import ../../modules/home-manager.nix;
  };

  system.primaryUser = "junghoon";

  system.configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;
  system.stateVersion = 6;
}
