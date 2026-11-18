{
  config,
  lib,
  pkgs,
  ...
}:

let
  gnoRev = "fc79041f4cd1a7b3ed4b316dc5ac14162eb78730";
  gnoplsRev = "c06cbb3d2dc5dc986647340b97478ff176ab25e5";
  gnoHash = "sha256-ZVE987RY2t/BWK6dQn/cqS+wqO1LKXrtsb4G+JwxsWs=";
  gnoVendorHash = "sha256-SVNVLF7xTIeLzwOxNK6DaN23ccp36CoYY3w137PGIaQ=";
  gnoplsHash = "sha256-x8xEgj6YNnEpviw2vG5fQMh6wZw/JZKVNnkGI0XsAMg=";
  gnoplsVendorHash = "sha256-BD5lx+iTrj4GInH1gIyjj6B+DLPv3VGs5OpnvM0jFok=";

  gnoSource = pkgs.fetchFromGitHub {
    owner = "gnolang";
    repo = "gno";
    rev = gnoRev;
    hash = gnoHash;
  };
  gnoToolchain = pkgs.buildGoModule {
    pname = "gno-toolchain";
    version = "unstable-${builtins.substring 0 7 gnoRev}";
    src = gnoSource;
    # Compiler diagnostics may retain a relative path prefix; keep checks enabled.
    patches = [ ../../patches/gno/transpile-diagnostic-path.patch ];
    # Preserve the HID C sources used by gnokey's Ledger support.
    proxyVendor = true;
    vendorHash = gnoVendorHash;
    subPackages = [
      "gnovm/cmd/gno"
      "gno.land/cmd/gnokey"
    ];
    ldflags = [ "-X github.com/gnolang/gno/tm2/pkg/version.Version=${gnoRev}" ];
    # Upstream CLI tests expect the default development version in test binaries.
    checkFlags = [ "-ldflags=" ];
    nativeCheckInputs = [ pkgs.python3 ];
    preCheck = ''
      python3 -B ${../../scripts/validation/check-gno-transpile-fixture.py} \
        gnovm/cmd/gno/testdata/transpile/gobuild_flag_build_error.txtar
    '';
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postFixup = ''
      wrapProgram "$out/bin/gno" --set GNOROOT ${gnoSource}
    '';
  };
  gnopls = pkgs.buildGoModule {
    pname = "gnopls";
    version = "unstable-${builtins.substring 0 7 gnoplsRev}";
    src = pkgs.fetchFromGitHub {
      owner = "gnoverse";
      repo = "gnopls";
      rev = gnoplsRev;
      hash = gnoplsHash;
    };
    vendorHash = gnoplsVendorHash;
    subPackages = [ "." ];
    # Builtin initialization imports cmp through go/importer at runtime.
    allowGoReference = true;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postInstall = ''
      install -Dm444 pkg/gnotypes/builtin/builtin.gno "$out/share/gnopls/builtin/builtin.gno"
    '';
    postFixup = ''
      wrapProgram "$out/bin/gnopls" \
        --set GNOROOT ${gnoSource} \
        --set GNOBUILTIN "$out/share/gnopls/builtin"
    '';
    doInstallCheck = true;
    nativeInstallCheckInputs = [ pkgs.python3 ];
    installCheckPhase = ''
      runHook preInstallCheck
      python3 -B ${../../scripts/validation/check-gnopls.py} "$out/bin/gnopls"
      runHook postInstallCheck
    '';
  };
in
{
  options.workstation.languages.gno.enable = lib.mkEnableOption "the Gno toolchain";
  config = lib.mkIf config.workstation.languages.gno.enable {
    environment.systemPackages = [
      gnoToolchain
      gnopls
    ];
  };
}
