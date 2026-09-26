#!/usr/bin/env bash

set -euo pipefail

branch="$1"
title="$2"
body="$3"
paths=("${@:4}")

if git diff --quiet -- "${paths[@]}"; then
  printf 'No dependency changes for %s\n' "$branch"
  exit 0
fi

git config user.name github-actions[bot]
git config user.email 41898282+github-actions[bot]@users.noreply.github.com
git switch -C "$branch"
git add --all -- "${paths[@]}"
git commit -m "$title"
git push --force-with-lease origin "HEAD:$branch"

if ! gh pr view "$branch" >/dev/null 2>&1; then
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
fi
