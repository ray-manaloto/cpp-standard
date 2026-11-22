---
name: codex-hook-health
description: Diagnose Codex lifecycle hooks that need review after a plugin refresh, disappear from discovery, or reference a missing plugin version on resume. Check hook health before publishing a Codex plugin or restarting its sessions.
---

# Codex hook health

1. Identify the affected Codex executable and version, home, cwd, profile and native thread. Use `/hooks` in that session for authorized source and trust review. Use the [read-only health command](references/check.md) for native discovery in a known control context.
2. Compare the full native hook identity with the reviewed baseline. An unchanged declaration and a different bundle digest require source review, even when the version is unchanged. Keep existing approvals for unchanged hooks. Route approval decisions through native review.
3. For missing-path errors on resume, check the exact old absolute target and bytes recorded for the session. A new version can be healthy while an older path needed for resume is missing. Preserve those paths through publication and restart.
4. Report discovery, retention and runtime evidence separately. Require a matching native thread and a fresh event receipt before claiming a hook ran. Record runtime as `NOT_RUN` when only inspecting native discovery.

Use `codex doctor` for harness diagnostics and focused native events or logs for failure evidence. For a Git commit hook, inspect Git's hook path and use the hk skills for repository checks.
