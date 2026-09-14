{
  inputs,
  lib,
  pkgs,
  workstationUser,
  ...
}:

let
  inherit (workstationUser) username homeDirectory;
  ohMyZsh = pkgs.runCommand "oh-my-zsh" { } ''
    cp -a ${inputs.oh-my-zsh}/. "$out"
    chmod -R u+w "$out/custom"

    rm -rf \
      "$out/custom/plugins/zsh-autosuggestions" \
      "$out/custom/plugins/zsh-completions" \
      "$out/custom/plugins/zsh-hangul" \
      "$out/custom/plugins/zsh-syntax-highlighting" \
      "$out/custom/themes/spaceship-prompt" \
      "$out/custom/themes/spaceship.zsh-theme"

    ln -s ${inputs.zsh-autosuggestions} "$out/custom/plugins/zsh-autosuggestions"
    ln -s ${inputs.zsh-completions} "$out/custom/plugins/zsh-completions"
    ln -s ${inputs.zsh-hangul} "$out/custom/plugins/zsh-hangul"
    ln -s ${inputs.zsh-syntax-highlighting} "$out/custom/plugins/zsh-syntax-highlighting"
    ln -s ${inputs.spaceship-prompt} "$out/custom/themes/spaceship-prompt"
    ln -s ${inputs.spaceship-prompt}/spaceship.zsh-theme "$out/custom/themes/spaceship.zsh-theme"
  '';
  # Keep upstream's LSP registration; reuse Zed's built-in Go grammar.
  zedGnoManifest = (pkgs.formats.toml { }).generate "extension.toml" (
    removeAttrs (builtins.fromTOML (builtins.readFile "${inputs.zed-gno}/extension.toml")) [
      "grammars"
    ]
    // {
      lib = {
        kind = "Rust";
        version = "0.7.0";
      };
    }
  );
  zedGno = pkgs.pkgsCross.wasm32-wasip1.rustPlatform.buildRustPackage {
    pname = "zed-gno-extension";
    version = "0.1.0";
    src = inputs.zed-gno;
    cargoLock.lockFile = "${inputs.zed-gno}/Cargo.lock";
    nativeBuildInputs = [
      pkgs.pkgsCross.wasm32-wasip1.lld
      pkgs.wasm-tools
    ];
    env.RUSTFLAGS = "-C linker=wasm-ld";
    # Zed loads a WASI component, not the core module produced by wasip1.
    wasiAdapter = pkgs.fetchurl {
      url = "https://github.com/bytecodealliance/wasmtime/releases/download/v30.0.2/wasi_snapshot_preview1.reactor.wasm";
      hash = "sha256-BYocDKOrsq4B8f4wNbkACMksPvJCFP1HkGRjx5/GpYs=";
    };
    extensionManifest = zedGnoManifest;
    installPhase = builtins.readFile ../scripts/zed/install-gno-extension.sh;
    doCheck = false; # The cross-compiled library cannot run on the build host.
  };
in
{
  imports = [ ./aside.nix ];

  home = {
    inherit username homeDirectory;
    stateVersion = "26.05";
    packages = [ pkgs.mise ];
    sessionPath = [ "$HOME/.local/bin" ];
  };

  home.file = {
    ".zshrc".source = ../home/.zshrc;
    ".gitconfig".source = ../home/.gitconfig;
    ".gitignore_global".source = ../home/.gitignore_global;
    ".paseo/config.json".source = ../home/.paseo/config.json;
    ".omp/agent/config.yml".source = ../home/.omp/agent/config.yml;
    ".omp/agent/agents/frontend.md".source = ../home/.omp/agent/agents/frontend.md;
    ".omp/agent/mcp.json".source = ../home/.omp/agent/mcp.json;
    ".config/gh/config.yml".source = ../home/.config/gh/config.yml;
    ".config/karabiner/karabiner.json".source = ../home/.config/karabiner/karabiner.json;
    ".config/terminal/com.apple.Terminal.plist".source = ../home/terminal/com.apple.Terminal.plist;
    ".config/nvim/init.lua".source = ../home/.config/nvim/init.lua;
    ".config/nvim/lua/config/lazy.lua".source = ../home/.config/nvim/lua/config/lazy.lua;
    ".config/nvim/lua/config/options.lua".source = ../home/.config/nvim/lua/config/options.lua;
    ".config/zed/settings.json".source = ../home/.config/zed/settings.json;
    "Library/Application Support/Zed/extensions/installed/gno" = {
      source = zedGno;
      recursive = true;
    };
    ".local/bin/weekly-disk-maintenance" = {
      source = ../home/.local/bin/weekly-disk-maintenance;
      executable = true;
    };

    ".oh-my-zsh" = {
      source = ohMyZsh;
      recursive = true;
    };
  };

  home.activation.createScreenshotsDirectory = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD mkdir -p "$HOME/Pictures/Screenshots"
  '';

  home.activation.applyTerminalPreferences = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    $DRY_RUN_CMD /usr/bin/defaults import com.apple.Terminal "$HOME/.config/terminal/com.apple.Terminal.plist"
  '';
}
