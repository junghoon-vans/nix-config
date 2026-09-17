{ ... }:

{
  imports = [ ../common.nix ];

  workstation.languages = {
    gno.enable = true;
    go.enable = true;
    node.enable = true;
    typescript.enable = true;
    python.enable = true;
    rust.enable = true;
    bun.enable = true;
    xml.enable = true;
  };
}
