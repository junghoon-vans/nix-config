{
  lib,
  stdenvNoCC,
  fetchurl,
  makeWrapper,
  _7zz,
  unzip,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).egoLite;
  cliArchive = fetchurl {
    url = "https://github.com/citrolabs/ego-lite/releases/download/v${release.version}/ego-browser-v${release.version}.zip";
    inherit (release) hash;
  };
  appDiskImage = fetchurl {
    url = "https://cdn.ego.app/setup/macos/arm64/egolite-${release.appBuild}.dmg";
    hash = release.appHash;
  };
in
stdenvNoCC.mkDerivation {
  pname = "ego-lite";
  inherit (release) version;
  src = cliArchive;
  dontUnpack = true;
  nativeBuildInputs = [
    makeWrapper
    _7zz
    unzip
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/Applications" "$out/bin" "$out/share/ego-browser"
    mkdir -p "$TMPDIR/ego-lite-cli"
    unzip -q "$src" -d "$TMPDIR/ego-lite-cli"
    cp -R "$TMPDIR/ego-lite-cli/agent-skills/ego-browser/." "$out/share/ego-browser/"

    mkdir -p "$TMPDIR/ego-lite-app"
    # The hash-pinned official image contains signed-bundle links that use ../ within the app.
    # 7-Zip 25.01+ blocks those by default; -snld20 permits their extraction into this isolated staging directory.
    (cd "$TMPDIR/ego-lite-app" && ${lib.getExe _7zz} x -bso0 -bsp0 -snld20 -y "${appDiskImage}")
    cp -R "$TMPDIR/ego-lite-app/ego lite/ego lite.app" "$out/Applications/ego lite.app"
    appCli="$out/Applications/ego lite.app/Contents/Frameworks/ego Framework.framework/Versions/Current/Helpers/ego-browser"
    test -x "$appCli"
    makeWrapper "$appCli" "$out/bin/ego-browser"

    runHook postInstall
  '';

  # Do not strip or rewrite Mach-O files in the signed upstream app bundle.
  dontFixup = true;

  meta = {
    description = "Chromium browser for AI-agent automation with the ego-browser CLI";
    homepage = "https://lite.ego.app/";
    # The CLI and skill are MIT-licensed upstream; the separately distributed app is not open source.
    license = [
      lib.licenses.mit
      lib.licenses.unfree
    ];
    platforms = [ "aarch64-darwin" ];
    mainProgram = "ego-browser";
  };
}
