# Stage 5 re-audit: Zoom Out after the D108-D113 fixes

The earlier re-audit (916-line design, D42-D47) is in git history at a5452af.

**Target:** `docs/designs/environment-standard.md` (1813 lines, after the
D108-D113 edits)

**Reviewers:** `egm-zoom-out` and `egm-inventive-catalyst`, each with the
previous `zoom_out_report.md` and the same GoldfishContext as Stage 5. This is
Stage 5's one allowed re-audit.

**Verdict:** no Blockers.

- The zoom-out reviewer requests changes.
  - Of the 11 earlier Z findings: 4 are resolved, 2 are deferred to Stage 7,
    and 5 are partly resolved.
  - It raises 5 new Majors and 4 new Nits.
- The catalyst calls C1 mostly resolved, C2 partly resolved, C3 resolved from
  M2, C4 resolved for M1a, C5 deferred and C6 resolved.
  - It raises 3 new Majors and 6 new Nits.
- Both reviewers make the same main point. D108-D111 settle the right
  questions, but in several places the rest of the document has not caught
  up, so a gate or a deferral is declared without being made real.

## Status of the Stage 5 findings

| Finding | Status | What is left |
|---|---|---|
| Z1 / C1 trust model | partly resolved | No step turns the gate on at M2 (R4). The gate covers files but not the code they run with privileged tokens (R1). |
| Z2 settings check forbids gate | resolved | None. |
| Z3 two stores | owner kept Releases (D111) | The Alternatives entry does not name jdx-first as the reason. |
| Z4 M1a trust load | partly resolved | M0 (i) and the M1a file plan still specify the deferred features (R2). |
| Z5 detail | deferred to Stage 7 (D113) | The design does not say so. §2 step 4 grew. |
| Z6 history | partly resolved | Setup step 6's CODEOWNERS sub-step, and "Since D101" / "D107, proposed" wording at lines 94, 862-865, 1016-1017, 1029 and 1398. |
| Z7 triplets | resolved | None. |
| Z8 probes | deferred to Stage 7 | None. |
| Z9 agent count | partly resolved | CUJ 5 and CUJ 6 still depend on `review:cap` (M5). |
| Z10, Z11 | resolved | None. |
| C2 negative control | partly resolved | Fixtures, `expected.toml` and `gate-policy.toml` can still be weakened together (R6). |
| C3 race | resolved from M2 | The trigger list is split across sections. Before M2, each bump builds twice (R9). |
| C4 admin PAT | resolved for M1a | The M2 runner PAT can add a bypass actor that the check skips (R5). |
| C5, C6 macOS | deferred to Q5 | Two rows still promise a last-good fallback (R10). |

## Residual findings (merged from both reviewers)

### R1. Major: trust roots gate files, not the code those files run with privileged tokens

Zoom-out N1 and catalyst N4 raise this.

- **The problem in `builder.yml`:**
  - The `main` publish job in `builder.yml` holds `id-token: write`.
  - It runs `mise run artifact:names`. That task, and `mise.toml`, are
    owned roots, not trust roots.
  - So an agent PR can change the task. After merge, the changed task runs
    with `builder.yml@main`'s signing identity.
- **The same problem in D110:** `cmake/capability-removals.toml` is gated,
  but its checker, `.mise/tasks/gate/policy`, is not.
- **Fix (zoom-out):**
  - The job that holds `id-token: write` runs no repository code: no
    `mise run`, and its names are computed inline. This is C1's small
    `publish.yml`.
  - For D110, either gate `gate/policy` too, or take the removals file off
    the list and call it a record.
- **Fix (catalyst N4):** keep `builder.yml` thin, with a data-driven matrix,
  so that edits to trust roots stay rare in M2 and M3.

### R2. Major: D111's deferral is not carried through

Zoom-out N2 raises this.

- M0 (i) still tests a signed release, `packslip install --identity`,
  branch-signed refusal and the merge-group `run-id` leg. M0-Linux ends on
  2026-11-16 and blocks M1a.
- The M1a file-plan rows `toolchain/fetch` and `artifact/names` still
  specify packslip. So do the Settled "Artifact trust" row, CUJ 2 and risk
  row 1470.
- **Fix:**
  - Cut M0 (i) to the M1a legs: an unsigned release found by its title,
    cache scoping, `bootstrap packages status`, and lock parity.
  - Move the packslip and `run-id` legs to the M2 entry gate.
  - Mark the packslip parts of the M1a rows as M2.

### R3. Major: unsigned M1a toolchains run on the owner's PC

Zoom-out N3 and catalyst N1 raise this.

- §3 puts the owner's devcontainer on the PC. So in M1a, any holder of
  `contents: write` (the agent App included) can publish a toolchain that
  runs on the owner's hardware, outside the D58 fence.
- The risk row says only "hosted runners and the devcontainer".
- **Fixes:**
  - Attest the M1a toolchain tarball with `actions/attest-build-provenance`,
    the same step images already use. `toolchain:fetch` then runs
    `gh attestation verify` on it outside Actions.
  - Or, outside Actions, `toolchain:fetch` rebuilds instead of accepting an
    unsigned release.
  - Or the owner does not use the PC devcontainer before M2.
  - At a minimum, the risk row names the owner's PC.

