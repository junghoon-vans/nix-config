"""Workflow paths approved for Dependabot reporting and auto-merge."""

DEPENDABOT_ACTION_PATHS = frozenset({
    ".github/workflows/dependabot-automerge.yml",
    ".github/workflows/mcp-security.yml",
    ".github/workflows/update-dependencies.yml",
    ".github/workflows/update-models.yml",
    ".github/workflows/validate.yml",
})
