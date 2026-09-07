{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.workstation.languages.rust;
in
{
  options.workstation.languages.rust.enable = lib.mkEnableOption "the Rust runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = with pkgs; [
      cargo
      rustc
      rustfmt
      clippy
      rust-analyzer
      cargo-nextest
    ];
  };
}
