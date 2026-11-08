packages:
builtins.concatLists (
  map (
    package:
    let
      source = package.src or null;
      urls = if source == null then [ ] else source.urls or [ ];
      algorithm = source.outputHashAlgo or null;
    in
    if
      source != null
      && (source.outputHashMode or "") == "flat"
      && (source.postFetch or "") == ""
      && builtins.any (
        url: builtins.match "https://github.com/[^/]+/[^/]+/releases/download/.*" url != null
      ) urls
    then
      [
        {
          inherit (source) name;
          inherit urls;
          hash = source.outputHash;
          hashAlgo = if algorithm == null || algorithm == "" then "sha256" else algorithm;
          path = toString source;
        }
      ]
    else
      [ ]
  ) (if builtins.isList packages then packages else [ packages ])
)
