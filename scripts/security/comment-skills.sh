#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?}" "${GITHUB_RUN_ID:?}" "${PR_NUMBER:?}" "${HEAD_SHA:?}"
marker='<!-- skillspector-advisory -->'
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"

# Download data only. Never execute files from the scanner artifact.
if ! gh run download "$GITHUB_RUN_ID" --repo "$GITHUB_REPOSITORY" \
  --name skillspector-reports --dir "$work_dir/reports"; then
  printf '%s\n' 'SkillSpector reports could not be downloaded.' >&2
fi
summary="$work_dir/reports/summary.md"
if [[ ! -f "$summary" ]]; then
  mkdir -p "$work_dir/reports"
  printf '%s\n' 'Inspection summary is unavailable. Review the run logs; no safety conclusion is available.' > "$summary"
fi

# Bound the comment size and prevent report text from notifying users or teams.
jq -n --rawfile summary "$summary" --arg marker "$marker" \
  --arg sha "$HEAD_SHA" --arg url "$run_url" '
  {body: ($marker + "\n## SkillSpector advisory\n\nCommit: `" + $sha + "` · [CI run and report artifacts](" + $url + ")\n\n" +
    "**CI success does not mean these skills are safe.** Static findings can be false positives; incomplete analysis is not a safety verdict.\n\n" +
    ($summary | gsub("@"; "@\u200b") | if length > 45000 then .[0:45000] + "\n\nSummary truncated; see report artifacts." else . end))}
' > "$work_dir/comment.json"

comment_id=$(gh api --paginate --slurp \
  "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments?per_page=100" \
  | jq -r --arg marker "$marker" '
    [ .[][] | select(.user.login == "github-actions[bot]" and ((.body // "") | startswith($marker))) ]
    | last | .id // empty
  ')
if [[ -n "$comment_id" ]]; then
  gh api --method PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${comment_id}" \
    --input "$work_dir/comment.json" --silent
else
  gh api --method POST "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
    --input "$work_dir/comment.json" --silent
fi
