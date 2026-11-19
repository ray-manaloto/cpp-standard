# Directory Update Log

## 2026-11-04
* **Creation**: a generic rewrite of the agent workflow protocol (v1.9) for user scope: the rules,
  the chain, shipping, cross-review and the skill table. Nothing project-specific is kept.

## 2026-11-07
* **Added**: cross-review's "Waiting on the pane" section. It says to wait with `hc wait` or
  `hc send --wait`, not with a sleep loop over `hc read`, which can miss the answer. It also says to
  word a brief's limits so the pane's read-only shell stays allowed.

## 2026-11-18
* **Added**: reconciliation and verify-receipt reporting (#162). `workflowtools report [--repo ...]`
  reads merged pull requests from GitHub (never writing), joins them to rounds, and adds the
  `without-receipt` (per-round close head and per-merge final head) and `merges-in-no-round`
  sections; `chief-of-staff` and workflow.md check-ins name the report command.
* **Changed**: ship.md's Verify and Commit steps (#161). `workflowtools verify-receipt` remembers the
  tree before `/verify` and `--verdict` saves the verdict against it; `workflowtools verify-commit`
  compares the staged tree at commit and adds the `Verify-Receipt` trailer. SKIP needs a change that
  is documentation only since the branch left the default branch. The pull request step names the
  verdict line that `repotools pr-create` warns about when it is missing.
* **Added**: retro debt (#160). A closed round owes a retro until `workflowtools round-retro` records
  one, with the sources read, the finding count (zero is valid), where the findings live and one
  disposition per proposed change. `workflowtools report` gains its second section, closed rounds
  owing a retro. See Rounds in workflow.md.
* **Added**: the Rounds section in workflow.md and the round close in ship.md's close-out (#159). The
  coordinator opens a round at the hand-off, adds its pull requests and closes it with
  `workflowtools round-open`, `round-pr` and `round-close`; `workflowtools report` lists open rounds.
