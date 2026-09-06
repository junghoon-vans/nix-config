{ config, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.gno;
  bootstrapGno = pkgs.writeShellApplication {
    name = "bootstrap-gno";
    runtimeInputs = [ pkgs.curl pkgs.git pkgs.go_1_25 pkgs.gnugrep ];
    text = ''
      release="chain/pearl"
      revision="c4c72fdd288c757e8da0d93aae867fa479b1b15c"
      root="$HOME/.local/share/gno/$release"
      bin="$HOME/.local/bin"
      mkdir -p "$bin" "$(dirname "$root")"
      if [[ ! -d "$root/.git" ]]; then git clone https://github.com/gnolang/gno "$root"; fi
      git -C "$root" fetch --tags --prune origin
      git -C "$root" checkout --detach "$revision"
      curl -fsSL -o "$bin/gno" "https://github.com/gnolang/gno/releases/download/$release/gno_darwin_arm64"
      curl -fsSL -o "$bin/gnokey" "https://github.com/gnolang/gno/releases/download/$release/gnokey_darwin_arm64"
      echo "adb32ebe714a34d9415808b1f2eda3dbca01e1fa9893f13f1c46b853e0dcbb3c  $bin/gno" | shasum -a 256 -c -
      echo "53efa14c840ebc8f6324148a83e584947cb6af19263c8be09df1a87415bd11a4  $bin/gnokey" | shasum -a 256 -c -
      chmod 755 "$bin/gno" "$bin/gnokey"
      GNOROOT="$root" GOBIN="$bin" go install github.com/gnoverse/gnopls@543a5cb1face8aeb9d947dc557995a8e4d4c311d
      GNOROOT="$root" "$bin/gno" version
      "$bin/gnopls" version
    '';
  };
in
{
  options.workstation.languages.gno.enable = lib.mkEnableOption "the Gno toolchain";
  config = lib.mkIf cfg.enable {
    assertions = [{ assertion = config.workstation.languages.go.enable; message = "Gno requires the Go language profile."; }];
    environment.systemPackages = [ bootstrapGno ];
  };
}
