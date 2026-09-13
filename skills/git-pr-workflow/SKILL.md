---
name: git-pr-workflow
description: Use when implementing repository changes for a branch or pull request, committing and pushing requested changes, opening or updating a PR, or addressing PR review feedback. Requires an isolated Git worktree for every code-changing task and preserves unrelated work.
---

# Git and PR workflow

## Isolate before editing

- Follow repository instructions and the user's requested scope. Inspect the repository root, remotes, status, current branch, and `git worktree list --porcelain` before changing files.
- Every code-changing task MUST run in a dedicated linked Git worktree on a task branch. Never edit the primary checkout, even when it is clean or already on a feature branch. Read-only inspection does not require a worktree.
- Reuse an existing linked worktree only when it belongs to this exact task or PR and no other agent is writing there. Do not create a nested worktree merely because the task already has one.
- Determine the base from the requested PR or branch; otherwise discover the remote default branch rather than assuming `main` or `master`. Fetch that base before starting a new task branch. For review follow-ups, use the existing PR head instead of starting again from the default branch.
- Create the task worktree outside the primary checkout, following existing workspace conventions. Use an unused path and branch name. If a branch is already checked out, inspect and reuse its task worktree when safe; never force checkout or remove another worktree.
- Run all edits, dependency operations, validation, staging, commits, and pushes with the dedicated worktree as the working directory. Verify its branch and directory before the first write. If isolation cannot be established, stop before editing and report the blocker.
- Leave unrelated tracked, untracked, staged, and generated files untouched. Never automatically stash, reset, clean, or move the user's changes into the new worktree.

## Implement and verify

- Change only the requested behavior and affected callers. Respect local approval boundaries for activation, installs, credentials, and external state.
- For review feedback, enumerate actionable threads, distinguish defects from preferences, and track every requested item. Use the same PR worktree. Explain disagreements with evidence rather than silently skipping them.
- Exercise the changed behavior using the repository's validation conventions. Run `git diff --check` and review the complete intended diff before committing. Report actual checks and limitations; do not describe an evaluation as a build or a build as activation.
- Avoid unrelated dependency updates, formatting, generated files, and runtime state. Do not add or expose credentials in commits, logs, or PR descriptions.

## Commit and publish when requested

- A request to implement alone is not authorization to publish. Commit, push, create or update PRs only within the user's requested scope; an explicit request to open a PR authorizes those steps without another confirmation.
- Inspect the staged diff for unrelated changes. Stage explicit intended paths, never `git add -A` or `git add .`. Use focused Conventional Commits unless the repository specifies otherwise.
- Push the task branch normally. Never force-push, merge, delete branches, or remove worktrees without explicit authorization. Leave the worktree available for review follow-ups.
- Check for an existing PR for the exact repository and head branch before creating one. Update it rather than opening a duplicate. Verify the base and head, including the head repository for forks.
- Describe the behavior change, changed files, verification actually performed, known limitations, and any activation or approval still needed. Do not imply local installation or deployment occurred when only configuration changed.
- Read the PR back from the API after creation or update. Report its returned number, title, URL, base/head, and observed CI status together; never infer a PR number from creation order. Pending CI is pending, not a pass.
- For requested review replies or thread resolution, tie replies to the verified fix and report unresolved items. Do not resolve threads merely because code was edited.
