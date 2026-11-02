{
  lib,
  stdenv,
  rcodesign,
  profileName,
}:

stdenv.mkDerivation {
  pname = "hermes-gateway-app-${profileName}";
  version = "1";
  src = ../scripts/hermes/gateway-host.c;

  dontUnpack = true;
  dontConfigure = true;
  dontBuild = true;
  dontFixup = true;

  nativeBuildInputs = [ rcodesign ];

  installPhase = ''
    runHook preInstall
    ${stdenv.shell} ${../scripts/hermes/build-gateway-app.sh} \
      "$src" "$out" ${lib.escapeShellArg profileName} "$CC" \
      ${lib.escapeShellArg (lib.getExe rcodesign)}
    runHook postInstall
  '';

  meta = {
    description = "Ad-hoc signed Hermes gateway supervisor app for ${profileName}";
    platforms = [ "aarch64-darwin" ];
  };
}
