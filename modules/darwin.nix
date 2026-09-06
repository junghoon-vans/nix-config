{ config, ... }:

{
  homebrew = {
    enable = true;
    taps = builtins.attrNames config.nix-homebrew.taps;
    onActivation = {
      autoUpdate = true;
      upgrade = true;
      cleanup = "none";
    };

    brews = [
      "neovim"
      "mole"
      "hugo"
      "git"
      "git-delta"
      "gh"
      "lazygit"
      "act"
      "actionlint"
      "prek"
      "delve"
      "go-task"
      "tmux"
      "hermes-agent"
      "cmake"
      "pkgconf"
      "marksman"
      "bash-language-server"
      "terraform-ls"
      "yaml-language-server"
      "shellcheck"
      "shfmt"
      "yamlfmt"
      "awscli"
      "kubernetes-cli"
      "helm"
      "terraform"
      "grpcurl"
      "mysql-client"
      "libpq"
      "bat"
      "eza"
      "ripgrep"
      "ast-grep"
      "fd"
      "htop"
      "jq"
      "tldr"
      "fzf"
      "zoxide"
      "microsoft/apm/apm"
    ];

    casks = [
      "aside"
      "session-manager-plugin"
      "orbstack"
      "tailscale-app"
      "karabiner-elements"
      "jordanbaird-ice"
      "hop"
      "headlamp"
      "paseo"
      "font-fira-code-nerd-font"
      "font-d2coding"
    ];
  };

  system.defaults = {
    NSGlobalDomain = {
      AppleInterfaceStyle = "Dark";
      AppleShowAllExtensions = true;
      InitialKeyRepeat = 15;
      KeyRepeat = 2;
      NSAutomaticCapitalizationEnabled = false;
      NSAutomaticDashSubstitutionEnabled = false;
      NSAutomaticPeriodSubstitutionEnabled = false;
      NSAutomaticQuoteSubstitutionEnabled = false;
      NSAutomaticSpellingCorrectionEnabled = false;
      NSDocumentSaveNewDocumentsToCloud = false;
    };
    dock = {
      autohide = true;
      autohide-delay = 0.0;
      autohide-time-modifier = 0.4;
      launchanim = false;
      show-recents = false;
    };
    finder = {
      AppleShowAllFiles = true;
      FXDefaultSearchScope = "SCcf";
      FXEnableExtensionChangeWarning = false;
      ShowPathbar = true;
      ShowStatusBar = true;
      _FXSortFoldersFirst = true;
    };
    screencapture = {
      disable-shadow = true;
      location = "/Users/junghoon/Pictures/Screenshots";
    };
  };
}
