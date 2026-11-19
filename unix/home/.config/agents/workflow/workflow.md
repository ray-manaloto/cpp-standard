---
okf_version: "0.2"
type: "process"
title: "The agent workflow"
description: "The rules and the eight steps that take an idea to a merged pull request."
timestamp: "2026-11-04T00:00:00Z"
status: "current"
tags: [workflow]
---

# The agent workflow

## Rules

1. People do the thinking steps: grilling, spec sign-off, ticket approval and the merge. Agents do
   the mechanical steps: implementing, reviewing and drafting pull request text.
2. Steps 1-3 share one attended session; every later step gets a fresh session. An optional
   Codex review runs in its own tab, never in the author's session. One ticket per worker, one
   git worktree per worker.
3. State lives in GitHub: issues, labels, assignees and blocked-by links. The roadmap and the ticket
   plans mirror it and hold working notes.
4. A review finding is a hypothesis to check against the diff. No review is required (owner ruling,
   2026-11-17); a lead may ask Codex for one by choice (see [cross-review](cross-review.md)).
5. Every loop has a cap. No review runs "until clean": three rounds per review kind, then park.
6. A mechanical mistake that recurs becomes a deterministic check; judgement calls stay in the
   repository's coding standards.
7. Workers never write to GitHub and never commit. They leave their changes in the worktree, write
   the proposed commit message to a file and stop.
8. Spend is tracked across a ticket, not only per loop. While a person is watching, money limits are
   advisory; an external spend limit is set and verified before anything runs unattended.
9. Text is checked for private content before it is published, not after. The home-path scan
   finds only the home-path strings it is configured with; a clean scan says nothing else about the
   content. The author reads the exact bytes for private content before publishing them.
10. A lead merges its own pull request with its repository's merge command (owner ruling,
    2026-11-15); the owner merges anything else.
11. Each agent step starts in a herdr-app tab: Codex as `codex-hc`, Claude through its launcher,
    both opened with `herdr-app do tab.new` and driven with `hc send`, `hc keys` and `hc read`.
    Inside that session, subagents and subagent teams are allowed (built-in `/simplify`, a
    fresh-context review subagent). Never start an agent step with `claude -p`, `codex exec`, the
    non-interactive `codex review` or `hc run`. A task (not an agent step) may make one one-shot
    model call when it sets a spend cap, restricts the model's tools and has a fallback for when the
    call fails (owner ruling, 2026-11-17). If `herdr-app ls` fails, stop and ask the owner. Close a
    tab when its step is done.
12. Every public write (docs, a commit, a spec, a ticket, pull-request text, an edit or a comment)
    is sent only after the home-path scan and the author's own read of the exact bytes for private
    content, plus the owner's OK where a step asks for it. The order is push, open the pull
    request, merge.
13. A step is done on an observed result: the verify output, a passing test run, a finding checked
    against the diff. A read that failed is reported as unreadable, never as "nothing found".

## The chain

Before the first ticket in a repository, `/work` runs setup once: `setup-matt-pocock-skills`, then a
`## Workflow facts` section (see [skills](skills.md)).

| # | Step | Who starts it | Produces | Person's gate | Review |
|---|------|---------------|----------|---------------|--------|
| 1 | `/grill-with-docs` | The owner, in a fresh session | Shared understanding, glossary terms, ADRs | Confirms the summary | None required |
| 2 | `/to-spec` | The owner, same session | One spec issue | Signs off the spec | Optional document review of the local file before it is published |
| 3 | `/to-tickets` | The owner, same session | Vertical-slice ticket issues, blockers first, each with seams and criteria that can fail | Approves the breakdown | Optional document review of the ticket bodies |
| 4 | `/implement owner/repo#N` | The owner or coordinator, one worker tab per ticket | Changes in the worker's worktree, tests first at the agreed seams | None: commits need no approval | None required |
| 5 | Branch review (optional) | A Codex tab, when the lead asks for one | Findings against the acceptance criteria | None: findings are hypotheses | Optional: the base-branch diff with the criteria supplied |
| 6 | `/pr` | The worker writes the body to a file | Title and body: summary, evidence, merge danger, blast radius | None | Home-path scan and the author's read of the diff and the text for private content |
| 7 | Close-out | The coordinator, after the lead merges (or earlier on a shared branch, see [ship](ship.md)) | Issue closed, roadmap line ticked; worktree removed only after the merge | The merge, or a spec's early-close rule in [ship](ship.md) | None |
| 8 | `/ticket-retro` | The owner | Lessons for the ticket plan; changes as normal pull requests | Approves any change | As any pull request |

