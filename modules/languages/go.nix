{ config, inputs, lib, pkgs, ... }:

let
  cfg = config.workstation.languages.go;
  protobuf36 = pkgs.stdenv.mkDerivation {
    pname = "protobuf";
    version = "36.0";
    src = inputs.protobuf36;
    nativeBuildInputs = [ pkgs.cmake pkgs.pkg-config ];
    buildInputs = [ pkgs.abseil-cpp ];
    cmakeFlags = [
      "-Dprotobuf_ABSL_PROVIDER=package"
      "-Dprotobuf_BUILD_LIBPROTOC=ON"
      "-Dprotobuf_BUILD_SHARED_LIBS=ON"
      "-Dprotobuf_BUILD_TESTS=OFF"
      "-Dprotobuf_FORCE_FETCH_DEPENDENCIES=OFF"
      "-Dprotobuf_INSTALL_EXAMPLES=ON"
      "-Dprotobuf_LOCAL_DEPENDENCIES_ONLY=ON"
    ];
  };
in
{
  options.workstation.languages.go.enable = lib.mkEnableOption "the Go runtime";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = with pkgs; [ go_1_25 gopls golangci-lint gofumpt protobuf36 ];
  };
}
