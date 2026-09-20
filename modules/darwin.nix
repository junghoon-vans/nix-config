{ config, pkgs, ... }:

let
  userHome = config.users.users.${config.system.primaryUser}.home;
  homeManagerBackup = pkgs.writeShellScript "home-manager-backup" ''
    target="$1"
    backup="''${target}.pre-nix.$(${pkgs.coreutils}/bin/date -u +%Y%m%dT%H%M%S.%NZ)"
    ${pkgs.coreutils}/bin/mv -- "$target" "$backup"
  '';
in

{
  environment.systemPackages = [
    (pkgs.callPackage ../packages/apm.nix { })
    (pkgs.callPackage ../packages/paseo.nix { })
  ];
  home-manager.backupCommand = homeManagerBackup;

  system.activationScripts.extraActivation.text = ''
    if sudo --user=${config.system.primaryUser} --set-home \
      ${config.homebrew.prefix}/bin/brew list --cask paseo >/dev/null 2>&1; then
      sudo --user=${config.system.primaryUser} --set-home \
        ${config.homebrew.prefix}/bin/brew uninstall --cask paseo
    fi
  '';

  homebrew = {
    enable = true;
    taps = builtins.attrNames config.nix-homebrew.taps;
    onActivation = {
      autoUpdate = false;
      upgrade = false;
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
    ];

    casks = [
      "aside"
      "chatgpt"
      "session-manager-plugin"
      "orbstack"
      "tailscale-app"
      "karabiner-elements"
      "jordanbaird-ice"
      "hop"
      "headlamp"
      "zed"
      "font-fira-code-nerd-font"
      "font-d2coding"
    ];

    masApps = {
      KakaoTalk = 869223134;
    };
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
      location = "${userHome}/Pictures/Screenshots";
    };
  };
}
