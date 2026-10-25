#!/usr/bin/env python3
"""Refresh APM 0.35's mount-local device number without replacing ownership evidence."""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import uuid


def refresh_device(home):
    home = home.resolve()
    key = hashlib.sha256(f"{home}|user".encode()).hexdigest()
    identity = home / ".apm-local/installation"
    receipt = home / f".apm/deployment-receipts/{key}.json"
    # Do not follow symlinked evidence, including parent directories. APM reports
    # these and all other invalid bindings itself; this is not general recovery.
    for path in (identity, receipt):
        for member in (path, *path.parents):
            if member == home:
                break
            if member.is_symlink():
                return
        if not path.is_file():
            return
    try:
        installation = identity.read_text(encoding="ascii").strip()
        if uuid.UUID(hex=installation).hex != installation:
            return
        data = json.loads(receipt.read_text(encoding="utf-8"))
        current = home.stat()
        recorded = data.get("root_identity")
        if (
            data.get("version") != 1
            or data.get("root") != home.as_posix()
            or data.get("scope") != "user"
            or data.get("installation") != installation
            or not isinstance(recorded, list)
            or len(recorded) != 2
            or any(type(value) is not int for value in recorded)
            or recorded[1] != current.st_ino
            or recorded[0] == current.st_dev
        ):
            return
    except (ValueError, UnicodeError, AttributeError):
        return

    # Darwin st_dev identifies the current mount, not a persistent volume.
    # Keep the installation UUID, inode, hashes, owners and destinations intact.
    data["root_identity"] = [current.st_dev, current.st_ino]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=receipt.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), stat.S_IMODE(receipt.stat().st_mode))
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.replace(temporary, receipt)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("APM: refreshed macOS receipt device number; installation and ownership preserved.")


if __name__ == "__main__" and sys.platform == "darwin":
    refresh_device(Path.home())
