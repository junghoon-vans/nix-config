{
  bash,
  gnugrep,
  lib,
  ruby_4_0,
  source,
  stdenvNoCC,
  version,
}:
let
  fiddle = ruby_4_0.gems.fiddle;
in
stdenvNoCC.mkDerivation {
  pname = "brew";
  name = "brew-${version}-patched";
  inherit version;
  src = source;
  dontUnpack = true;
  dontPatchShebangs = true;
  dontFixup = true;
  nativeBuildInputs = [
    bash
    gnugrep
  ];

  installPhase = ''
    runHook preInstall
    source ${../scripts/homebrew/patch-runtime.sh} \
      ${lib.escapeShellArg "${source}"} \
      "$out" \
      ${lib.escapeShellArg version} \
      ${lib.escapeShellArg "${ruby_4_0}/bin/ruby"} \
      ${lib.escapeShellArg "${fiddle}"} \
      ${lib.escapeShellArg ruby_4_0.gemPath} \
      ${lib.escapeShellArg fiddle.version}
    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    ${bash}/bin/bash ${../scripts/homebrew/check-runtime.sh} \
      "$out/bin/brew" \
      ${lib.escapeShellArg version} \
      ${lib.escapeShellArg "${ruby_4_0}/bin/ruby"} \
      ${lib.escapeShellArg "${fiddle}/${ruby_4_0.gemPath}/gems/fiddle-${fiddle.version}/lib"}
    runHook postInstallCheck
  '';

  meta.platforms = lib.platforms.darwin;
}
