# Workspace isolation

For any task that modifies repository files, always work in an isolated git worktree unless the user explicitly requests otherwise. Do not ask whether to use a worktree. First detect whether the current workspace is already isolated; reuse it when it is, otherwise create a native or Paseo-managed worktree automatically. Read-only investigation does not require a worktree.

# Documentation changes

Do not automatically create or modify README files, changelogs, contribution guides, or other documentation as part of code changes.

Change documentation only when the user explicitly requests it or applicable repository instructions explicitly require it.

Verification alone does not authorize documentation changes. Do not treat the default workflow's requirement to update docs/changelog after verification as authorization.

When documentation changes are not authorized, report any relevant documentation implications in the final response instead.

# Browser automation

Use Aside MCP as the default for browser automation, including authenticated websites and local web UI verification. Read the `aside-browser` skill and the relevant Aside guide before browser work.

- Use Aside `exec` for multi-step website tasks; use Aside `repl` for precise interactions, DOM inspection, screenshots, and visual verification.
- Keep static page retrieval and documentation research on read/search tools when browser interaction is unnecessary.
- For an existing-page request, inspect Aside's open tabs and attach to the matching tab. For local UI verification, open a dedicated task tab and close only that tab afterward. Never navigate an unrelated user tab.
- Aside uses the user's login session. Preserve existing confirmation requirements for submissions, messages, purchases, and destructive actions; never export cookies or credentials to another browser.
- OMP Browser Relay is disabled. Do not enable it or launch Aside through OMP's browser `app.path`; use Aside MCP directly.
- OMP's independent browser automation is an exception, not a fallback. Use it only when the user explicitly requests another browser or approves a stated isolation, compatibility, or Aside capability limitation. Never silently switch to Brave, Chrome, or another browser after an Aside failure.
- Version-pinned headless document rendering, such as OfficeCLI PPT screenshots and PDF export, is a separate permitted exception. Keep it isolated from the user's browser profiles.

Apply this routing policy to delegated browser work as well. Do not install or update browsers, CLIs, or extensions merely to bypass an unavailable Aside connection; report the prerequisite and obtain approval first.
