{
  description = "Junghoon's declarative macOS workstation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nix-darwin.url = "github:nix-darwin/nix-darwin/master";
    nix-darwin.inputs.nixpkgs.follows = "nixpkgs";
    home-manager.url = "github:nix-community/home-manager/master";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
    nix-homebrew.inputs.brew-src.url = "github:Homebrew/brew/7.0.11";
    hermes-agent.url = "github:NousResearch/hermes-agent/v0.22.5";
    hermes-omp-acp = {
      url = "github:junghoon-vans/hermes-omp-acp/v0.3.0";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    hermes-official-plugins = {
      url = "github:NousResearch/hermes-official-plugins/e404b6816b20237a82f6fbe2749b5a576cf75dba";
      flake = false;
    };
    protobuf36 = {
      url = "github:protocolbuffers/protobuf/v36.2";
      flake = false;
    };

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

    zed-gno = {
      url = "github:julienrbrt/zed-gno";
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
    hashicorp-tap = {
      url = "github:hashicorp/homebrew-tap";
      flake = false;
    };
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      nix-darwin,
      home-manager,
      nix-homebrew,
      ...
    }:
    let
      system = "aarch64-darwin";
      pkgs = nixpkgs.legacyPackages.${system};
      brewVersion = (builtins.fromJSON (builtins.readFile ./flake.lock)).nodes.brew-src.original.ref;
      homebrewPackage = pkgs.callPackage ./packages/homebrew.nix {
        source = inputs.nix-homebrew.inputs.brew-src;
        version = brewVersion;
      };
      homebrewSource = {
        nix-homebrew.package = homebrewPackage;
        nix-homebrew.patchBrew = false;
      };
    in
    {
      packages.${system} = {
        homebrew = homebrewPackage;
        apm = pkgs.callPackage ./packages/apm.nix { };
        kakaotalk-patcher = pkgs.callPackage ./packages/kakaotalk-patcher.nix { };
      };
      formatter.${system} = pkgs.writeShellApplication {
        name = "nixfmt-all";
        runtimeInputs = [
          pkgs.git
          pkgs.nixfmt
        ];
        text = ''
          git ls-files -z -- '*.nix' |
            while IFS= read -r -d "" file; do
              nixfmt "$file"
            done
        '';
      };
      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          deadnix
          nixfmt
          (python3.withPackages (ps: [
            ps.packaging
            ps.pyyaml
            ps.python-dotenv
          ]))
          shellcheck
          statix
        ];
      };

      darwinConfigurations = {
        "junghoonui-MacBookAir" = nix-darwin.lib.darwinSystem {
          specialArgs = { inherit inputs; };
          modules = [
            nix-homebrew.darwinModules.nix-homebrew
            homebrewSource
            home-manager.darwinModules.home-manager
            ./hosts/junghoonui-MacBookAir
          ];
        };

        "junghoonui-MacBookPro" = nix-darwin.lib.darwinSystem {
          specialArgs = { inherit inputs; };
          modules = [
            nix-homebrew.darwinModules.nix-homebrew
            homebrewSource
            home-manager.darwinModules.home-manager
            ./hosts/junghoonui-MacBookPro
          ];
        };
      };
    };
}
