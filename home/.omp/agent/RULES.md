# Documentation changes

Do not automatically create or modify README files, changelogs, contribution guides, or other documentation as part of code changes.

Change documentation only when the user explicitly requests it or applicable repository instructions explicitly require it.

Verification alone does not authorize documentation changes. Do not treat the default workflow's requirement to update docs/changelog after verification as authorization.

When documentation changes are not authorized, report any relevant documentation implications in the final response instead.

# Browser automation

Use Ego Lite for browser work: public research that needs a browser, logged-in data exploration, UI testing, and screenshots. Read the official `ego-browser` skill and invoke its documented CLI through OMP execution tools. Use web search, static reads, or APIs when those fit the task without a browser.

- Never transfer cookies or credentials between browsers.
- For explicit user browser choices, follow the choice when safe and available. Do not automatically fail over between browsers after authentication, permission, or other errors; stop and hand off to the user.
- Preserve existing confirmation requirements for submissions, destructive actions, purchases, and messages. Never navigate unrelated user tabs. Browser permission prompts and device choosers require user action; hand off and stop.
- Do not install or update browsers, CLIs, or extensions to bypass an unavailable browser or an error. Never substitute Agent Desktop for browser work.
- OMP Browser Relay is disabled. Do not enable it.
- For headless document rendering through the installed Brave app, such as OfficeCLI PPT screenshots and PDF export, use temporary profiles isolated from user browser profiles; do not install Chrome, Chromium, or a separate headless browser.

Apply this routing policy to delegated browser work as well.
