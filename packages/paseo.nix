{
  stdenvNoCC,
  fetchurl,
  runtimeShell,
  undmg,
}:

let
  release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).paseo;
in

stdenvNoCC.mkDerivation {
  pname = "paseo";
  inherit (release) version;

  src = fetchurl {
    url = "https://github.com/getpaseo/paseo/releases/download/v${release.version}/Paseo-${release.version}-arm64.dmg";
    inherit (release) hash;
  };

  nativeBuildInputs = [ undmg ];
  sourceRoot = ".";

  installPhase = ''
    mkdir -p "$out/Applications" "$out/bin"
    cp -R Paseo.app "$out/Applications/"
    cat > "$out/bin/paseo" <<EOF
    #!${runtimeShell}
    exec "$out/Applications/Paseo.app/Contents/Resources/bin/paseo" "\$@"
    EOF
    chmod +x "$out/bin/paseo"
  '';

  dontPatchShebangs = true;
  dontStrip = true;
}
