# Stage 5: Initial Zoom Out Review (re-review of D99-D107)

The earlier Stage 5 report (795-line design) is in git history at a5452af.

**Target:** `docs/designs/environment-standard.md` (full file, 1804 lines,
`main` at fae7325)

**Reviewers:** `egm-zoom-out` (Zoom-Out standard) and `egm-inventive-catalyst`,
run in parallel.

**GoldfishContext:**

- `level-1/decisions-log.md`
- `level-1/concepts_brief.md`
- `level-1/sources/ccache-pr-1523.json`
- `level-1/sources/mise-CONTRIBUTING.txt` (saved as `.md` during the review; renamed so the markdown lint skips the upstream copy)

The owner left out the earlier review reports, so this review does not depend
on them.

**Verdict:**

- The zoom-out reviewer requests changes: 2 Blockers, 5 Majors and 4 Nits.
- The catalyst found 5 Majors and 1 Nit.
- Working separately, both reached the same central point. Since D101 the
  trust machinery enforces nothing, yet it still costs time on a two-week
  critical path.

Both reviewers checked the saved sources:

- ccache PR #1523 is still an open draft, so the ccache rejection holds.
- mise takes no outside PRs, so the "don't fork mise" rejection holds.

## Zoom-out findings

### Z1. Blocker: the two-tier trust model no longer enforces anything

- **Scope:**
  - §6: The fence (848-852), Credentials (886-899) and Owned roots
    (935-960).
  - §7: Merge rule (1002-1017).
  - Risk rows 1445-1448 and 1454.
  - D101 and D107.
- **Problem:** the owned-roots/pins split exists so that a trusted file guards
  an untrusted one. The split covers:
  - the O/P marks and CODEOWNERS;
  - `pins-allowlist.toml` and `gate-policy.toml`;
  - `pins:validate` and `gate:policy`.

  Since D101, one agent PR can change a guard and the file it guards together,
  and merge on the checks. For example:
  - `pins-allowlist.toml` with a pin;
  - `gate-policy.toml` with a preset;
  - `cmake/probes.cmake` with the capability lock;
  - `builder.yml`, `post-merge.yml` or `repo-verify.yml` themselves.

  So the design pays for the trust model but gets none of its enforcement.
- **Fix:**
  - Add one small, real gate on only the files whose compromise reaches the
    owner's hardware or signing identity:
    - `builder.yml`;
    - the workflows on the self-hosted allowlist;
    - `repo-verify.yml`;
    - `runner/**`;
    - the rulesets.
  - The gate can be either:
    - code-owner review on that short list; or
    - a required check that fails when a non-owner PR touches the list.
  - Make restoring the gate an M2 entry condition. There are no self-hosted
    runners before M2, so M1a loses nothing.
  - The rest of the owned-roots list can then honestly be called
    documentation, or be dropped.

### Z2. Blocker: the settings check forbids restoring code-owner review

- **Scope:**
  - §6 daily settings check (967-977, especially 969-971).
  - File plan: `repo:rulesets`.
- **Problem:** `repo:rulesets --verify` fails if code-owner review is turned
  back on. That makes the interim D101 choice ("for the time being") an
  enforced invariant. To restore Z1's safety, someone must first edit an
  owned task, and the check stays red until they do.
- **Fix:** check that the protections are present (the merge queue, the
  required checks, no extra bypass actors). Do not forbid adding a
  protection.

### Z3. Major: artifacts use two stores and two trust paths

- **Scope:**
  - §2.2 (480-494) and §2.4 (505-594).
  - Alternatives: "GitHub attestations for toolchains too" (1334-1337).
  - File plan: `toolchain/fetch`, `artifact/names` and the M1b tag ruleset.
- **Problem:** the design uses:
  - two stores: Releases for toolchains and GHCR for images;
  - two trust paths: packslip and attestations;
  - four fetch sources for toolchains.

  Releases force a chain of workarounds:
  - a semver scheme with `-r.<n>` variants;
  - a title search over `gh release list --limit 1000`;
  - an ordering for immutable releases;
  - a tag ruleset;
  - a `salt` field;
  - an `actions/cache` scoping workaround.
- **Fix:** publish toolchain archives as OCI artifacts in GHCR, tagged by the
  inputs hash and checked by the same attestation verify. This removes the
  version scheme, the title lookup, the cache leg, the run-id lookup and the
  tag ruleset.
- **If packslip stays:** if jdx-first (D10/D11) is the real reason for
  packslip, say so as the trade-off. At a minimum, drop the `actions/cache`
  leg and use `pr-` GHCR artifacts instead.

### Z4. Major: M1a carries trust work that buys little before M2

- **Scope:**
  - §10 critical path item 6.
  - M1a PR order 3 and 6.
  - Setup steps 9-10.
  - §6 Credentials and risk row 1446.
- **Problem:** M1a carries:
  - packslip signing;
  - a four-source fetch;
  - attestation verify;
  - the `pr-` namespace;
  - a JWT minter;
  - a verifier that needs an Admin-write PAT shared with every future
    project.