`/implement-spec` runs step 4 for every open ticket of a spec, frontier first. Off the chain:
`triage` is for issues other people filed; `diagnosing-bugs` replaces step 1 for a bug;
`wayfinder` comes before step 2 when the work spans many sessions.

## Rounds

A round is one queue item the coordinator hands to a lead: a ticket, a spec, a tool round, a wiki
build or a fix series. Its ID is `<repo-or-lane>-<yyyymmdd>-<slug>`. The coordinator records it with
the installed `workflowtools`; replaying a command adds nothing.

- **Hand-off.** In the same step as the lead's brief: `workflowtools round-open --round <ID>`, and
  the ID goes in the brief. When a pull request belongs to the round:
  `workflowtools round-pr --round <ID> --repo <owner/name> --number <N>`. It reads the pull request
  from GitHub first and adds nothing when GitHub cannot (exit 2), so a wrong number never enters the
  round. A round may have none, and one pull request may belong to several rounds.
- **Close.** When the lead reports the round finished (see the close-out in [ship](ship.md)):
  `workflowtools round-close --round <ID> --session <session> [--session <session> ...] --plan <plan or lane page>`.
  It records each pull request's head commit at that moment. Exit 2 means GitHub did not answer
  and nothing was written: run it again, and if the same pull request keeps failing (its repository
  is no longer readable), hand it to the owner. Exit 1 means the round was never opened
  or is already closed. A replay prints the stored close and ignores new `--session` and `--plan`
  values.
- **Retro.** Closing a round makes it owe a retro. Whoever runs the retro (`ticket-retro` or
  `session-retro`) records it by hand until those skills do it themselves:
  `workflowtools round-retro --round <ID> --source <what was read>
  [--source ...] --findings <N> --findings-at <where the findings live>`, plus one `--accepted`,
  `--declined` or `--later <change>` per proposed change, stored grouped in that order; a change
  given twice is refused. Zero findings, or every change declined, still clears the debt. Exit 1
  means the round was never opened, is not closed yet, or a change was given twice. A replay prints
  the stored retro and ignores the new values.
- **Check-in.** `workflowtools report [--repo <owner/name> ...] [--since YYYY-MM-DD]` reads GitHub
  read-only and prints four sections: open rounds (`open-rounds`), closed rounds owing a retro with the inputs the retro
  starts from (`owing-retro`), merges and closed round heads without a matching verify receipt
  (`without-receipt`), and merged pull requests in no round (`merges-in-no-round`). Per-round checks
  compare the head commit recorded at close; per-merge checks compare the pull request's final head
  commit. A commit reads `verified` with a local PASS receipt (or SKIP on a documentation-only change),
  `unknown` with a reason when it carries `Verify-Receipt` for a tree with no local receipt,
  `unverified` (changed after verification) when the trailer's tree hash differs from the commit's
  own tree, or `unverified` when it carries no trailer. Every section reads "unknown" with the reason
  when its store or GitHub listing cannot be read. The two merge sections list only pull requests merged on or
  after `--since` (UTC; default 2026-11-19, when receipts and rounds came into use; `--since 2000-01-01` gives the
  full history); a closed round's heads are checked whatever the merge date.

## Plans

The roadmap lives in the main checkout; ticket plans live in a sibling `<repo>.plans/` folder,
outside every checkout. The coordinator creates each plan and is the only one who writes the
roadmap. A worker starts with `PLAN_ID` set to its plan and never re-creates it.
