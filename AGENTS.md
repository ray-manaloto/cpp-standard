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
