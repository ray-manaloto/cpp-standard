# Stage 6: Comprehension Test (re-review of D99-D118)

The earlier Stage 6 report is in git history at a5452af.

**Target:** `docs/designs/environment-standard.md` (1841 lines)

- FeatureRange: lines 1-1513.
- DetailedRange: lines 1514-1841.

**Reviewer:** `egm-comprehension`. It read only the target: no decisions log,
no linked files and no document standard.

## What this proposes

The document sets up one public repository, cpp-standard, which holds four
things:

- a written C++ environment standard;
- a small reference project: a named module plus a reflection-based FIX
  encoder of about 100 lines;
- a reflection canary;
- a mise bootstrap project.

One configuration (mise.toml, several conf.d pins files and a lock file)
produces three environments: a local Tart macOS VM, and Ubuntu 26.10 arm64
and amd64 images. Each environment has three compilers with fixed roles:
clang 23, GCC 16.2 and clang-p2996.

Images and the source-built toolchains are named by a hash of their inputs.
One builder workflow builds them. Only `main` publishes them, through a
separate `publish.yml` that runs no repository code. It uses attestations in
M1a and packslip signatures from M2.

Every environment runs the same gate, `mise run ci`. The gate:

- compares configure-time probes with a committed capability lock;
- enforces 100% gcov-mode coverage with no exclusion markers;
- runs sanitizers and lint;
- is backed by must-fail fixtures.

The work is staged as M0 spikes, then M1a (the critical path to 2026-11-27,
Linux first), then M1b-M5, which can be cut, in a dated cut order.

## How the existing system works, per this document

Today, setups have been rebuilt across four earlier repositories, and the
compiler source has kept switching between Homebrew, conda and apt. Agents
collided in shared repositories and in the dotfiles, and rulings were never
enforced, so the glaze FIX work stalled.

Under the proposed trust model, no human reviews ordinary PRs (D101):

- Agent PRs merge through a merge queue once the required hosted checks pass
  and a separate agent session has approved each commit.
- Most Renovate PRs merge on green. Major compiler bumps and capability-lock
  changes wait for the owner.
- Self-hosted PC and Mac runners (from M2 and M3) accept only `main` jobs of
  allowlisted workflows. A job-start hook inside each runner VM image
  enforces this.
- From M2, a short list of "trust roots" needs the owner's code-owner
  review.

Toolchains are fetched at job start by one rule: `main`'s release, else a PR
or merge-group cache or artifact, else a rebuild.

**Author's check of the paraphrase:** it matches the intent. It reads the
fetch rule in its M2 form, which is finding 4.

## Findings: FeatureRange (1-1513)

### 1. Major: decision range and inline gists

**Where:** lines 4-5 and 38-39, and throughout.

- The status line and the Inputs line say D1-D113. The body cites D114-D118.
- D106 appears only in the status line.
- Many key rules are stated only as "(Dnn)", with no summary in the text.
  Line 94 is an example: "since D101 'reviewed' means…".

### 2. Major: the fence rests on a proposal and on a commit review nothing enforces

**Where:** lines 94, 127, 871-876, 991-995 and 1048-1050.

- The fence definition depends on D107, which is still a proposal. The design
  never says what changes if D107 is rejected.
- §6 names the agent's commit review as a guard. No required check, ruleset
  or hook verifies it, so as written it is a convention, not a guard.

### 3. Major: "publish job" means three different things

**Where:** lines 511-526, 613-617, 922 and 1550-1551.

- The term covers `publish.yml`, the `builder.yml` PR publish job, and the
  bootstrap "minimal builder.yml (one publish job, on … pull_request …)".
- Step 5 says "the publish job posts a commit status" on PR and merge-group
  commits. `publish.yml` runs only on `main`, so this cannot be that job.
- "Only `main`'s builder publishes" seems to contradict a publish job that
  triggers on `pull_request`.

### 4. Major: M1a and M2 trust states contradict each other

**Where:** lines 92, 283, 302, 1380 and 1498.

- The glossary "Fetch rule" (line 92) and CUJ 2 (line 302) describe the M2
  state without naming a milestone: "signed release… PR run's artifact (merge
  groups)".
- CUJ 1 (line 283) says packslip checks the signature of "`main`'s builder".
  The signer is now `publish.yml`.
