{
  lib,
  stdenvNoCC,
  fetchurl,
  makeWrapper,
  browser,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).officecli;
  skill = fetchurl {
    url = "https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/v${release.version}/skills/officecli/SKILL.md";
    hash = release.skillHash;
  };
in
stdenvNoCC.mkDerivation {
  pname = "officecli";
  inherit (release) version;
  src = fetchurl {
    url = "https://github.com/iOfficeAI/OfficeCLI/releases/download/v${release.version}/officecli-mac-arm64";
    inherit (release) hash;
  };
  dontUnpack = true;
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    install -Dm755 "$src" "$out/libexec/officecli"
    install -Dm644 ${skill} "$out/share/officecli/SKILL.md"
    makeWrapper "$out/libexec/officecli" "$out/bin/officecli" --prefix PATH : ${lib.makeBinPath [ browser ]}
  '';
  # Preserve the upstream Mach-O signature.
  dontFixup = true;
  meta = {
    description = "Read, create, and edit Office documents from the command line";
    homepage = "https://github.com/iOfficeAI/OfficeCLI";
    license = lib.licenses.asl20;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "officecli";
  };
}
