{
  config,
  lib,
  pkgs,
  ...
}:

let
  gnomcpVersion = "0.11.0";
  gnomcp = pkgs.stdenvNoCC.mkDerivation {
    pname = "gnomcp";
    version = gnomcpVersion;
    src = pkgs.fetchurl {
      url = "https://github.com/gnoverse/gno-mcp/releases/download/v${gnomcpVersion}/gno-mcp_darwin_arm64.tar.gz";
      hash = "sha256-BeGxpShCMJRfwEEnzfRxYcOY90v5n8W/j1l8JBh6SYU=";
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
