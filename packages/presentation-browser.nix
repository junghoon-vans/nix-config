{
  lib,
  stdenvNoCC,
  fetchzip,
  makeWrapper,
}:

stdenvNoCC.mkDerivation {
  pname = "presentation-browser";
  version = "155.0.8059.39";
  src = fetchzip {
    url = "https://storage.googleapis.com/chrome-for-testing-public/155.0.8059.39/mac-arm64/chrome-headless-shell-mac-arm64.zip";
    hash = "sha256-PlTFR9KZgyCxPE3eM/aTk6ApfaWak3SSdSZGM7QKcWU=";
  };
  nativeBuildInputs = [ makeWrapper ];
  installPhase = ''
    mkdir -p "$out/lib" "$out/bin"
    cp -R . "$out/lib/chrome-headless-shell"
    makeWrapper "$out/lib/chrome-headless-shell/chrome-headless-shell" "$out/bin/chromium"
  '';
  dontFixup = true;
  meta = {
    description = "Pinned Chrome headless shell for OfficeCLI presentation rendering";
    homepage = "https://googlechromelabs.github.io/chrome-for-testing/";
    license = lib.licenses.bsd3;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "chromium";
  };
}
