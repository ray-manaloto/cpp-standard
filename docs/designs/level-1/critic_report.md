# Stage 7: Critic Review, round 1 (re-review of D99-D121)

The earlier Stage 7 report is in git history at a5452af.

## Scope

**Target:** `docs/designs/environment-standard.md`, FeatureRange lines
1-1533.

**Reviewers:**

| Reviewer | Standard |
|---|---|
| `egm-design` | feature-spec standard |
| `egm-structural` | feature-spec standard |
| `egm-style` | none |

All three completed.

**GoldfishContext:**

- the decisions log;
- the brief;
- the two saved sources.

The earlier review reports were not included.

## Results

**Tally:** 1 Blocker, 37 Majors, about 50 Nits.

The IDs are `<reviewer>-1-<n>`:

- `des` is the design critic;
- `str` is the structural critic;
- `sty` is the style critic.

Duplicates are merged under the first ID.

## Blocker

### des-1-1. Dispatch input can run non-`main` code on the self-hosted runners

**Lines:** 504-506, 937-938, 1517.

**The problem:** from M2, `post-merge.yml` and `mac-gate.yml` are dispatched
"for that commit". That means a SHA input on `refs/heads/main`. The agent
App can dispatch them with an unmerged PR head SHA. The D58 hook would accept
the job, and unreviewed code would then run on the PC or the Mac.

**Fix:** every self-hosted workflow does one of two things:

- takes no ref or SHA input; or
- refuses, before checkout, any SHA that is not an ancestor of `origin/main`.

Add a negative test at the M2 entry gate, and a risk row.

## Majors: trust and security

### des-1-2. M1a toolchain trust inside Actions is weaker than stated

**Lines:** 94, 515-521, 588-594, 1516.

**The problem:**

- The hosted fetch does no check.
- A release titled with a future hash can be created ahead of time.
- `gh attestation verify` binds a digest to a workflow, not to the artifact
  tag.

**Fix:**

- Verify in Actions too.
- Check that `inputs-hash.txt` equals the computed hash.
- Refuse an ambiguous title.
- Describe the M1a and M2 states separately.

### des-1-7. The trust roots protect who signs, not what is signed

**Lines:** 515-555, 982-983, 1522.

**The problem:** `artifact:build` and `toolchains/*/build.sh` are owned roots,
not trust roots. A merged agent change to them produces a toolchain signed as
`main`.

**Fix:** add a risk row, or make these files trust roots from M2.

### des-1-8. The removals ratchet can be beaten in two PRs

**Lines:** 829-832, 1007, 1515.

**The problem:** the first PR weakens the checker, and `main`'s old copy
passes it. The second PR then drops a capability.

**Fix:** make `gate:policy` and the fixture runner trust roots from M2, or
mark the risk as accepted.

### str-1-outside. `ci.yml` itself comes from the PR

**Lines:** 830-832, 989, 1515.

**The problem:** "run `gate:policy` from `main`'s copy" is weak, because a PR
can edit the step that fetches `main`'s copy.

**Research:** a ruleset's "require workflows" rule needs GitHub Enterprise
Cloud, at the org level, so it cannot pin `ci.yml` to `main`'s copy here.

### des-1-9. Renovate's identity is open

**Lines:** 923, 978, 1015, 1030-1050.

**The problem:** a Renovate token stored as a repository secret would be
readable by same-repo PR workflows.

**Fix:** add an Open Question, or name the credential's home.

### des-1-5. The runner PAT text contradicts D117

**Lines:** 126-127, 198-200, 959-961, 1014, 1218, 1523.

## Majors: correctness and evidence

### des-1-3. The release lookup by title does not scale

**Lines:** 498-501, 626-632, G1.

**The problem:** `--limit 1000` returns newest first. After some hundreds of
days, older releases fall out of the list, and the toolchain is silently
rebuilt.

**Fix:** use a deterministic lookup, and fail on an ambiguous match.

### des-1-4. The ordering between the builder and `ci.yml` is not stated

**Lines:** 502-514, 586, 621-625, 1509, 1519, 1528.

**The problem:**

- Gate jobs may miss the cache and each rebuild p2996.
- In M1a, a merge group rebuilds for every input-changing PR.

**Fix:**

- Gate jobs wait for `artifact:check`.
- Add a risk row for M1a merge-queue cost.

