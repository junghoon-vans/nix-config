#!/usr/bin/env python3
"""Exercise packaged gnopls builtin diagnostics and hover over stdio LSP."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time


def check(binary: str, root: Path) -> None:
    source = root / "smoke.gno"
    (root / "gnowork.toml").write_text("")
    (root / "gnomod.toml").write_text('module = "gno.land/p/builtin_smoke"\ngno = "0.9"\n')
    source.write_text("package builtin_smoke\n\nvar Owner address\nvar Broken = missingValue\n")
    env = os.environ.copy()
    # The package must work without caller-supplied toolchain paths or cached diagnostics.
    for name in ("GOROOT", "GNOROOT", "GNOBUILTIN", "GOPACKAGESDRIVER"):
        env.pop(name, None)
    env["GOPLSCACHE"] = str(root / "cache")
    messages = queue.Queue()
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            [binary, "serve"], cwd=root, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
        )

        def receive() -> None:
            try:
                while True:
                    headers = {}
                    while True:
                        line = process.stdout.readline()
                        if not line:
                            raise EOFError("gnopls closed stdout")
                        if line == b"\r\n":
                            break
                        key, value = line.decode().split(":", 1)
                        headers[key.lower()] = value.strip()
                    body = process.stdout.read(int(headers["content-length"]))
                    messages.put(json.loads(body))
            except Exception as error:
                messages.put(error)

        threading.Thread(target=receive, daemon=True).start()

        def send(message: dict) -> None:
            body = json.dumps({"jsonrpc": "2.0", **message}).encode()
            process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            process.stdin.flush()

        deadline = time.monotonic() + 45

        def wait_for(predicate):
            while True:
                message = messages.get(timeout=max(0, deadline - time.monotonic()))
                if isinstance(message, Exception):
                    raise message
                if "method" in message and "id" in message:
                    send({"id": message["id"], "result": None})
                elif predicate(message):
                    return message

        try:
            send({"id": 1, "method": "initialize", "params": {
                "processId": None, "rootUri": root.as_uri(), "capabilities": {},
                "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            }})
            initialized = wait_for(lambda message: message.get("id") == 1)
            if "error" in initialized:
                raise RuntimeError(initialized)
            send({"method": "initialized", "params": {}})
            send({"method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": source.as_uri(), "languageId": "gno", "version": 1,
                "text": source.read_text(),
            }}})
            published = wait_for(lambda message: (
                message.get("method") == "textDocument/publishDiagnostics"
                and message["params"]["uri"] == source.as_uri()
            ))
            diagnostics = published["params"]["diagnostics"]
            errors = [item["message"] for item in diagnostics if item.get("severity") == 1]
            if errors != ["undefined: missingValue"]:
                raise RuntimeError(f"unexpected diagnostics: {diagnostics}")
            send({"id": 2, "method": "textDocument/hover", "params": {
                "textDocument": {"uri": source.as_uri()},
                "position": {"line": 2, "character": 11},
            }})
            hover = wait_for(lambda message: message.get("id") == 2)
            content = (hover.get("result") or {}).get("contents", {})
            if "type address string" not in content.get("value", ""):
                raise RuntimeError(f"builtin hover failed: {hover}")
            print("gnopls: address type-checks and resolves builtin hover; undefined names still diagnosed")
        except Exception:
            process.terminate()
            process.wait(timeout=5)
            stderr.seek(0)
            sys.stderr.write(stderr.read().decode(errors="replace"))
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()


def main() -> None:
    binary = str(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory(prefix="gnopls-smoke-") as directory:
        check(binary, Path(directory).resolve())


if __name__ == "__main__":
    main()
