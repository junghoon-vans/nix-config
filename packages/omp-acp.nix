{
  lib,
  stdenvNoCC,
  makeWrapper,
  bun,
  nodejs,
  importNpmLock,
}:

let
  packageRoot = ../scripts/hermes/omp-acp;
  nodeModules = importNpmLock.buildNodeModules {
    npmRoot = packageRoot;
    inherit nodejs;
    derivationArgs.npmRebuildFlags = [ "--ignore-scripts" ];
  };
in
stdenvNoCC.mkDerivation {
  pname = "hermes-omp-acp";
  version = (lib.importJSON (packageRoot + "/package.json")).dependencies."@oh-my-pi/pi-coding-agent";
  src = packageRoot;
  dontUnpack = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall
    packageDir="$out/share/hermes-omp-acp"
    install -d "$packageDir"
    cp -R "$src"/. "$packageDir"/
    ln -s ${nodeModules}/node_modules "$packageDir/node_modules"
    makeWrapper ${lib.getExe' bun "bun"} "$out/bin/hermes-omp-acp" \
      --add-flags "$packageDir/agent.ts"
    runHook postInstall
  '';

  meta = {
    description = "Restricted OMP ACP server for Hermes";
    homepage = "https://github.com/can1357/oh-my-pi";
    license = lib.licenses.mit;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "hermes-omp-acp";
  };
}
