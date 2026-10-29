#!/usr/bin/env bash

set -euo pipefail

if (( $# < 4 )); then
  printf 'Usage: %s BRANCH TITLE BODY PATH...\n' "$0" >&2
  exit 2
fi

branch="$1"
title="$2"
body="$3"
paths=("${@:4}")

if git diff --quiet -- "${paths[@]}"; then
  printf 'No dependency changes for %s\n' "$branch"
  exit 0
fi

bot_login="${GH_APP_SLUG:?GH_APP_SLUG must identify the PR GitHub App}[bot]"
bot_id="$(gh api "users/$bot_login" --jq '.id')"
git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
git switch -C "$branch"
git add --all -- "${paths[@]}"
git commit -m "$title"
git push --force-with-lease origin "HEAD:$branch"

if [ "$(gh pr list --head "$branch" --state open --json number --jq 'length')" -eq 0 ]; then
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
else
  gh pr edit "$branch" --title "$title" --body "$body"
fi

python3 -B "$(dirname "${BASH_SOURCE[0]}")/enable-update-automerge.py" \
  --number "$(gh pr view "$branch" --json number --jq '.number')" \
  --branch "$branch" \
  --head "$(git rev-parse HEAD)"
