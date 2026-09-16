{ stdenvNoCC, fetchurl }:

stdenvNoCC.mkDerivation {
  pname = "apm";
  version = "0.31.0";

  src = fetchurl {
    url = "https://github.com/microsoft/apm/releases/download/v0.31.0/apm-darwin-arm64.tar.gz";
    hash = "sha256-O5hbpzVbPNkl/ThPQ699LUWRJUQx3yj10BY/FtOhPoE=";
  };

  unpackPhase = "tar -xzf $src";

  installPhase = builtins.readFile ../scripts/apm/install.sh;

  dontStrip = true;
}
