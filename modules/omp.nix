{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.omp;
  bootstrapOmp = pkgs.writeShellApplication {
    name = "bootstrap-omp";
    runtimeInputs = [ pkgs.bun pkgs.coreutils ];
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

      export BUN_INSTALL="$HOME/.bun"
      export PATH="$BUN_INSTALL/bin:$PATH"
      bun install --global "@oh-my-pi/pi-coding-agent@${cfg.version}"
      omp --version
      (
        cd "$repository_root"
        apm install --global --target agent-skills --only apm .
      )
    '';
  };
in
{
  options.workstation.omp = {
    enable = lib.mkEnableOption "the Oh My Pi bootstrap command";
    version = lib.mkOption {
      type = lib.types.str;
      default = "18.1.11";
      description = "Pinned Oh My Pi package version.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ bootstrapOmp ];
  };
}
