{ pkgs }:
pkgs.writeShellApplication {
  name = "aside";
  text = ''
    exec "$HOME/.aside/cli/Aside CLI.app/Contents/MacOS/aside" "$@"
  '';
}
