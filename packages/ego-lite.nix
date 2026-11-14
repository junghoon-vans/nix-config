{
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).egoLite;
  cliArchive = fetchurl {
    url = "https://github.com/citrolabs/ego-lite/releases/download/v${release.version}/ego-browser-v${release.version}.zip";
    inherit (release) hash;
  };
in
stdenvNoCC.mkDerivation {
  pname = "ego-lite";
  inherit (release) version;
  src = cliArchive;
  dontUnpack = true;
  nativeBuildInputs = [
    unzip
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/bin" "$out/share/ego-browser"
    mkdir -p "$TMPDIR/ego-lite-cli"
    unzip -q "$src" -d "$TMPDIR/ego-lite-cli"
    cp -R "$TMPDIR/ego-lite-cli/agent-skills/ego-browser/." "$out/share/ego-browser/"

    # The mutable, versionless GUI is installed separately, never fetched by a build.
    install -m755 ${../scripts/ego/ego-browser.sh} "$out/bin/ego-browser"
    substituteInPlace "$out/bin/ego-browser" --replace-fail '#!/usr/bin/env bash' '#!${stdenvNoCC.shell}'

    runHook postInstall
  '';

  meta = {
    description = "Ego Lite CLI launcher and pinned official browser skill";
    homepage = "https://lite.ego.app/";
    license = lib.licenses.mit;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "ego-browser";
  };
}
