# EGM protocol: what each skill produces

Taken from the EGM plugin 0.1.1 (`skills/*/SKILL.md`, `docs/getting_started.md`,
`docs/claude.md`, `docs/designs/architecture.md`). Re-read the plugin if its
version changes.

## Order

brainstorm → draft → review (stages 5 → 6 → 7 → 8 → 9; resolve and
review-loop run inside stages 7 and 9) → human PR review → implementation →
drift report weekly. The guide allows skills out of order ("you can and
should reach for them out of order"), so a skipped step is a finding only
when its output is needed and missing.

Artifacts go to the working directory unless AGENTS.md or CLAUDE.md has a
line `EGM artifact directory: <path>`.

## Per skill

| Skill | Runs when | Writes | Done when | Next |
|---|---|---|---|---|
| egm-brainstorm | a new concept | `concepts_brief.md` (Overview, Analysis, Goals, Non-Goals, Alternatives Weighed, Key Decisions); optionally `docs/designs/<feature>.md` and a SITEMAP row | readiness gate passed, user confirms alignment, handoff gate | egm-draft |
| egm-draft | brief ready | `design_draft.md`, then `<design_dir>/<feature>.md`; a SITEMAP row (Link, Date, Author, Components, Description) | each section approved; brief reconciled with the draft; saved to the design dir | egm-review |
| egm-review | design saved | stage 5 `zoom_out_report.md`; 6 `comprehension_report.md`; 7 `critic_report.md`; 8 `intermediate_zoom_out_report.md`; 9 `implementation_readiness_report.md`; uninterrupted preset adds `consolidated_review_report.md` | each stage's gate; at most one re-audit per stage, then remaining findings are accepted trade-offs; stage 9 "conclude and finalize" | human PR, implementation |
| egm-review-loop | inside stages 7 and 9, or alone on any document | the synthesizer's report; resolve's report; edits to the target | two clean rounds in a row (no unsettled Blocker or Major), at most five rounds | back to the caller |
| egm-resolve | after Goldfish findings, in the session that wrote the doc | `goldfish_review_report.md` (each finding CONTEST, ESCALATE, PROPOSE FIX or DECLINE); approved edits to the target | `Status: resolved` at the top of the report | back to the caller |
| egm-bootstrap | existing code with no design coverage (optional) | `README.md` or `EGM.md` contracts in each code-bearing directory | verification pass read every contract | egm-drift-report |
| egm-drift-report | weekly, and after bootstrap | `<YYYY-MM-DD>_DRIFT_REPORT.md`, one section per design doc: differences or "No drift detected"; code no design covers counts as drift | every doc checked; the owner picks doc fix or code fix for each drift | doc update, issue or code change |

## Not covered by the plugin

EGM sets no rule for re-reviewing a design after a later decision amends
it. egm-check treats a decision that changes a design section, a trust
boundary, an owner gate or an external interface as needing a Goldfish
pass on the sections it touches; that is this project's rule, not the
plugin's.