- Alternatives (line 1380) rejects "GitHub attestations for toolchains too",
  yet M1a attests toolchain tarballs (D116).
- The risk row at line 1498 has a stale trigger (`+hash` versions, settled
  by D89) and a stale fallback (GHCR).

### 5. Major: the gate checklist and `main` runs are underspecified

**Where:** lines 71, 207-215, 801-823 and 1649-1650.

- No file, issue or format holds the "gate checklist", and no planned file
  produces it.
- `ci.yml` runs only on `pull_request`, `merge_group` and
  `workflow_dispatch`, so it is unclear what "a green `mise run ci` on
  `main`" is.
- The fixtures "run daily", but no workflow is said to schedule them.
- It is unclear whether `ci` includes `ci-must-fail`.

### 6. Major: the pins fragments are counted three ways

**Where:** lines 363, 385-386 and 644.

- Line 385 says three fragments, line 644 says five, and the diagram shows
  four.

### 7. Major: golden-image retention contradicts G1

**Where:** lines 165-169, 618-622 and 1801.

- G1 says an old commit is reproduced by pulling its images. Yet `vm:golden`
  keeps only the newest 2 local golden images, and the exception for older
  commits is not stated.

### 8. Nit: the M2 glossary entry misses the trust change

**Where:** line 69.

- The entry should say that M2 entry also turns on the trust roots, packslip
  and code-owner review.

### 9. Nit: "post-merge macOS run" names the wrong workflow

**Where:** lines 71, 1705 and 1805.

- The run is `mac-gate.yml`, not `post-merge.yml`. Add a sentence mapping
  each name to its workflow file.

### 10. Nit: the `gcc-macos-macos-arm64` example looks like a typo

**Where:** lines 490 and 1808.

- One clause on the naming scheme would show it is not.

### 11. Nit: "golden" means two things

**Where:** lines 711 and 1601.

- `macos-golden-gate-vanilla` is Cirrus Labs' image name. It is not the
  local golden image.

### 12. Nit: an unexplained reference

**Where:** line 898.

- The reference "rejifald/faber ADR-0059" has no link and no explanation.

### 13. Nit: the cap file and its citations

**Where:** lines 79 and 1825.

- `review/cap.toml` is not in the file plan.
- `review:cap` cites D23 in one place and D113 in another.

## Findings: DetailedRange (1514-1841)

### 14. Major: setup step 9 deletes something never introduced

**Where:** lines 1591-1593.

- The step deletes the `audit` environment and `RULESETS_PAT`, but nothing
  in the document says why they exist.

### 15. Major: M0 (i) tests mechanisms M1a no longer uses

**Where:** lines 1167-1186 and 1584-1588.

- M0 (i) blocks M1a, but it proves packslip signing and the merge-group leg,
  which now arrive in M2.
- It does not say what M1a does if (i) fails.

### 16. Major: setup step 6 contradicts §6

**Where:** lines 1568-1572 and line 965.

- Setup step 6 has a PR from the owner's login add CODEOWNERS.
- §6 says trust-root changes never come from the owner's login.
- The two are reconcilable before M2, but the text does not say so.

### 17. Major: M0 outcomes are recorded unevenly

**Where:** line 1617.

- The (f) pass line mixes criteria, a fallback and the results.
- (g) says "taken".
- (h) shows only in a file-plan row.
- The other M0 checks have no status.

### 18. Nit: the `os` field disagrees

**Where:** lines 1665-1666, against lines 662 and 1750-1753.

- One place says `os = "linux"`; the others say `os = ["linux"]`.

### 19. Nit: the marker scope disagrees

**Where:** §5, the glossary, the `gate/policy` row (line 1689) and the jouet
rule (line 1781).

- §5 and the glossary say `src/**`. The other two say `src/**` and
  `tests/**`.

### 20. Nit: the `must-fail` job's file list is unclear

**Where:** line 1700.

- The job runs on "owned-root PRs", but it is unclear which list the job
  reads to detect one.

### 21. Nit: "reviewed by whom" for the first commit

**Where:** line 1534.

### 22. Nit: D53's cuts are not summarized

**Where:** line 1611.

### 23. Nit: "Drafted with EGM"

**Where:** line 1841.

- This is fine as written. No action needed.
