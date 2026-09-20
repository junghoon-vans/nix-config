{ stdenvNoCC, fetchurl }:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).apm;
in

stdenvNoCC.mkDerivation {
  pname = "apm";
  inherit (release) version;

  src = fetchurl {
    url = "https://github.com/microsoft/apm/releases/download/v${release.version}/apm-darwin-arm64.tar.gz";
    inherit (release) hash;
  };

  unpackPhase = "tar -xzf $src";

  installPhase = builtins.readFile ../scripts/apm/install.sh;

  dontStrip = true;
}
