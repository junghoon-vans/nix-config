{
  config,
  lib,
  pkgs,
  ...
}:

let
  gnomcpRelease = (builtins.fromJSON (builtins.readFile ../../release-pins.json)).gnomcp;
  gnomcp = pkgs.stdenvNoCC.mkDerivation {
    pname = "gnomcp";
    inherit (gnomcpRelease) version;
    src = pkgs.fetchurl {
      url = "https://github.com/gnoverse/gno-mcp/releases/download/v${gnomcpRelease.version}/gno-mcp_darwin_arm64.tar.gz";
      inherit (gnomcpRelease) hash;
    };
    unpackPhase = "tar -xzf $src";
    installPhase = ''
      install -Dm755 gnomcp "$out/bin/gnomcp"
    '';
  };
in
{
  options.workstation.mcp.gnomcp.enable = lib.mkEnableOption "the Gno MCP server";

  config = lib.mkIf config.workstation.mcp.gnomcp.enable {
    environment.systemPackages = [ gnomcp ];
  };
}
