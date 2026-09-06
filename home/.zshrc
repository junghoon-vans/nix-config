# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH

# Path to your Oh My Zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time Oh My Zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="spaceship"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment one of the following lines to change the auto-update behavior
# zstyle ':omz:update' mode disabled  # disable automatic updates
# zstyle ':omz:update' mode auto      # update automatically without asking
# zstyle ':omz:update' mode reminder  # just remind me to update when it's time

# Uncomment the following line to change how often to auto-update (in days).
# zstyle ':omz:update' frequency 13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS="true"

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# You can also set it to another string to have that shown instead of the default red dots.
# e.g. COMPLETION_WAITING_DOTS="%F{yellow}waiting...%f"
# Caution: this setting can cause issues with multiline prompts in zsh < 5.7.1 (see #5765)
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(
  git
  golang
  docker
  npm
  node
  brew
  macos
  sudo
  web-search
  jsontools
  colored-man-pages
  zsh-completions
  zsh-autosuggestions
  zsh-syntax-highlighting
  zsh-hangul
)

if command -v brew >/dev/null 2>&1; then
  export HOMEBREW_PREFIX="$(brew --prefix)"
elif [[ -d "/opt/homebrew" ]]; then
  export HOMEBREW_PREFIX="/opt/homebrew"
elif [[ -d "/usr/local/Homebrew" || -x "/usr/local/bin/brew" ]]; then
  export HOMEBREW_PREFIX="/usr/local"
fi

typeset -U path PATH

source $ZSH/oh-my-zsh.sh

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='nvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch $(uname -m)"

# Set personal aliases, overriding those provided by Oh My Zsh libs,
# plugins, and themes. Aliases can be placed here, though Oh My Zsh
# users are encouraged to define aliases within a top-level file in
# the $ZSH_CUSTOM folder, with .zsh extension. Examples:
# - $ZSH_CUSTOM/aliases.zsh
# - $ZSH_CUSTOM/macos.zsh
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"

# ========================================
# FZF Configuration
# ========================================
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# ========================================
# Zoxide Configuration (smart directory navigation)
# ========================================
command -v zoxide &>/dev/null && eval "$(zoxide init zsh)"
alias j='z'  # muscle memory compatibility with autojump

# Gno Configuration
export GNOPATH=$HOME/gno
export GNOROOT=$HOME/gno
# ========================================
# mise Configuration
# ========================================
# Keep mise-managed runtimes ahead of legacy managers inherited from old shells.
# Global defaults are tracked in ~/.config/mise/config.toml.
path=(${path:#$HOME/.nvm/*})
path=(${path:#$HOME/.sdkman/*})
path=(${path:#$HOME/.bun/bin})
path=(${path:#$HOME/.cargo/bin})
path=(${path:#$HOME/go/bin})
unset NVM_DIR SDKMAN_DIR BUN_INSTALL GOROOT
if command -v mise &>/dev/null && [ -z "${MISE_SHELL:-}" ]; then
  eval "$(mise activate zsh)"
  unset GOROOT
fi
path=(${path:#$HOME/.nvm/*})
path=(${path:#$HOME/.sdkman/*})
path=(${path:#$HOME/.bun/bin})
path=(${path:#*/opt/go@1.25/bin})
path=(${path:#$HOME/go/bin})

# ========================================
# General Aliases
# ========================================
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'

# ========================================
# Codex HUD
# ========================================
# codex-hud alias
codex() {
  if [[ -x "$HOME/.local/bin/codex-hud" ]]; then
    "$HOME/.local/bin/codex-hud" "$@"
  else
    command codex "$@"
  fi
}

codex-resume() {
  if [[ -x "$HOME/.local/bin/codex-hud" ]]; then
    "$HOME/.local/bin/codex-hud" resume "$@"
  else
    command codex resume "$@"
  fi
}


# ========================================
# Environment Variables
# ========================================

# History settings
HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=50000
setopt SHARE_HISTORY
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_SPACE
setopt HIST_EXPIRE_DUPS_FIRST
setopt EXTENDED_HISTORY

# Editor
export EDITOR=nvim
export VISUAL=nvim

# mysql-client
[[ -n "${HOMEBREW_PREFIX:-}" && -d "$HOMEBREW_PREFIX/opt/mysql-client/lib/pkgconfig" ]] && export PKG_CONFIG_PATH="$HOMEBREW_PREFIX/opt/mysql-client/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
[[ -n "${HOMEBREW_PREFIX:-}" && -d "$HOMEBREW_PREFIX/opt/mysql-client/bin" ]] && export PATH="$HOMEBREW_PREFIX/opt/mysql-client/bin:$PATH"

# libpq (PostgreSQL client)
[[ -n "${HOMEBREW_PREFIX:-}" && -d "$HOMEBREW_PREFIX/opt/libpq/bin" ]] && export PATH="$HOMEBREW_PREFIX/opt/libpq/bin:$PATH"

path=(${path:#$HOME/.local/bin})
path+=("$HOME/.local/bin")

# Bun global CLI tools, including omp, are installed here by setup/apps/*.sh.
# Keep this after mise so mise-managed Bun remains the runtime provider.
if [[ -d "$HOME/.bun/bin" ]]; then
  path=(${path:#$HOME/.bun/bin})
  path+=("$HOME/.bun/bin")
fi

export ANTHROPIC_MODEL="sonnet"

# ========================================
# Local Overrides (machine-specific)
# ========================================
[ -f "$HOME/.zshrc.local" ] && source "$HOME/.zshrc.local"

# ========================================
# Modern CLI Tools Aliases
# ========================================
alias cat='bat'
alias ls='eza --icons'
alias l='eza --icons'
alias ll='eza -alh --icons'
alias la='eza -a --icons'
alias lt='eza --tree --icons'
alias grep='rg'
alias pre-commit='prek'
alias lg='lazygit'
