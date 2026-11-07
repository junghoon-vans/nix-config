{
  lib,
  stdenvNoCC,
  fetchurl,
  undmg,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).openmarket;
in
stdenvNoCC.mkDerivation {
  pname = "openmarket";
  inherit (release) version;

  src = fetchurl {
    url = "https://assets.openmarket.xyz/desktop/stable/OpenMarket-${release.version}-mac-arm64.dmg";
    inherit (release) hash;
  };

  nativeBuildInputs = [ undmg ];
  sourceRoot = ".";

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/Applications"
    cp -R OpenMarket.app "$out/Applications/"
    runHook postInstall
  '';

  # Preserve the upstream Developer ID signature and notarization ticket.
  dontFixup = true;

  meta = {
    description = "Market charting and trading desktop app with an AI agent";
    homepage = "https://openmarket.xyz/download";
    license = lib.licenses.unfree;
    platforms = [ "aarch64-darwin" ];
  };
}