- **Why the PAT is avoidable:** the verifier needs that PAT only to read
  `bypass_actors`. In a single-admin org, dropping that field lets the check
  run on `GITHUB_TOKEN`. That removes the `audit` environment,
  `RULESETS_PAT` and the D107 `repo-verify` risk.
- **Why the signing buys little:** before M2, nothing outside hosted runners
  uses `main`'s signatures. Since D101, any green PR can change
  `builder.yml`.
- **Fix:**
  - Move packslip and the merge-group leg to M1b or M2, or adopt Z3.
  - Spend the freed days on the encoder and the gate.

### Z5. Major: the Technical Plan drops into implementation detail

- **Scope:**
  - §2 (425-604).
  - §6 runner enforcement and credential storage (862-934).
  - File plan rows `agent/token`, the outrunner files and the Dockerfiles.
- **Problem:** the plan quotes:
  - exact `gh` flags;
  - upstream source line numbers;
  - `retention-days: 7`;
  - JWT lifetimes;
  - `$GITHUB_OUTPUT` fields;
  - canonical-JSON rules.

  The fetch-rule paragraph alone is about 35 lines.
- **Fix:**
  - Move the evidence to the decisions log.
  - Move command lines to runbooks or task files.
  - Keep components, data flow and trust boundaries in the design.

### Z6. Major: the design describes its history, not its current state

- **Scope:**
  - Status (4-11).
  - Inputs (43), which still says "D1 to D102".
  - Setup steps 5, 6 and 10.
  - The §6 owned-roots preface.
- **Problem:**
  - Setup step 6's "First, CODEOWNERS (D100)" rationale no longer applies
    after D101.
  - Its done-when check, a `BLOCKED` App PR, cannot happen now.
  - Step 10 says its content moved to step 7.
- **Fix:** rewrite these sections as the current procedure. Leave the history
  to the decisions log.

### Z7. Major: the vcpkg triplets are speculative

- **Scope:**
  - §4 Dependencies (736-741).
  - File plan: `triplets/*.cmake`, `vcpkg.json` and `vcpkg/bootstrap`.
- **Problem:** the only dependency is the header-only ut library (D52). Yet
  the plan has nine arm64 triplets, including sanitizer variants, plus amd64
  copies. None of them proves anything, because no library builds through
  them.
- **Fix:**
  - Keep one triplet per compiler and standard library, three in total.
  - Add sanitizer triplets with the first compiled dependency, in Level 2.

### Z8. Nit: the probes copy more of the parked catalogue than they need

- **Scope:** file plan: `cmake/probes.cmake` and `gate/policy`.
- **Fix:**
  - Copy only the `check_*` calls that §4 lists.
  - In `gate:policy`, compare plain strings instead of calling
    `_profile_undone_in` through `cmake -P`.

### Z9. Nit: the digest's agent count has no source until M5

- **Scope:**
  - §9 (1041-1059).
  - The G6 measure and CUJs 5 and 6.
  - `review/cap`, which is scheduled for M5.
- **Fix:** do one of these:
  - move `review:cap` into M1b, next to the digest;
  - drop the agent count from the Level 1 G6 measure.

### Z10. Nit: `vcpkg/bootstrap` is agent-editable in §6 but not in D76

- **Scope:** §6 (944-946) and D76.
- **Fix:** record the addition in the decisions log, or remove it from §6.

### Z11. Nit: D74's reason for a separate `tools.toml` no longer holds

- **Scope:**
  - §3 (626-651).
  - Alternatives: "Folding [tools] into mise.toml" (1374-1375).
- **Problem:** D74 kept `tools.toml` separate because "the daily tools PR
  would need the owner". After D101 that is no longer true.
- **Fix:** restate the reason for the split: parallel edits and hashing per
  layer.

## Inventive-catalyst findings

### C1. Major: "no human approval" is treated as all or nothing

- **Problem:** this has the same root cause as Z1. About five trust-root files
  merge on the checks:
  - `builder.yml`;
  - `post-merge.yml` and `mac-gate.yml`;
  - `repo-verify.yml`;
  - `runner/hook/job-started.sh`.

  The only mitigation is a look after merge. It has no mechanism until the M1b
  digest, and the digest is item 3 on the cut list.
- **Resolution (segmentation):**
  - Move publishing and signing into a small `publish.yml`. Make it the only
    identity that packslip and `gh attestation verify` accept, so that
    `builder.yml` stops being a trust root.
  - Add one required `trust-roots` check. It fails when a PR touches
    `publish.yml`, the self-hosted allowlist, `repo-verify.yml` or
    `runner/**`, unless the owner pushed or approved the head commit.
- **Alternative (extraction):** the runner hook checks the workflow SHA
  against an allowlist on the host that only the owner updates. This option
  is unverified: it depends on the hook context exposing the SHA.
- **Liabilities:**
  - A second identity to pin and test.
  - The owner is back on the path for rare trust-root edits, which come in
    bursts during M1a.
  - With the hook option, a stale allowlist turns runs red.

