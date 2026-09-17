# Workspace isolation

For any task that modifies repository files, always work in an isolated git worktree unless the user explicitly requests otherwise. Do not ask whether to use a worktree. First detect whether the current workspace is already isolated; reuse it when it is, otherwise create a native or Paseo-managed worktree automatically. Read-only investigation does not require a worktree.
