{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.omp;
  omp = pkgs.stdenvNoCC.mkDerivation {
    pname = "omp";
    inherit (cfg) version;
    src = pkgs.fetchurl {
      url = "https://github.com/can1357/oh-my-pi/releases/download/v${cfg.version}/omp-darwin-arm64";
      hash = "sha256-qBsqmNmdWzRJHSUjICDVPLDlUmCV7yHEy51Cg+ZRGAc=";
    };
    dontUnpack = true;
    installPhase = ''
      install -Dm755 "$src" "$out/bin/omp"
    '';
  };
  bootstrapAgentSkills = pkgs.writeShellApplication {
    name = "bootstrap-agent-skills";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      repository_root="''${1:-$PWD}"
      manifest="$repository_root/apm.yml"

      [[ -f "$manifest" ]] || {
        echo "apm.yml not found in $repository_root" >&2
        exit 1
      }
      command -v apm >/dev/null || {
        echo "APM is not installed; apply the Nix configuration first." >&2
        exit 1
      }

      mkdir -p "$HOME/.apm"
      cp "$manifest" "$HOME/.apm/apm.yml"
      apm install --global --target agent-skills --only apm
    '';
  };
in
{
  options.workstation.omp = {
    enable = lib.mkEnableOption "Oh My Pi";
    version = lib.mkOption {
      type = lib.types.str;
      default = "18.1.11";
      description = "Pinned Oh My Pi release version.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      omp
      bootstrapAgentSkills
    ];
  };
}
