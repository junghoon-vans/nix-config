{ inputs, lib, pkgs, ... }:

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
      source = inputs.oh-my-zsh;
      recursive = true;
    };
    ".oh-my-zsh/custom/plugins/zsh-autosuggestions" = {
      source = inputs.zsh-autosuggestions;
      recursive = true;
    };
    ".oh-my-zsh/custom/plugins/zsh-completions" = {
      source = inputs.zsh-completions;
      recursive = true;
    };
    ".oh-my-zsh/custom/plugins/zsh-hangul" = {
      source = inputs.zsh-hangul;
      recursive = true;
    };
    ".oh-my-zsh/custom/plugins/zsh-syntax-highlighting" = {
      source = inputs.zsh-syntax-highlighting;
      recursive = true;
    };
    ".oh-my-zsh/custom/themes/spaceship-prompt" = {
      source = inputs.spaceship-prompt;
      recursive = true;
    };
    ".oh-my-zsh/custom/themes/spaceship.zsh-theme".source = "${inputs.spaceship-prompt}/spaceship.zsh-theme";
  };

  home.activation.createScreenshotsDirectory = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD mkdir -p "$HOME/Pictures/Screenshots"
  '';

  home.activation.applyTerminalPreferences = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    $DRY_RUN_CMD /usr/bin/defaults import com.apple.Terminal "$HOME/.config/terminal/com.apple.Terminal.plist"
  '';
}
