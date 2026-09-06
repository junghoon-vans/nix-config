{
  config,
  lib,
  pkgs,
  ...
}:

let
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
  options.workstation.apm.enable = lib.mkEnableOption "APM skill deployment";
  config = lib.mkIf config.workstation.apm.enable {
    environment.systemPackages = [ bootstrapAgentSkills ];
  };
}
