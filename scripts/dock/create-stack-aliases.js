ObjC.import("Foundation");

function run(argv) {
    var home = argv[0];
    var aliases = JSON.parse(argv[1]);
    var files = $.NSFileManager.defaultManager;

    function checked(success, error) {
        if (!success || (typeof success === "function" && success.isNil())) {
            throw new Error(ObjC.unwrap(error[0].localizedDescription));
        }
    }

    Object.keys(aliases).forEach(function (relativePath) {
        var targetPath = aliases[relativePath];
        if (!files.fileExistsAtPath(targetPath)) {
            console.log("Skipping Dock alias: missing " + targetPath);
            return;
        }

        var error = Ref();
        var target = $.NSURL.fileURLWithPath(targetPath);
        var bookmark = target.bookmarkDataWithOptionsIncludingResourceValuesForKeysRelativeToURLError(
            $.NSURLBookmarkCreationSuitableForBookmarkFile, $(), $(), error
        );
        checked(bookmark, error);

        var path = home + "/" + relativePath;
        var destination = $.NSURL.fileURLWithPath(path);
        checked(files.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(
            ObjC.unwrap(destination.URLByDeletingLastPathComponent.path), true, $(), error
        ), error);

        // Preserve collisions, including broken symlinks. Home Manager normally
        // removes its old store-backed links before this activation entry runs.
        var attributes = files.attributesOfItemAtPathError(path, error);
        if (!attributes.isNil()) {
            var symlink = ObjC.unwrap(attributes.objectForKey($.NSFileType)) === ObjC.unwrap($.NSFileTypeSymbolicLink);
            var ownedAlias = false;
            if (!symlink) {
                var values = destination.resourceValuesForKeysError($([$.NSURLIsAliasFileKey]), error);
                checked(values, error);
                if (ObjC.unwrap(values.objectForKey($.NSURLIsAliasFileKey))) {
                    var resolved = $.NSURL.URLByResolvingAliasFileAtURLOptionsError(
                        destination, $.NSURLBookmarkResolutionWithoutUI | $.NSURLBookmarkResolutionWithoutMounting, error
                    );
                    ownedAlias = !resolved.isNil() && ObjC.unwrap(resolved.path) === targetPath;
                }
            }
            if (!ownedAlias) {
                var stamp = new Date().toISOString().replace(/[-:]/g, "").replace("Z", "000000Z");
                var backup = path + ".pre-nix." + stamp;
                checked(files.moveItemAtPathToPathError(path, backup, error), error);
                console.log("Backed up Dock stack item to " + backup);
            }
        }

        checked($.NSURL.writeBookmarkDataToURLOptionsError(bookmark, destination, 0, error), error);
    });
}
