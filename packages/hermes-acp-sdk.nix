{
  pkgs,
  upstreamCallPackage,
  package,
  patch,
  pmPackages,
  version,
  extraDependencyGroups,
}:
let
  # Hermes exposes callPackage as an override but no pythonSrc hook. Keep its
  # upstream Nixpkgs scope and replace only python.nix's filtered source.
  callPackage =
    path: args:
    upstreamCallPackage path (
      if builtins.baseNameOf (toString path) == "python.nix" then
        args
        // {
          pythonSrc = pkgs.applyPatches {
            name = "hermes-agent-python-acp-0.10.1";
            src = args.pythonSrc;
            patches = [ patch ];
          };
        }
      else
        args
    );
in
package.override {
  inherit
    callPackage
    pmPackages
    version
    extraDependencyGroups
    ;
}
