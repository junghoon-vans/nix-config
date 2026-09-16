#!/bin/bash

set -euo pipefail

KEEP_DAYS="${KEEP_DAYS:-30}"
CONFIRM="${CONFIRM:-0}"

case "$KEEP_DAYS" in
    ''|*[!0-9]*)
        printf 'KEEP_DAYS must be a non-negative integer\n' >&2
        exit 2
        ;;
esac

case "$CONFIRM" in
    0|1)
        ;;
    *)
        printf 'CONFIRM must be exactly 0 or 1\n' >&2
        exit 2
        ;;
esac

search_roots=(
    "$HOME"
    "$HOME/.config"
    "$HOME/.local"
    "$HOME/.omp"
    "$HOME/.paseo"
    "$HOME/Library/Application Support/Zed/extensions/installed"
)

backups=()
collect_backups() {
    local backup

    while IFS= read -r -d '' backup; do
        backups+=("$backup")
    done < <(
        find "$@" \
            \( -type f -o -type d \) \
            -name '*.pre-nix.????????T??????.?????????Z' \
            -mtime "+$KEEP_DAYS" \
            -prune \
            -print0 \
            2>/dev/null
    )
}

for root in "${search_roots[@]}"; do
    [ -d "$root" ] || continue

    if [ "$root" = "$HOME" ]; then
        collect_backups "$root" -maxdepth 1
    else
        collect_backups "$root"
    fi
done

if [ "${#backups[@]}" -eq 0 ]; then
    printf 'No Home Manager backups older than %s day(s).\n' "$KEEP_DAYS"
    exit 0
fi

printf 'Home Manager backups older than %s day(s):\n' "$KEEP_DAYS"
printf '%s\n' "${backups[@]}"

if [ "$CONFIRM" = "0" ]; then
    printf 'No files removed. Re-run with CONFIRM=1 to delete these backups.\n'
    exit 0
fi

rm -rf -- "${backups[@]}"
printf 'Removed %s Home Manager backup(s).\n' "${#backups[@]}"
