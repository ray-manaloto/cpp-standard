# Goldfish Annotated Review Report: Stage 7, round 1

Status: resolved

The earlier report (`Status: resolved`, D42-D98 review) is in git history at
a5452af.

**Target:** `docs/designs/environment-standard.md` (lines 1-1533)

**Findings:** `critic_report.md`

## Prioritized Findings & AI Suggestions

### Questions for the owner first

These findings have more than one defensible fix, so the owner chooses before
any edit.

- **des-1-7, des-1-8, str-1-outside (Major).** These three are one question:
  which files besides the D108 list must be trust roots from M2, so that a
  merged agent PR cannot change *what* is signed (`artifact:build`,
  `toolchains/*/build.sh`) or *the checker* (`gate:policy`, the fixture
  runner, `ci.yml`)?
  - Suggestion: **PROPOSE FIX**, with the owner choosing the list.
  - Research: rulesets cannot pin `ci.yml` to `main`'s copy without
    Enterprise Cloud.
- **des-1-11 (Major), consteval coverage.**
  - Suggestion: **PROPOSE FIX**. State the limit in the risk table. Requiring
    a named `static_assert` per consteval function is the owner's call.

### Blocker

#### [des-1-1] [`egm-design`] - Severity: Blocker

- **Affected Scope:** lines 504-506, 937-938, 1517.
- **AI Suggestion:** PROPOSE FIX.
- **Justification:** the claim is accurate. `workflow_dispatch` takes inputs.
  The agent App has `actions: write`, and the hook checks only the
  ref/event/workflow.
- **Proposed Edit:**
  - §2 step 3 and §6 add a rule: every self-hosted workflow takes no SHA
    input, or refuses any SHA that is not an ancestor of `origin/main`,
    before checkout.
  - The M2 entry gate adds a negative test that dispatches with a PR head
    SHA.
  - Add a risk row.
  - New decision D122.

### Majors: PROPOSE FIX

| ID | Proposed edit |
|---|---|
| des-1-2 | `toolchain:fetch` verifies the attestation in Actions too. It checks that `inputs-hash.txt` equals the computed hash, and refuses more than one release with the same title. §2 states the M1a and M2 states separately. Reword lines 588-594. Part of D122. |
| des-1-3 | The release lookup pages through every release with `gh api --paginate`, matches the title exactly, and fails if it finds more than one. Add a risk row for a missed lookup. Part of D122. |
| des-1-4 | `ci.yml` gate and `must-fail` jobs `needs:` the `artifact-check` job, so they fetch after the builder finished. Add an M1a risk row for the merge-queue rebuild cost of input-changing PRs. |
| des-1-5 | Every runner-PAT mention follows D117: the PC runner App registers the runners from M2. Rewrite or remove row 1523. |
| des-1-6 / sty-1-M1 | §1, §10 and the risk rows state each M0 result with its decision (D103-D106, D121): (g)'s fallback taken, (b)/(c)/(h)/(j) passed, (j) on the stand-in, proposed D106. Include (h)'s packed size of 682 MiB against the 10 GB cache. |
| des-1-9 | New open question Q6: Renovate's identity and where its credential lives. Not a repository secret, which same-repo PR workflows could read. The Mend-hosted app is the leading option. Due before M1b. |
| des-1-10 | §4: sccache caches clang module compiles only partly. mozilla/sccache#2650 (CMake 4.3+ `@modmap` response files are not cacheable) is still open, and #2216 reported a stale-cache bug. So module compiles are treated as uncached, and the gate's clean build does not rely on sccache. Cite the sources. |
| str-1-1 | Add a blank line, so the security paragraph leaves fetch item 4. |
| str-1-2 | Give §2 step 4 "M1a state" and "M2 state" H4s. Give §6 H4s for The fence, Trust roots, Owned roots, Credentials, Identities, Settings check. |
| str-1-4 | Add Alternatives entries for D101/D108/D120: code-owner review on all owned roots, trust roots from M1a, a required commit-review check. Each with its rejection reason. |
| str-1-5 / sty-1-M11 | Replace "reviewed/unreviewed" with "`main` code / not yet on `main`" at lines 391, 867, 871, 1240, 1460. |
| str-1-6 / sty-1-M10 | Label the overview diagram "M2 state". Show the trust roots apart from the owned roots, with M1a attestation and M2 packslip. |
| sty-1-M2 | Narrow line 52 to say decisions and research cite their sources, and cite or date the figures listed. |
| sty-1-M3 | The 66,000-line count came from the brainstorm session, not the brief. Reword to "counted with `tokei` on 2026-11-12 during the brainstorm", without the brief link. |
| sty-1-M4 | G1 says "bumped daily by Renovate, subject to the `minimum_release_age` cutoff and the D56 owner wait". |
| sty-1-M5 | G5 says "by M3". |
| sty-1-M6 / des-1-22 | G3 says "the same result for the checks both environments run, per the capability lock". |
| sty-1-M7 | G8's measure adds "no paid runner minutes are used". |
| sty-1-M8 / str-1-7 | Change line 355 to "D26 to D121". |
| sty-1-M9 | Line 388 says "each artifact tag is published once, from `main`, by `publish.yml`". |
| sty-1-M12 / M13 | Use one set of terms: "attested" (M1a) and "packslip-signed" (M2). Scope line 591 to "never becomes `main`'s release from a PR artifact". |
| sty-1-M14 | State the fetch rule once, in §2, and have the glossary, CUJ 2 and the risk row point to it. |
| sty-1-M15 / des-1-14 | Add "before M2, or outside the trust roots" at lines 984, 1004, 1051-1054 and 1243. |
| sty-1-M16 | Make lines 420, 986 and 1345 cross-references to §7. |
| sty-1-M17 / des-1-19 / str-1-3 | Open questions gain Q7 (D106) and Q8 (D107). Mark every D107 citation "proposed". The Settled Ubuntu row points to Q8. |
| sty-1-M18 | Lines 660 and 1046 use D113's reason for the split. |
| sty-1-M19 | Line 812: "one must-fail fixture for each check in the list below". |
| sty-1-M20 | One promotion rule, zero findings plus the owner's OK, at line 808. Line 1307 points to it. |
| sty other | Line 56: "the owner confirmed these three; the decisions log records the rest". Line 84: list `gate-removals.toml` in the owned roots. Line 1133: "for rows with a run". Line 1508: "until fixed or reverted". Line 1292: state the arithmetic. |

