{
  config,
  lib,
  pkgs,
  ...
}:

let
  gnoRev = "9c8eb132e483d6fd324d92c193e629ad65a98a37";
  gnoplsRev = "543a5cb1face8aeb9d947dc557995a8e4d4c311d";

  gnoSource = pkgs.fetchFromGitHub {
    owner = "gnolang";
    repo = "gno";
    rev = gnoRev;
    hash = "sha256-tJtZ44lilWSqW00Pzlar9xPQwjHF4t+gkrF4h8YW10I=";
  };
  gnoToolchain = pkgs.buildGoModule {
    pname = "gno-toolchain";
    version = "unstable-${builtins.substring 0 7 gnoRev}";
    src = gnoSource;
    # Preserve the HID C sources used by gnokey's Ledger support.
    proxyVendor = true;
    vendorHash = "sha256-e1g2y3igU88Z6wkBC7+ab/cxj2Wx2Q2izz8ZDJWzuOQ=";
    subPackages = [
      "gnovm/cmd/gno"
      "gno.land/cmd/gnokey"
    ];
    ldflags = [ "-X github.com/gnolang/gno/tm2/pkg/version.Version=${gnoRev}" ];
    # Upstream CLI tests expect the default development version in test binaries.
    checkFlags = [ "-ldflags=" ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postFixup = ''
      wrapProgram "$out/bin/gno" --set GNOROOT ${gnoSource}
    '';
  };
  gnopls = pkgs.buildGoModule {
    pname = "gnopls";
    version = "unstable-${builtins.substring 0 7 gnoplsRev}";
    src = pkgs.fetchFromGitHub {
      owner = "gnoverse";
      repo = "gnopls";
      rev = gnoplsRev;
      hash = "sha256-wFGv+UDI20XDwqjjYPLzvyZPSqziqXggpKRDYfpkM0M=";
    };
    vendorHash = "sha256-BD5lx+iTrj4GInH1gIyjj6B+DLPv3VGs5OpnvM0jFok=";
    subPackages = [ "." ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postFixup = ''
      wrapProgram "$out/bin/gnopls" --set GNOROOT ${gnoSource}
    '';
  };
in
{
  options.workstation.languages.gno.enable = lib.mkEnableOption "the Gno toolchain";
  config = lib.mkIf config.workstation.languages.gno.enable {
    environment.systemPackages = [
      gnoToolchain
      gnopls
    ];
  };
}
