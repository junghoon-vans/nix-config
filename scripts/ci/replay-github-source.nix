{ sourcePath, archivePath }:
packages:
let
  values = if builtins.isList packages then packages else [ packages ];
  package = builtins.head (
    builtins.filter (
      package: (package.src or null) != null && toString package.src == sourcePath
    ) values
  );
in
(package.src.overrideAttrs (_: {
  urls = [ ("file://" + builtins.storePath archivePath) ];
})).drvPath
