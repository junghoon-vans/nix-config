{
  lib,
  stdenvNoCC,
  fetchurl,
  undmg,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).kiri;
in
stdenvNoCC.mkDerivation {
  pname = "kiri";
  inherit (release) version;

  src = fetchurl {
    url = "https://download.runkiri.com/Kiri-${release.version}-arm64.dmg";
    inherit (release) hash;
  };

  nativeBuildInputs = [ undmg ];
  sourceRoot = ".";

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/Applications"
    cp -R Kiri.app "$out/Applications/"
    runHook postInstall
  '';

  # Preserve the upstream signature; do not expose bundled Docker tools on PATH.
  dontFixup = true;

  meta = {
    description = "Lightweight Docker-compatible container runtime for macOS";
    homepage = "https://runkiri.com";
    license = lib.licenses.asl20;
    platforms = [ "aarch64-darwin" ];
  };
}
