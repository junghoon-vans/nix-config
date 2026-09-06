{ inputs, lib, pkgs, ... }:

let
  ohMyZsh = pkgs.runCommand "oh-my-zsh" {} ''
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
in
{
  home = {
    username = "junghoon";
    homeDirectory = "/Users/junghoon";
    stateVersion = "26.05";
    packages = [ pkgs.chezmoi pkgs.mise ];
    sessionPath = [ "$HOME/.local/bin" ];
  };

  home.file = {
    ".zshrc".source = ../home/.zshrc;
    ".gitconfig".source = ../home/.gitconfig;
    ".gitignore_global".source = ../home/.gitignore_global;
    ".paseo/private_config.json".source = ../home/.paseo/private_config.json;
    ".omp/agent/config.yml".source = ../home/.omp/agent/config.yml;
    ".config/gh/config.yml".source = ../home/.config/gh/config.yml;
    ".config/karabiner/karabiner.json".source = ../home/.config/karabiner/karabiner.json;
    ".config/terminal/com.apple.Terminal.plist".source = ../home/terminal/com.apple.Terminal.plist;
    ".config/nvim/init.lua".source = ../home/.config/nvim/init.lua;
    ".config/nvim/lua/config/lazy.lua".source = ../home/.config/nvim/lua/config/lazy.lua;
    ".config/nvim/lua/config/options.lua".source = ../home/.config/nvim/lua/config/options.lua;
    ".config/zed/settings.json".source = ../home/.config/zed/settings.json;
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
