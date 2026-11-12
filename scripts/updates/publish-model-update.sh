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

# Model updates are manual-merge-only, but must also preserve held CI repairs.
held="$(gh pr list --repo junghoon-vans/nix-config --base main --head "$branch" --state open \
  --json labels --jq 'any(.[]; any(.labels[]; (.name | ascii_downcase) == "ci-repair/manual-review"))')"
case "$held" in
  true) printf 'Skipping %s: ci-repair/manual-review preserves the repair\n' "$branch"; exit 0 ;;
  false) ;;
  *) printf 'Cannot determine manual-review hold for %s\n' "$branch" >&2; exit 1 ;;
esac

body="$(cat "$body_file")"
bot_login="${GH_APP_SLUG:?GH_APP_SLUG must identify the PR GitHub App}[bot]"
bot_id="$(gh api "users/$bot_login" --jq '.id')"
git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
# Refresh the lease without trusting checkout-time remote-tracking refs.
remote_head="$(git ls-remote --heads origin "refs/heads/$branch")"
remote_head="${remote_head%%[[:space:]]*}"
git switch -C "$branch"
git add -- "${model_paths[@]}"
if git diff --cached --quiet -- "${model_paths[@]}"; then
  printf 'No supported OpenAI model pin changes for %s\n' "$branch"
  exit 0
fi

title='chore(models): update OpenAI model references'
git commit -m "$title" -- "${model_paths[@]}"
git push "--force-with-lease=refs/heads/$branch:$remote_head" origin "HEAD:refs/heads/$branch"
open_pr="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number // empty')"
if [[ -n "$open_pr" ]]; then
  gh pr edit "$open_pr" --title "$title" --body "$body"
else
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
fi
