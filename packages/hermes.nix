{
  stdenvNoCC,
  fetchurl,
  unzip,
}:
let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).hermes;
in
stdenvNoCC.mkDerivation {
  pname = "hermes";
  inherit (release) version;

  src = fetchurl { inherit (release) url hash; };
  nativeBuildInputs = [ unzip ];
  sourceRoot = ".";
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/Applications" "$out/bin"
    cp -R "Hermes Agent.app" "$out/Applications/"
    ln -s "$out/Applications/Hermes Agent.app/Contents/Resources/agent-payload/bin/hermes" "$out/bin/hermes"
    runHook postInstall
  '';

  dontPatchShebangs = true;
  dontStrip = true;

  meta = {
    description = "Hermes Agent with its bundled runtime";
    mainProgram = "hermes";
    platforms = [ "aarch64-darwin" ];
  };
}
