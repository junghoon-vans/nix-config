#!/usr/bin/env bash

set -euo pipefail

branch="$1"
title="$2"
body="$3"

if git diff --quiet; then
  printf 'No dependency changes for %s\n' "$branch"
  exit 0
fi

base_sha="$(git rev-parse HEAD)"
git config user.name github-actions[bot]
git config user.email 41898282+github-actions[bot]@users.noreply.github.com
git switch -C "$branch"
git add --all
git commit -m "$title"
git push --force-with-lease origin "HEAD:$branch"

if ! gh pr view "$branch" >/dev/null 2>&1; then
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
fi

gh workflow run validate.yml --ref "$branch" -f "base_sha=$base_sha"
