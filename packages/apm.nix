{ stdenvNoCC, fetchurl }:

stdenvNoCC.mkDerivation {
  pname = "apm";
  version = "0.30.0";

  src = fetchurl {
    url = "https://github.com/microsoft/apm/releases/download/v0.30.0/apm-darwin-arm64.tar.gz";
    hash = "sha256-HL2P77tfdP0OBfGWu4HP887Ch2+PjhouRdS3j6Eno3w=";
  };

  unpackPhase = "tar -xzf $src";

  installPhase = builtins.readFile ../scripts/apm/install.sh;

  dontStrip = true;
}
