# Zed

Home Manager owns Zed settings and installs the pinned Gno extension. The extension is built from
the `zed-gno` flake input as a `wasm32-wasip1` module, converted to a WASI component with the pinned
Wasmtime reactor adapter, and installed under Zed's extension directory.

The generated manifest must retain upstream's `language_servers.gnopls` registration. A binary
path in Zed settings alone does not register a language server. Gno continues to use Zed's built-in
Go grammar, so no separate grammar download is required. The manifest's `lib.version` identifies
the Zed extension API version, not the extension release.

After an approved activation, run `zed: reload extensions` or restart Zed. Open a `.gno` file in a
trusted worktree and confirm that `gnopls` starts. No manual extension installation or `rustup`
setup is required.
