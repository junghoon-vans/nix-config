# Workspace isolation

For any task that modifies repository files, always work in an isolated git worktree unless the user explicitly requests otherwise. Do not ask whether to use a worktree. First detect whether the current workspace is already isolated; reuse it when it is, otherwise create a native or Paseo-managed worktree automatically. Read-only investigation does not require a worktree.

# Documentation changes

Do not automatically create or modify README files, changelogs, contribution guides, or other documentation as part of code changes.

Change documentation only when the user explicitly requests it or applicable repository instructions explicitly require it.

Verification alone does not authorize documentation changes. Do not treat the default workflow's requirement to update docs/changelog after verification as authorization.

When documentation changes are not authorized, report any relevant documentation implications in the final response instead.
