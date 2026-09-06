{
  description = "Junghoon's declarative macOS workstation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nix-darwin.url = "github:nix-darwin/nix-darwin/master";
    nix-darwin.inputs.nixpkgs.follows = "nixpkgs";
    home-manager.url = "github:nix-community/home-manager/master";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    nix-homebrew.url = "github:zhaofengli/nix-homebrew";

    oh-my-zsh = {
      url = "github:ohmyzsh/ohmyzsh";
      flake = false;
    };
    spaceship-prompt = {
      url = "github:spaceship-prompt/spaceship-prompt";
      flake = false;
    };
    zsh-autosuggestions = {
      url = "github:zsh-users/zsh-autosuggestions";
      flake = false;
    };
    zsh-completions = {
      url = "github:zsh-users/zsh-completions";
      flake = false;
    };
    zsh-hangul = {
      url = "github:gomjellie/zsh-hangul";
      flake = false;
    };
    zsh-syntax-highlighting = {
      url = "github:zsh-users/zsh-syntax-highlighting";
      flake = false;
    };

    homebrew-core = {
      url = "github:homebrew/homebrew-core";
      flake = false;
    };
    homebrew-cask = {
      url = "github:homebrew/homebrew-cask";
      flake = false;
    };

    homebrew-microsoft-apm = {
      url = "github:microsoft/homebrew-apm";
      flake = false;
    };
    homebrew-tw93 = {
      url = "github:tw93/homebrew-tap";
      flake = false;
    };
  };

  outputs = inputs@{ self, nix-darwin, home-manager, nix-homebrew, ... }:
    {
      darwinConfigurations."junghoonui-MacBookAir" = nix-darwin.lib.darwinSystem {
        specialArgs = { inherit inputs; };
        modules = [
          nix-homebrew.darwinModules.nix-homebrew
          home-manager.darwinModules.home-manager
          ./hosts/junghoonui-MacBookAir
        ];
      };
    };
}
