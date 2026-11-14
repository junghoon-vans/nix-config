{
  config,
  lib,
  pkgs,
  ...
}:

let
  gnoRev = "83431a7f0261882541a8a8dcf1643e6f246bbbe5";
  gnoplsRev = "c06cbb3d2dc5dc986647340b97478ff176ab25e5";
  gnoHash = "sha256-IlpJepk07XI10CP6z2PejmZ0qaFNWFGF0MjKfIBDUfM=";
  gnoVendorHash = "sha256-e1g2y3igU88Z6wkBC7+ab/cxj2Wx2Q2izz8ZDJWzuOQ=";
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