### R4. Major: no step turns on the D108 gate at M2

Zoom-out N4 and catalyst N5 raise this.

- **The gap:** nothing applies `repo:rulesets --phase m2`. The file-plan
  row lists only `bootstrap|m1a|m1b`, and `repo-verify` never moves to
  phase `m2`. So the gate never arrives, and nothing goes red.
- **Fix:** add this to the M2 entry gate: "`repo:rulesets --phase m2`
  applied, and `repo-verify` green at `m2`". Add `m2` to the phases the file
  plan applies.
- **Catalyst N5 addition:** before turning the gate on, the owner reviews
  `git diff <bootstrap>..HEAD` for the trust-root paths once, because those
  files went ungated until M2.

### R5. Major: from M2, a runner PAT leak could add a bypass actor unseen

Catalyst N2 raises this.

- **The gap:** D109 assumes only the owner can add a bypass actor. But the
  M2 runner PAT has Administration write, and it can edit rulesets.
- **Fixes:**
  - A host-run check reads the `main` ruleset with the agent App's token and
    fails unless `current_user_can_bypass` is `never`. This field is
    unverified for App tokens; prove it at the M2 entry gate.
  - Or make D82 (a runner App with no Administration write) an M2 entry
    condition.

### R6. Major: the C2 hole remains through fixtures and the gate policy

Catalyst N3 raises this.

- **The gap:** one agent PR can do all three of these at once and stay
  green:
  - delete a marker fixture, or its `expected.toml` row;
  - drop `GCOVR_EXCL` from `forbidden_markers`;
  - add a marker.

  It can also drop a `required_flags` item together with its fixture.
- **Fix:** widen the ratchet into a general removals file. `gate:policy`
  fails, unless the file has an entry, on any removal of:
  - a lock capability;
  - a fixture or an `expected.toml` row;
  - a `required_flags` item;
  - a `forbidden_markers` item.

### R7. Major: from M2 the weekly Action SHA batch waits for the owner

Zoom-out N5 and catalyst N6 raise this.

- **The conflict:** the batch rewrites `uses:` lines in trust-root
  workflows, so from M2 it needs code-owner review. §7 says it "merges on the
  checks".
- **Owner-written PRs:** GitHub does not let an author approve their own PR
  (D100). So a trust-root PR that the owner writes cannot be approved, and
  the agent App must write them.
- **Fix:** state both rules, or move trust-root Action bumps into their own
  Renovate group.

### R8. Nit: setup step 6's CODEOWNERS sub-step no longer earns its place

Zoom-out N6 raises this.

- **Fix:** let M1a PR 6 add the trust-root CODEOWNERS, and drop the sub-step.

### R9. Nit: triggers are still split, and each bump builds twice before M2

Zoom-out N7 and catalyst N7 and N8 raise this.

- **The gaps:**
  - The `builder.yml` and `post-merge.yml` file-plan rows miss the `push`
    trigger and the dispatch.
  - D112's "push only when tags exist" rule is not in the design body.
  - Before M2, both workflows cold-build p2996 for each bump.
- **Fixes:**
  - Keep one trigger list, in the file plan.
  - Optionally, use the dispatch from M1a.

### R10. Nit: two rows promise a last-good macOS fallback that Q5 left open

Zoom-out N8 and catalyst N9 raise this.

- **Rows:** risk row 1456, and the `toolchains/gcc-macos/README.md` row.
- **Fix:** point both rows to Q5.
- **Also (Z3 residual):** the Alternatives entry "GitHub attestations for
  toolchains too" names jdx-first as the reason.

### R11. Nit: CUJ 5 and CUJ 6 still depend on `review:cap`

Zoom-out N9 raises this.

- **Fix:** align both CUJs with G6: "once `review:cap` exists (M5)".

## Areas both reviewers confirmed

- The scope of D108.
- D109 for M1a.
- D113's three triplets.
- The deferral to Q5.
- `main` never reusing PR artifacts.
- One VM per self-hosted job.
- The cut order.

## Owner decisions on the residuals (2026-11-13)

The owner chose to fix the residuals and move to Stage 6 without a third
Stage 5 audit:

- R1: D114, a separate `publish.yml` that runs no repository code holds the
  signing identity. `builder.yml` stays a trust root because it runs on the
  PC runners.
- R1/R6: D115, one `gate-removals.toml` ratchet, and the checker runs from
  `main`'s copy.
- R3: D116, toolchain tarballs are attested in M1a and verified outside
  Actions.
- R5: D117, the PC runner App replaces the PAT, as an M2 entry condition.
- R7: D118, the weekly Action SHA batch waits for the owner from M2;
  trust-root PRs come from the agent App or Renovate.
- R2, R4, R9, R10, R11: applied. The M2 entry gate re-proves packslip for
  `publish.yml`, applies `--phase m2` after a one-time owner diff review,
  and keeps one trigger list in the file plan. The macOS rows point to Q5,
  and CUJs 5 and 6 wait for `review:cap`.
- R8 and the remaining Z6 history wording: left for Stage 7.
