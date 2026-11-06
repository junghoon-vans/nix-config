#!/usr/bin/env bash

set -euo pipefail

if (( $# != 2 )); then
  printf 'Usage: %s BRANCH BODY-FILE\n' "$0" >&2
  exit 2
fi

branch="$1"
body_file="$2"
model_paths=(
  home/.omp/agent/config.yml
  home/.paseo/config.json
  modules/aside.nix
  modules/hermes.nix
)

git diff --quiet HEAD -- "${model_paths[@]}" && {
  printf 'No supported OpenAI model pin changes for %s\n' "$branch"
  exit 0
}

body="$(cat "$body_file")"
bot_login="${GH_APP_SLUG:?GH_APP_SLUG must identify the PR GitHub App}[bot]"
bot_id="$(gh api "users/$bot_login" --jq '.id')"
git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
git switch -C "$branch"
git add -- "${model_paths[@]}"
if git diff --cached --quiet -- "${model_paths[@]}"; then
  printf 'No supported OpenAI model pin changes for %s\n' "$branch"
  exit 0
fi

title='chore(models): update OpenAI model references'
git commit -m "$title" -- "${model_paths[@]}"
git push --force-with-lease origin "HEAD:$branch"
open_pr="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number // empty')"
if [[ -n "$open_pr" ]]; then
  gh pr edit "$open_pr" --title "$title" --body "$body"
else
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
fi