### des-1-10. The sccache module claim has no source

**Line:** 771.

**Verified by the author:**

- mozilla/sccache#2516 added partial clang module support, merged
  2026-02-27.
- mozilla/sccache#2650 is still open: with CMake 4.3 and later, the module
  compiles pass flags in an `@modmap` response file, which is not
  cacheable.
- The fix, #2701, was closed without merging.
- #2216 reported a wrong-cache bug.
- The latest release is v0.19.0, from 2026-10-24.

### des-1-11. The 100% coverage measure does not count consteval code

**Lines:** 188-194, 792-795.

**Fix:** state this as a limit, and optionally require a named
`static_assert` per consteval function.

## Majors: the M0 record

### des-1-6 / sty-1-M1. M0 results are not reflected in §1, §10 or the risk rows

**Lines:** 409-411, 595, 1165-1210, 1506, 1510, 1519.

## Majors: wording that changed meaning

### str-1-5 / sty-1-M11 / des-1-15. "Reviewed" and "unreviewed" are used in the pre-D101 sense

**Lines:** 391, 867, 871, 1240, 1460.

### sty-1-M12 / sty-1-M13. Toolchain trust terms contradict each other

**Lines:** 515, 548, 552, 591, 1125, 1518.

The text calls releases both "unsigned" and "attested", and says one item
"can never become `main`'s release".

### sty-1-M15 / des-1-14. "No PR needs approval" is stale for M2

**Lines:** 984, 1004, 1051-1054, 1243.

### sty-1-M16. The merge rule is restated

**Lines:** 420, 986, 1345.

### sty-1-M17 / des-1-19 / str-1-3. D106 and D107 are not in Open Questions

**Lines:** 1062, 1245.

These lines cite D107 without marking it "proposed".

### sty-1-M18. The `tools.toml` reason is stale

**Lines:** 660, 1046.

### sty-1-M9. Summary claims

**Lines:** 388-393.

The summary says "built once" and that "only `main`'s builder publishes".

### sty-1-M8 / str-1-7. Stale decision range

**Line:** 355.

The text cites "D26 to D82".

### str-1-6 / sty-1-M10 / des-1-20. The overview diagram shows only the M2 state

**Lines:** 362-386.

The `OWN` node does not separate out the trust roots.

### sty-1-M14. The fetch rule is written differently in several places

**Lines:** 94, 304-306, 1247, 1519.

## Majors: goals and claims

### sty-1-M2. "Each claim cites its source" is not true

**Lines:** 52-54.

Uncited figures appear at lines 1524, 1525, 1529, 1292 and 259.

### sty-1-M3. The 66,000-line figure is credited to the brief

**Lines:** 144-146.

The brief does not contain it.

### sty-1-M4. G1's "newest" contradicts the release-age cutoff

**Lines:** 161-165.

### sty-1-M5. G5 states the M3 end state as fact

**Lines:** 195-204.

### sty-1-M6 / des-1-22. G3's "same result" is undefined across operating systems

**Lines:** 184-186.

### sty-1-M7. G8's capacity goal has no measure

**Lines:** 219-222.

### sty-1-M19. "One fixture per tier-1 check" is too broad

**Lines:** 812-814.

### sty-1-M20. Two rules for promoting a tool to tier 1

**Lines:** 808 and 1307.

### Other style calibration items

- Line 56: "three differences".
- Line 84: the owned and trust lists.
- Line 1133: "primary signal for every risk row".
- Line 1508: "up to a day".
- Line 1292: "2,000 minutes".

## Majors: structure

### str-1-1. A Markdown list continues lazily

**Lines:** 573-596.

The security paragraph sits inside fetch item 4.

### str-1-2. §2 step 4 and §6 have no subheadings

**Lines:** 515-620, 863-1026.

There are no anchors and no separate M1a and M2 blocks.

### str-1-4. No alternatives are recorded for D101, D108 and D120

**Lines:** 1250-1497.

## Nits

The nits are recorded in the round-1 reviewer outputs. The resolver groups
them in `goldfish_review_report.md`. They cover:

- **Glossary:** filing and duplicate definitions.
- **CUJs:** inconsistent "Then" formatting.
- **Document order:** unnumbered H3s, and the order of §10.
- **M0:** missing (i) tags.
- **Alternatives:** the preamble.
- **Risks:** the "Kind" set, rows whose trigger is "—", and the
  `builder.yml` row reference.
