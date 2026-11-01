{
  lib,
  stdenvNoCC,
  fetchFromGitHub,
  makeWrapper,
  python3,
}:

stdenvNoCC.mkDerivation {
  pname = "kakaotalk-patcher";
  version = "26.9.0-2006-5eb5519";
  src = fetchFromGitHub {
    owner = "betive37";
    repo = "mac-kakaotalk-adblock";
    rev = "5eb55199f3aa0c9680b8d080c7d5221a4725d627";
    hash = "sha256-DMZnS5sVRabiRJlz/liAHSxqDs9owq9A1DjlP99O4jM=";
  };
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    PYTHONPATH="$PWD:${../patches/kakaotalk}" ${python3}/bin/python3 -B ${../patches/kakaotalk/test_activate.py}
    PYTHONPATH="$PWD:${../patches/kakaotalk}" ${python3}/bin/python3 -B ${../patches/kakaotalk/test_patch_copy.py}
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    install -Dm644 patch_kakaotalk.py "$out/libexec/kakaotalk-patcher/patch_kakaotalk.py"
    install -Dm644 ${../patches/kakaotalk/activate.py} "$out/libexec/kakaotalk-patcher/activate.py"
    install -Dm644 ${../patches/kakaotalk/patch_copy.py} "$out/libexec/kakaotalk-patcher/patch_copy.py"
    install -Dm644 LICENSE "$out/share/licenses/kakaotalk-patcher/LICENSE"
    makeWrapper ${python3}/bin/python3 "$out/bin/kakaotalk-patcher" \
      --add-flags "-B -s $out/libexec/kakaotalk-patcher/patch_copy.py" \
      --set PYTHONPATH "$out/libexec/kakaotalk-patcher" \
      --prefix PATH : /usr/bin:/bin:/usr/sbin:/sbin
    makeWrapper ${python3}/bin/python3 "$out/bin/kakaotalk-activate" \
      --add-flags "-B -s $out/libexec/kakaotalk-patcher/activate.py" \
      --set PYTHONPATH "$out/libexec/kakaotalk-patcher" \
      --set NIX_KAKAOTALK_PATCHER_ID "$out" \
      --prefix PATH : /usr/bin:/bin:/usr/sbin:/sbin
    runHook postInstall
  '';
  meta = {
    description = "Validate and transactionally patch KakaoTalk during Darwin activation";
    homepage = "https://github.com/betive37/mac-kakaotalk-adblock";
    license = lib.licenses.mit;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "kakaotalk-patcher";
  };
}