### Nits

- **PROPOSE FIX** for the cheap ones:
  - the `pins.toml` fields against `pins:validate`;
  - one dispatcher (`publish.yml`);
  - CUJ 2 says "PR and merge-group jobs";
  - a cross-release apt.llvm.org risk row;
  - the missing (i) tags;
  - "Rejected by owner" kept only where the owner decided;
  - the risk "Kind" values limited to unproven, dependency, limit, accepted,
    mitigated and scale;
  - the row reference at line 1513;
  - the macOS wording;
  - the garbled sentence at line 1497;
  - "young" dated;
  - the credentials sentence says "only stored secret".
- **DECLINE**, recorded only:
  - full re-wrapping;
  - horizontal rules;
  - converting the research paths to links;
  - reordering §10;
  - CUJ "Then" formatting;
  - the glossary refiling;
  - renaming `gcc-macos`, which would change artifact names;
  - the subjective wording nits.

## Status

Resolved on 2026-11-13. The owner chose the question fixes (D122-D124) and
"Auto accept" for the rest.

- **Applied:** the Blocker, every Major, and the cheap Nits, as D122-D124
  plus text edits.
- **Declined (recorded only):** the eight Nits listed above.
- **Not applied:** des-1-18 (weak rejections), the garbled-sentence Nit and
  the row-reference Nit. Their line numbers no longer point at a clear
  target. Round 2 sees the current text and can raise them again.
- **Contested or escalated:** none.

`mise run check` passes after the edits.

## Round 2

Status: resolved. The owner chose the recommended fix for each Blocker
(D125-D127), called the D56 wait a convention (D128), and chose auto accept
for the rest. Every PROPOSE FIX was applied, and the two partial contests
were applied as their proposed text (a risk row, an alternative and a stated
limit). The declines stand. `mise run check` passes.

Round 2 is not clean: it has 4 Blockers and 41 Majors. The loop cap is 5
rounds.

### Questions for the owner

- **des-2-1 and des-2-2: what a merged agent PR can still change from M2.**
  - **Verified:** §6 says so in its "cannot change what `publish.yml`
    signs" sentence.
  - **Proposed:** correct that claim. Allowlist toolchain sources by URL
    prefix, not by host. Add these to the trust roots from M2:
    - `pins-allowlist.toml`;
    - `toolchain:fetch`;
    - `image:verify`;
    - `.mise/tasks/vm/**`;
    - the PC image build task.
- **des-2-3: PR workflows with write tokens.**
  - **Proposed:**
    - PR images travel as workflow artifacts, not GHCR tags;
    - a `pins:validate` rule fails any workflow file that is not on an
      allowlist, and the allowlist is a trust root from M2;
    - a risk row records that a required check can be faked by a new job
      with the same name. Pinning the check to one workflow needs
      Enterprise Cloud.
- **des-2-4: agents on the Mac host.**
  - **Proposed:** an M2 entry condition. Agents run in the dev VM, or as a
    separate macOS user who cannot read:
    - the PC SSH key;
    - the runner App key;
    - the Docker context.
  - Until M2, record it as an accepted risk.
- **des-2-10: the D56 owner wait cannot be enforced.** The agent App can
  queue a waiting Renovate PR itself.
  - **Proposed:** call it a convention, as D120 did for commit review.

