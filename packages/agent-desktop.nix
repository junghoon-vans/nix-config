{
  lib,
  stdenvNoCC,
  fetchurl,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json))."agent-desktop";
in

stdenvNoCC.mkDerivation {
  pname = "agent-desktop";
  inherit (release) version;

  src = fetchurl {
    url = "https://github.com/vercel-labs/agent-desktop/releases/download/v${release.version}/agent-desktop-v${release.version}-aarch64-apple-darwin.tar.gz";
    inherit (release) hash;
  };

  unpackPhase = "tar -xzf $src";

  installPhase = ''
    install -Dm755 agent-desktop "$out/bin/agent-desktop"
    install -Dm755 agent-desktop-macos-helper "$out/bin/agent-desktop-macos-helper"
  '';

  # Keep both upstream Mach-O files unchanged; fixups could invalidate signatures.
  dontFixup = true;

  meta = {
    description = "Computer-use CLI for reading and operating desktop apps through accessibility APIs";
    homepage = "https://github.com/vercel-labs/agent-desktop";
    license = lib.licenses.asl20;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "agent-desktop";
  };
}
