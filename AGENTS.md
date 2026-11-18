# cpp-standard agent notes

EGM artifact directory: docs/designs/level-1/

The design is `docs/designs/environment-standard.md`; its decisions are in
`docs/designs/level-1/decisions-log.md`. Run the `egm-check` project skill
(`.agents/skills/egm-check/`) to see where the work stands against the EGM
workflow.

## No agent runs the Antigravity CLI

No agent ever runs `agy`: not `agy -p`, not from Claude Code, Codex, OpenCode, a script or `hc send`. In a project
container it signs in with the owner's Google account, and Google's terms call third-party software accessing the
service a breach that may suspend the owner's Antigravity and Gemini CLI accounts (antigravity.google/terms). The
owner runs `agy` only in a terminal they type into, and no agent reads or copies its login files (D155).

## Agent skills

### Issue tracker

GitHub Issues on ray-manaloto/cpp-standard, through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles, each label named as its role: `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. Decisions are the D-rows of `docs/designs/level-1/decisions-log.md` (there is no `docs/adr/`); the
design is `docs/designs/environment-standard.md`. See `docs/agents/domain.md`.
