#!/usr/bin/env bash

set -euo pipefail

if (( $# < 3 )); then
  printf 'Usage: %s BRANCH BODY PATH...\n' "$0" >&2
  exit 2
fi

branch="$1"
body="$2"
paths=("${@:3}")

if git diff --quiet -- "${paths[@]}"; then
  printf 'No dependency changes for %s\n' "$branch"
  exit 0
fi

# Capture the authoritative before/after pins before switching or committing.
# Reporting failures must stop before any GitHub or branch mutation.
title="$(python3 -B "$(dirname "${BASH_SOURCE[0]}")/dependency_report.py" --title "${paths[@]}")"
body="$(printf '%s' "$body" | python3 -B "$(dirname "${BASH_SOURCE[0]}")/dependency_report.py" "${paths[@]}")"

# Task-branch dispatches validate updates without replacing production bot branches,
# opening PRs from an unmerged base, or enabling their automatic merge.
if [[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch && "${GITHUB_REF:-}" != refs/heads/main ]]; then
  printf 'Preview only for %s\n%s\n%s\n' "${GITHUB_REF:-unknown ref}" "$title" "$body"
  exit 0
fi

# Query live labels before replacing a branch that may contain a human CI repair.
held="$(gh pr list --repo junghoon-vans/nix-config --base main --head "$branch" --state open \
  --json labels --jq 'any(.[]; any(.labels[]; (.name | ascii_downcase) == "ci-repair/manual-review"))')"
case "$held" in
  true) printf 'Skipping %s: ci-repair/manual-review preserves the repair\n' "$branch"; exit 0 ;;
  false) ;;
  *) printf 'Cannot determine manual-review hold for %s\n' "$branch" >&2; exit 1 ;;
esac

bot_login="${GH_APP_SLUG:?GH_APP_SLUG must identify the PR GitHub App}[bot]"
bot_id="$(gh api "users/$bot_login" --jq '.id')"
git config user.name "$bot_login"
git config user.email "${bot_id}+${bot_login}@users.noreply.github.com"
# Checkout-time tracking refs can be stale after an earlier PR is merged/deleted.
# Lease against the observed publication target, including an absent branch.
remote_head="$(git ls-remote --heads origin "refs/heads/$branch")"
remote_head="${remote_head%%[[:space:]]*}"
git switch -C "$branch"
git add --all -- "${paths[@]}"
git commit -m "$title"
git push "--force-with-lease=refs/heads/$branch:$remote_head" origin "HEAD:refs/heads/$branch"

if [ "$(gh pr list --head "$branch" --state open --json number --jq 'length')" -eq 0 ]; then
  gh pr create --base main --head "$branch" --title "$title" --body "$body"
else
  gh pr edit "$branch" --title "$title" --body "$body"
fi

python3 -B "$(dirname "${BASH_SOURCE[0]}")/enable-update-automerge.py" \
  --number "$(gh pr view "$branch" --json number --jq '.number')" \
  --branch "$branch" \
  --head "$(git rev-parse HEAD)"
