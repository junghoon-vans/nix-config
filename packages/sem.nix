{
  lib,
  stdenvNoCC,
  fetchurl,
  makeWrapper,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).sem;
  licenseFile = fetchurl {
    url = "https://raw.githubusercontent.com/Ataraxy-Labs/sem/v${release.version}/LICENSE-MIT";
    hash = release.licenseHash;
  };
in
stdenvNoCC.mkDerivation {
  pname = "sem";
  inherit (release) version;
  src = fetchurl {
    url = "https://github.com/Ataraxy-Labs/sem/releases/download/v${release.version}/sem-darwin-arm64.tar.gz";
    inherit (release) hash;
  };
  sourceRoot = ".";

  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    runHook preInstall
    install -Dm755 sem "$out/bin/sem"
    install -Dm644 ${licenseFile} "$out/share/licenses/sem/LICENSE-MIT"
    # Nix owns updates; upstream's network flag does not disable update checks.
    wrapProgram "$out/bin/sem" --set SEM_NO_UPDATE_CHECK 1
    runHook postInstall
  '';

  # Preserve the upstream Mach-O binary without stripping or rewriting it.
  dontFixup = true;

  meta = {
    description = "Semantic code discovery and Git diff CLI";
    homepage = "https://github.com/Ataraxy-Labs/sem";
    # Upstream offers MIT OR Apache-2.0; distribute under the MIT option.
    license = lib.licenses.mit;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "sem";
  };
}