### C2. Major: one PR can drop a check and its negative control together

- **Scope:**
  - §1 capability lock.
  - §5 negative controls.
  - The probe-and-lock risk row (D42, D107).
- **Problem:**
  - Whether a fixture applies comes from the capability lock.
  - Removing a capability therefore also turns off the must-fail fixture that
    would catch the removal.
  - So one PR can remove a check and its negative control at the same time
    and stay green.
- **Resolution (a one-way ratchet):**
  - Additions to the lock merge freely.
  - A removal needs a matching entry in an owned `capability-removals.toml`.
    `gate:policy` fails without that entry.
  - The fixtures for a removed capability stay applicable until the entry
    exists.
- **Liabilities:**
  - One more owned file, and a lock-diff parser in `gate:policy`.
  - If agents can write the removals file in the same PR, it is only an audit
    trail. So the file belongs on C1's trust-root list.

### C3. Major: `main` consumers race the `main` toolchain build

- **Scope:**
  - §2 Build and fetch rule.
  - §6 job table.
- **Problem:**
  - A `main` job uses only the `main` release, so it fails on a hash that
    has no release yet.
  - `post-merge.yml` and `mac-gate.yml` start on push, but a p2996 rebuild
    takes 61-76 minutes or more.
  - Toolchain inputs merge daily, so `main` gets a red window every day. That
    noise drowns the red post-merge signal that several risk rows rely on.
  - §2 step 3 and §6 also disagree on whether `builder.yml` runs on `push`.
- **Resolution (inversion):**
  - After it publishes, the publish job dispatches `post-merge.yml` and
    `mac-gate.yml` with the head SHA.
  - Keep the push trigger only for commits that change no artifact inputs.
  - Settle the trigger list in one place.
- **Liabilities:**
  - One more hop, and `actions: write` on the publish job.
  - A failed publish shows as a missing run instead of a red one, so the
    digest must flag it.

### C4. Major: `RULESETS_PAT` lives where agent-merged code can use it

- **Scope:**
  - §6 Credentials (D92).
  - The `repo-verify.yml` risk row.
- **Resolution (extraction):**
  - Move the ruleset audit into one owner-only audit repository with no
    agent App installed.
  - A scheduled workflow there holds the PAT and checks every C++ project.
  - cpp-standard reads that workflow's status with `actions: read`.
- **Simpler option:** Z4 suggests dropping the `bypass_actors` read and using
  `GITHUB_TOKEN`.
- **Liabilities:**
  - A second repository to maintain.
  - The settings checklist then depends on a status read across
    repositories.

### C5. Major: a macOS-only breakage stops macOS work until someone acts

- **Scope:**
  - §2 fetch rule.
  - §7 "macOS builds after merge".
  - The risk rows for Mac GCC and macOS regressions (D62, D85).
- **Problem:**
  - After a bump that breaks the Mac build merges, the fetch falls through to
    a source rebuild.
  - That rebuild fails for the same reason.
  - The risk table promises "keep the last good build", but no fetch source
    provides it.
- **Resolution:**
  - Add a macOS-only fallback to the newest signed `main` release, marked as
    stale. A stale environment never ticks a gate item.
  - Optionally, let the builder open a revert PR itself.
- **Liabilities:**
  - The fallback weakens G1's "tags always resolve", so it must not be used
    on Linux or for the capability lock.
  - Auto-revert needs a retry-once rule and a cap.

### C6. Nit: Renovate and toolchain PRs get no macOS signal before merge

- **Resolution:** add a hosted macOS job that is advisory and not required.
  It builds the PR's Mac toolchain inputs and runs a smoke test. It runs on
  GitHub's hardware, so the fence is not touched.
- **Liabilities:**
  - SDK differences give false results.
  - A GCC bootstrap may come close to the 6-hour job limit.
  - Its artifacts must never be fetched.
  - It is better left as a candidate for M3 or later.

### Areas the catalyst found balanced

- The `main` builder never reuses PR artifacts. Provenance needs this.
- GCC module compiles are not cached. This is an upstream limit.
- The runner hook has no token (actions/runner#2813).
- macOS allows only two VMs.
- The cut order and the Linux-first critical path.
- gcov-mode coverage with `static_assert`.
- One `pins.toml` per toolchain (D85).

## Where the two reviewers agree

- **Z1, C1, C4 and Z4:** D101 left the trust roots ungated.
  - Both reviewers propose a small gate on about five files:
    - the builder or publish workflow;
    - the self-hosted workflows;
    - `repo-verify.yml`;
    - `runner/**`;
    - the rulesets.
  - Neither proposes a human review of everything.
  - Both note the gate is needed only from M2, when self-hosted runners
    start.
- **Z2:** whatever the owner picks for Z1, the settings check must not forbid
  it.
- **C2:** the capability lock needs a one-way rule for removals. Otherwise the
  probe-and-lock risk in D107 also turns off its own negative control.
