{ ... }:

{
  imports = [ ../common.nix ];

  homebrew.casks = [
    "displaylink"
    "logi-options+"
  ];

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
}
