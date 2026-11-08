packages:
builtins.concatLists (
  map (
    package:
    let
      source = package.src or null;
      urls = builtins.filter (
        url:
        builtins.match "https://github.com/[^/]+/[^/]+/releases/download/.*" url != null
        || (
          (source.outputHashMode or null) == "recursive"
          && builtins.match "https://github.com/[^/]+/[^/]+/archive/.*(\\.tar\\.gz|\\.zip)" url != null
        )
      ) (if source == null then [ ] else source.urls or [ ]);
    in
    if source != null && (source.outputHash or null) != null && urls != [ ] then
      [
        {
          inherit (source) name;
          inherit urls;
          path = toString source;
        }
      ]
    else
      [ ]
  ) (if builtins.isList packages then packages else [ packages ])
)
