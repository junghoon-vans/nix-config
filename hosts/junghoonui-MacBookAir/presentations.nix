{ lib, pkgs, ... }:

let
  braveExecutable = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
  braveLauncher = pkgs.writeShellApplication {
    name = "officecli-brave-browser";
    text = ''
      exec ${python}/bin/python3 ${../../scripts/presentations/brave_cli.py} ${lib.escapeShellArg braveExecutable} "$@"
    '';
  };
  officecli = pkgs.callPackage ../../packages/officecli.nix { inherit braveLauncher; };
  python = pkgs.python3.withPackages (ps: [
    ps.pillow
    ps.playwright
  ]);
  render = pkgs.writeShellApplication {
    name = "render-presentation";
    runtimeInputs = [ officecli ];
    text = ''
      exec ${python}/bin/python3 ${../../scripts/presentations/render.py} ${lib.escapeShellArg braveExecutable} "$@"
    '';
  };
in
{
  homebrew.casks = [ "brave-browser" ];
  environment.systemPackages = [
    officecli
    render
  ];
  home-manager.users.junghoon.home.file = {
    # Replace the manually installed binary that precedes system packages on PATH.
    ".local/bin/officecli".source = "${officecli}/bin/officecli";
    # Nix owns this skill; it is not part of the shared APM manifest.
    ".agents/skills/officecli/SKILL.md".source = "${officecli}/share/officecli/SKILL.md";
  };
}
