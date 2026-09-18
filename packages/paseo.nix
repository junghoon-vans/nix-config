{
  stdenvNoCC,
  fetchurl,
  runtimeShell,
  undmg,
}:

stdenvNoCC.mkDerivation {
  pname = "paseo";
  version = "0.8.0";

  src = fetchurl {
    url = "https://github.com/getpaseo/paseo/releases/download/v0.8.0/Paseo-0.8.0-arm64.dmg";
    hash = "sha256-9YgQFntZ6s6IqNo1Yp1cm5HmKTtCOct9GVSxOhq5UB4=";
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