### PROPOSE FIX (once the owner has decided)

**Design:**

- des-2-5: attest `inputs-hash.txt`, or check the attested subject name.
- des-2-7: give the fetch rule for `main` jobs by milestone, and state the
  D112 skip rule in the `post-merge.yml` row.
- des-2-8: add `artifact/build` and the bootstrap compiler to the hash rows,
  and name each exclusion with its reason.
- des-2-9: the `merge_group` builder saves the cache on the queue ref, which
  becomes source 2 in M1a.
- des-2-11: record the self-disable limit, and that the owner notices a
  missing digest.
- des-2-12: add a risk row for the Org-admin App's key.
- des-2-14 to des-2-18.

**Structural:**

- str-2-1 to str-2-5, str-2-7 to str-2-9;
- str-2-6, partly: §10 gets a one-line scope and a link for each later
  milestone.

**Style:**

- the Majors sty-2-1 to sty-2-23;
- the cheap Nits.

### CONTEST, partly

- **des-2-13: release lookup cost.** Releases grow only when an input hash
  changes, not daily. That is a few hundred a year, so a lookup costs a few
  pages. Proposed:
  - record the request budget in a risk row;
  - list the hash-as-prerelease idea as an alternative.
- **des-2-6: gate callees come from the PR.** Partly covered by D123.
  Proposed: name the gate's task set, and record the rest as a limit.

### DECLINE

- str-2-6's reordering of §10, as in round 1;
- horizontal rules (str-2-16);
- link-style unification (str-2-13);
- section-heading IDs (str-2-19);
- subjective wording.

## Round 3

Status: resolved. The owner chose the small closes and accepted the rest
(D129), draft PRs for `linux:run` (D130), and auto accept for the
correctness fixes (D131). The PC runners go in a dedicated runner group,
because the org has 20 public repositories. The design, structural and style
Majors are applied. These Nits are left for round 4 to raise again if they
still matter:

- Alternatives labels;
- link styling;
- the order of the risk rows;
- horizontal rules;
- line wrapping.

`mise run check` passes.

Round 3 has no Blocker but 37 Majors, so it is not clean. The design
critic's Majors keep finding new edge cases in the M2 trust model: each
round adds trust roots or checks, and that conflicts with "don't
over-engineer". The owner chooses how far to go.

- **PROPOSE FIX: correctness, cheap.**
  - des-3-1: `builder.yml` takes no SHA input. The post-merge workflows
    accept only the SHA from the builder run that `publish.yml` verified.
    The M2 review reads `git log -p`.
  - des-3-3: put `inputs-hash.txt` inside the archive.
  - des-3-5: register runners at the org level.
  - des-3-7: one gcovr gate per compiler.
  - des-3-9: the lookup skips drafts.
  - des-3-4: `ci.yml`'s `workflow_dispatch` follows the hosted-job rules.
  - All 6 structural Majors and all 22 style Majors.
- **Owner's choice:** des-3-2, des-3-6 and des-3-8. Each would widen the
  trust roots or add a new check.

## Round 4

Status: resolved.

- **Tally:** 0 Blockers and 32 Majors (design 10, structural 6, style 16).
- **Owner's choices:** fix round 4 and run round 5 as the final round, then
  fix the bugs and add the M2 gate items.
- **D132:**
  - replaces D131's tip-only rule, which raced with merges: the inputs
    hash at `main`'s tip decides instead;
  - adds the publish-run check, per-tag concurrency, decoy-tolerant fetch,
    a retention job without `packages: write`, and a `must-fail` that
    reads `main`'s list;
  - names five M2 entry gate items.
- **Structural Majors:** applied only where cheap (the Settled row, links).
  Splitting §6 into H3s, turning the §2 steps into headings, risk IDs and
  regrouping the alternatives are recorded as declined. They are layout
  only, and round 5 may raise them again.

`mise run check` passes.

## Round 5 (final)

Status: resolved. Stage 7 is closed under D133.

- **The Blocker (des-5-1)** is now an M2 entry gate item: a dedicated build
  user that cannot read host credentials, and no repository mise config.
- **The correctness Majors** are fixed:
  - the D132 Dockerfile item is narrowed;
  - `publish.yml` gets a concurrency group;
  - same-title releases resolve to the lowest version;
  - one shared hash script;
  - an image inputs-hash label;
  - a replay refusal for old publish runs;
  - the Org-admin key is added to D127;
  - the status-job and push-trigger items;
  - `owned-roots.txt` becomes a trust root;
  - the permissions fixes.
- **The structural and style Majors** are applied.
- **Residuals, recorded and not applied** (Stage 8 reads the whole
  document again):
  - splitting §6 into H3s;
  - the §2 steps as headings;
  - risk-row IDs and Kind legend;
  - grouping the alternatives by section;
  - one rejection label;
  - link styling;
  - line wrapping;
  - horizontal rules.

`mise run check` passes.
