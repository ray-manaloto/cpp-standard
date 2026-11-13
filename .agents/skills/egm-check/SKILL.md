---
name: egm-check
description: Check whether the project has drifted from the EGM (Elephant-Goldfish Model) workflow - skipped or stale egm-brainstorm, egm-draft, egm-review, egm-resolve, egm-review-loop, egm-bootstrap or egm-drift-report runs, decisions and code changes no Goldfish review has seen, and EGM artifacts that are missing, stale or unmarked - then name the next EGM step to run. Use it whenever the user asks "are we still following EGM", "did we skip a step", "are we on track", "what did we forget to write down", after a run of research, probes or spikes, before a milestone or exit review, before calling a design "done", or when work has gone on for a while without an EGM skill. Use it even if the user only says they feel distracted or off track.
---

# EGM check

The EGM workflow keeps design and code in step: a brainstorm brief, a
drafted design, a five-stage Goldfish review with resolved findings, and a
weekly drift report once code exists. Long stretches of research, spikes
and fixes tend to change decisions and code without any of that happening.
This skill finds those gaps from what is in the repository, so the answer
rests on evidence rather than on memory of the session.

It reports and recommends. It does not run the EGM skills itself and does
not edit the design: those steps need the owner's gates, and running them
silently would be the same kind of drift this skill exists to catch.

## Step 1: gather the facts

Run the bundled script from inside the repository:

```bash
.agents/skills/egm-check/scripts/egm-state.sh [design_dir] [artifact_dir]
```

Defaults: `docs/designs`, and the artifact directory named by an
`EGM artifact directory: <path>` line in AGENTS.md or CLAUDE.md, else the
design subdirectory that holds the `*_report.md` files. The script only
reads. Keep its output; every finding below cites a line of it.

## Step 2: compare with the protocol

Read `references/protocol.md` for what each EGM skill must produce and when
it should run. Then check each item below against the script output. Each
check names the evidence that settles it; do not mark a check as failed on
a guess, and do not mark it passed without its evidence.

1. **Unreviewed decisions.** `decisions_never_reviewed` lists decisions
   newer than any review report cites. Read those rows in the decisions
   log. A decision that changes a design section, a trust boundary, an
   owner gate or an external interface needs a Goldfish pass on the
   sections it touches (egm-review at the matching stage, or
   egm-review-loop on those lines). A purely mechanical one can be noted
   and left.
2. **Changes since the last review.** For each non-doc path changed since
   `last_review_commit`, find the design section that describes it
   (search the design for the file name). No section at all is drift
   (egm-drift-report counts uncovered code as drift). A section that
   exists but was edited after the review is unreviewed text.
3. **Design header honesty.** If the design's Status says the review is
   complete but items 1 or 2 found unreviewed decisions or text, the
   header overstates; say so.
4. **Review stages.** The preset sets which reports to expect. The full
   presets need all five (`zoom_out_report.md`, `comprehension_report.md`,
   `critic_report.md`, `intermediate_zoom_out_report.md`,
   `implementation_readiness_report.md`); the uninterrupted preset also
   writes `consolidated_review_report.md`. The feature-spec-only preset
   stops after stage 8, and the implementation-only preset runs stage 9
   alone, so a missing report outside the chosen preset is not a gap. A
   finished egm-resolve run leaves `Status: resolved` at the top of
   `goldfish_review_report.md`.
5. **Draft and brief.** A `design_draft.md` still marked Draft next to a
   saved design is a stale working copy; say whether it should be deleted
   or marked superseded.
6. **SITEMAP.** Every top-level design doc has a row, and the row's
   components match what the design now covers (for example a new gate
   or tool added by a later decision).
7. **Drift report.** None ever, or older than seven days while code has
   changed since, means egm-drift-report is due (the EGM getting-started
   guide asks for it weekly).
8. **Spike and probe findings.** Results in spike READMEs or research
   notes that change a design choice must reach the design or the
   decisions log. Search the design for each finding's key term; a
   finding with no match is unrecorded.
9. **Open branches.** An unmerged branch that edits the design will need
   its own review of those edits; list it so it is not forgotten.
10. **Bootstrap contracts.** egm-bootstrap is optional. List the
    code-bearing directories without a README.md or EGM.md for
    information only, unless the drift report finds uncovered code there.
11. **The design's own tracking.** The design lists things it expects to
    happen: open questions, milestone exit checks (spike results, pass
    lines due by a date), and files a milestone will create. Compare them
    with the repository. An open question the repository already answers
    (a LICENSE file for a license question, a public repository for a
    "before going public" question) should be closed in the design. An
    exit check with no recorded result close to its date is the most
    urgent kind of gap, because the milestone review will have nothing
    to read.
12. **Artifact directory line.** If AGENTS.md or CLAUDE.md has no
    `EGM artifact directory:` line, EGM skills write to the working
    directory by default; recommend adding the line naming the directory
    the project actually uses.

## Step 3: report

Write the report in chat with this structure, plain and short:

```markdown
# EGM check, <date>

**Verdict:** on track | drifting | off track - one sentence why.

## Gaps
| # | Gap | Evidence | Fix (EGM step) |
|---|-----|----------|----------------|
(one row per failed check, most serious first; evidence quotes the
script line or a file:line)

## Next steps
1. <the single most important EGM step, with its exact skill and target,
   e.g. "/egm:egm-review docs/designs/x.md, Stage 5 then 8, on §6 and the
   D101 rows">
2. ...

## Checked and fine
(one line per passed check)
```

Rank by risk: design text that contradicts a later decision, and
unreviewed decisions that change a trust boundary or owner gate, come
first; then exit checks without results near their date; then uncovered
code; then missing artifacts; then housekeeping. For each unreviewed
decision, grep the design for the behaviour it replaced: a design that
still describes the old behaviour is a contradiction, which is worse
than text nobody reviewed. "Off track" means at least one decision or code change that
alters the design has had no Goldfish review; "drifting" means only
artifacts or housekeeping are behind.

If the user asks for a file, save the same report as
`<artifact_dir>/egm_check_<YYYY-MM-DD>.md`.

Finish by asking the owner which next step to run. One question, with the
recommended step first.