- **Formatting:** line wrap, horizontal rules and research links.
- **Pins:** `pins.toml` against `pins:validate` (des-1-12).
- **Dispatch:** which job dispatches (des-1-13).
- **Images:** the CUJ 2 rule for unattested images (des-1-17).
- **Weak rejections:** des-1-18.
- **LLVM:** the cross-release apt.llvm.org risk (des-1-21).
- **Wording:** about 20 style items.

## Round 2

**Target:** lines 1-1658 after the round-1 edits. The same three reviewers,
started fresh, read the same GoldfishContext and no earlier report.

**Tally:** 4 Blockers, 41 Majors, 38 Nits. All four Blockers come from the
design critic.

### Blockers

- **des-2-1.** The design claims that from M2 a merged agent PR "cannot
  change what `publish.yml` signs" (§6 Trust roots). This is false. The
  inputs are still owned roots:
  - toolchain source URLs in `pins.toml`, which are allowlisted by host
    only;
  - `pins-allowlist.toml`;
  - `tools.toml` and `mise.lock`;
  - `mise.toml`;
  - the tasks that `artifact:build` calls.
- **des-2-2.** Neither the checks that protect the owner's hardware nor the
  runner image are gated by a human, even from M2:
  - the checks run in `toolchain:fetch` and `image:verify`;
  - the image that carries the D58 hook is built by `vm:golden` and by the
    PC image build.
- **des-2-3.** A same-repo PR workflow can request write permissions:
  - it can push any GHCR tag, not only `pr-` tags, and PR jobs pull without
    verifying;
  - it can post statuses and create releases;
  - a new workflow file is not a trust root.
- **des-2-4.** The fence text says agent code runs only in the dev VM and
  on hosted runners. In M1a, and if M0 (a) fails, agents run on the Mac
  host. That host holds the PC SSH access, the Docker context and the App
  keys.

### Majors and Nits

The full lists are in the reviewers' outputs and are summarised in
`goldfish_review_report.md`:

- design: des-2-5 to des-2-18;
- structural: str-2-1 to str-2-19;
- style: sty-2-1 to sty-2-46.

## Round 3

**Target:** lines 1-1850 after the round-2 edits. The same three reviewers,
started fresh.

**Tally:** 0 Blockers, 37 Majors (design 9, structural 6, style 22), 43
Nits.

Design Majors:

- **des-3-1:** "ancestor of `main`" admits old and reverted commits, and
  `publish.yml` checks the run's `head_sha`, not the built SHA.
- **des-3-2:** the code that enforces the D125 and D126 allowlists
  (`pins:validate`, `artifact:tag`) is not a trust root.
- **des-3-3:** attesting the archive and `inputs-hash.txt` separately does
  not bind them together.
- **des-3-4:** `workflow_dispatch` of `ci.yml` (`linux:run`) is outside the
  hosted-job rules.
- **des-3-5:** runner registration level. A repository-level App needs
  Administration write, so registration must be at the org level.
- **des-3-6:** `main`'s checker runs with the PR's `mise.toml`, which
  nothing validates.
- **des-3-7:** a merged gcovr report could hide lines that one compiler did
  not cover.
- **des-3-8:** who builds the runner images, and from which ref.
- **des-3-9:** a draft release left by a failed publish breaks the lookup
  outside Actions.

The structural Majors cover:

- the D124 range, which is stale;
- the M1a PR named in the image risk row;
- §10 and §6 headings that cannot be linked;
- open items in Settled questions;
- whether the repository is public or private.

The style Majors are about calibration and contradictions.

## Rounds 4 and 5

- **Round 4:** 0 Blockers and 32 Majors (design 10, structural 6,
  style 16). These were resolved as D132.
- **Round 5, the cap:** 1 Blocker and 22 Majors (design 7, structural 3,
  style 12).
  - **The Blocker (des-5-1):** the host launchd job that builds runner
    images loaded the merged `mise.toml` on the host.
  - These were resolved as D133.

## Loop result

The loop ran all five rounds without reaching two clean rounds. Each round
had Majors: style calibration, and new M2 trust edge cases that D129 routes
to the M2 entry gate as named items. The number of design and structural
Majors fell from round to round: 37, 41, 15, 16, then 10.
