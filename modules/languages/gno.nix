{
  config,
  lib,
  pkgs,
  ...
}:

let
  gnoRelease = "chain/pearl";
  gnoplsRev = "543a5cb1face8aeb9d947dc557995a8e4d4c311d";

  gnoSource = pkgs.fetchFromGitHub {
    owner = "gnolang";
    repo = "gno";
    rev = "c4c72fdd288c757e8da0d93aae867fa479b1b15c";
    hash = "sha256-nKEp6P1zeYMhmA9GeXsnhiyHsmPOlRZej3FjaROIFFM=";
  };
  gnoBinary = pkgs.fetchurl {
    url = "https://github.com/gnolang/gno/releases/download/${gnoRelease}/gno_darwin_arm64";
    hash = "sha256-rbMuvnFKNNlBWAix8u2j28oB4fqYk/E/HEa4U+Dcuzw=";
  };
  gnokeyBinary = pkgs.fetchurl {
    url = "https://github.com/gnolang/gno/releases/download/${gnoRelease}/gnokey_darwin_arm64";
    hash = "sha256-U++hTIQOvI9jJBSKg+WElHy2rxkmPIvgnfGodBW9EaQ=";
  };
  gnoToolchain = pkgs.stdenvNoCC.mkDerivation {
    pname = "gno-toolchain";
    version = lib.replaceStrings [ "/" ] [ "-" ] gnoRelease;
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      install -Dm755 ${gnoBinary} "$out/libexec/gno"
      install -Dm755 ${gnokeyBinary} "$out/libexec/gnokey"
      makeWrapper "$out/libexec/gno" "$out/bin/gno" --set GNOROOT ${gnoSource}
      makeWrapper "$out/libexec/gnokey" "$out/bin/gnokey"
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
