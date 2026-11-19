# Consolidated Goldfish review: D136 to D155

Status: resolved

The owner approved one resolution table for ticket #142 (2026-11-18); the
owner did not mark the findings one by one. The resolve step wrote each
finding's Owner line from that table and set each decision's disposition
in the Disposition table.

- **Design revision reviewed:** `docs/designs/environment-standard.md` at
  `main` commit 283866d. The design text was last changed in 3e0dfa8 (#140)
  and is 2030 lines long.
- **Decisions reviewed:** D136 to D155, rows 144-163 of
  [decisions-log.md](decisions-log.md).
- **Ticket:** #141 of spec #122. The ticket asks for one review, so this is
  one consolidated pass, the "uninterrupted" preset. The design was not
  edited. The stage reports of the D99-D135 review (`zoom_out_report.md`,
  `critic_report.md` and the others) are left as they were.
  `goldfish_review_report.md` holds the resolved D99-D135 review and is left
  as it was; this review's resolved state is recorded in this file.

## Scope

The reviewers covered the design sections that D136 to D155 touch. Each
decision was mapped to those sections by searching the design for `D<n>`.

- Status header: lines 1-12.
- Overview and Glossary: 14-133.
- Goals, as context: 162-226.
- Non-Goals and Open Questions: 227-283.
- §6 Where code runs: 827-1057.
- §7 Updates: 1058-1115.
- §9 Agents: 1129-1156.
- §10 Critical path: 1159-1175.
- §10 M2 entry gate and M0-Linux exit review: 1259-1299.
- §11 Machine configuration: 1300-1340.
- §12 Project agent containers: 1341-1382.
- Settled questions: 1383-1398.
- Alternatives, "From the review stages": 1483-1580.
- Risks & Mitigations: 1581-1626.
- Detailed Implementation: 1627-2030.

Goldfish context: the decisions log,
[m2-trust-backlog.md](m2-trust-backlog.md),
[machine-bootstrap-migration.md](machine-bootstrap-migration.md), and the
`docs/standard/` files that §11 and §12 cite. The comprehension reviewer read
only the design, by design of that test.

## Reviewers

Each reviewer ran in a fresh context with no conversation history. All six
were dispatched directly and in parallel, at the same revision. Ordering the
stages buys nothing in a single pass with no fixes between stages.

| Reviewer | Lens | Standard | Status | Raw findings |
|---|---|---|---|---|
| `egm-zoom-out` (`zo-*`) | simplicity, scope | zoom-out | completed | 22 |
| `egm-inventive-catalyst` (`ic-*`) | contradictions with the decisions they amend | none | completed | 21 |
| `egm-comprehension` (`cp-*`) | does the text stand on its own | none | completed | 21 |
| `egm-design` (`des-*`) | architecture, trust, risks | feature-spec | completed | 25 |
| `egm-codebase-details` (`cb-*`) | text against the repository | implementation-readiness | completed | 20 |
| `egm-implementation-readiness` (`ir-*`) | can an agent build it | implementation-readiness | completed | 14 |
| `egm-structural`, `egm-style`, Stage 8 re-zoom | | | not dispatched: the ticket asks for one pass, and spec #122 rules out further stages | |

The 123 raw findings first merged into 39 consolidated findings. A Codex
adversarial review then revised them (see [Revision after the Codex
review](#revision-after-the-codex-review)): 8 numbers are now merged or
dropped, and F40 is new. That leaves 32 active findings: 4 Blockers,
19 Major and 9 Nits. Five more raw findings, and parts of two others (zo-20, cb-15),
concern decisions outside D136 to D155; they are listed under [Outside scope](#outside-scope) and do
not appear in the disposition table. Where reviewers gave a finding
different severities, the consolidated finding takes the highest one that
the evidence supports. The Elephant checked each Blocker's evidence and the
handed-over points against the repository at 283866d (`.github/CODEOWNERS`,
`mise.pc.toml`, the runner README, the D137 row, `.github/rulesets/main.json`,
`mise.toml` and the rulesets task); live GitHub settings were not queried.

Coverage limits, from the reviewers' own statements: `macos.md` and
`ubuntu.md` were only searched or read in part, the codebase reviewer did not
open `m2-trust-backlog.md`, and the three shared repositories of D148 could
not be checked from this repository.

## Points handed over by the #140 worker

| Point | Consolidated finding | Raised by a reviewer without prompting |
|---|---|---|
| The D118 Action SHA batch wait, against D149 | F8 | answered by all six; the design marks it open for this review, and the brief asked reviewers to answer such questions |
| What `repo:rulesets --verify --phase m2` checks | F10 | yes (cp, zo, ir). Elephant check: the task offers only the phases `bootstrap` and `m1a` (`.mise/tasks/repo/rulesets`, lines 3-5). No `m2` phase exists, and the decision that cut M1a (spec #122) moved the phases out to the follow-up spec |
| The D131 one-time trust-root read | F9 | answered by all six (five say keep, one says drop); also marked open in the design and asked for in the brief |
| D17 and D127, against D143 and D155 | F3 (F5 merged into it) | yes (zo, ic, ir, cb, des) |
| D148's `minimum_release_age = "0s"`, not yet in `mise.toml` | F12 | yes. Elephant check: `mise.toml` line 11 still holds `minimum_release_age = "2026-11-13T00:00:00Z"` |

## Revision after the Codex review

At the owner's request, an adversarial Codex review of the first version
was checked point by point. Codex read the report statically at 283866d,
and its own reviewer fan-out did not run, so each of its points was
treated as a claim to be checked against the files it cites. The verdicts
are in each finding's **Codex review** line. Codex points that did not hold
are recorded in the ticket's plan, not here.

F-numbers are stable. A finding that was merged or dropped keeps its
number and has a one-line reason. These are:
- merged: F4 into F1, F5 into F3, F18 into F19, F28 into F14, F26 and F27,
  and F37 into F19;
- dropped: F21, F33 and F36.

Findings are listed by number. Each one's severity is in its first field.

## Findings

Each finding has these fields:

- **Severity:** Blocker, Major or Nit, or "merged into" / "dropped".
- **Sections:** the design sections it concerns.
- **Decisions:** the decisions it concerns.
- **Raw:** the reviewer finding IDs it merges.
- **Codex review:** the verdict on the Codex adversarial review's point,
  checked against the cited files.
- **Recommendation:** the Elephant's suggestion to the owner.
- **Owner:** kept or dropped, written by the resolve step from the resolution
  table the owner approved. It is empty until the gate.

#### F1. Admission control on the PC runner slots is missing, so no cpp-standard slot may be activated before M2's controls

- **Severity:** Blocker (on activating a cpp-standard slot)
- **Sections:** §6 The fence, Runner-side enforcement, Runner VMs, Public
  repository and self-hosted runners, Identities, Credential storage
  (846-952); Glossary "The fence" (100); §11 (1302-1311); setup closing line
  (1737-1738); M2 entry gate (1268-1275); §12 Accepted risks (1378-1381);
  Risks row 1595.
- **Decisions:** D137, D141, D149, D150, D155.
- **Problem:** §6 says no self-hosted runner is registered until M2 and that
  every PC job runs behind the D58 hook, whose allowlist is
  `builder|post-merge|mac-gate`. D141 moved the gha-slot runners into
  cpp-standard. Each job there gets a single-use JIT runner in a new `--rm`
  container with no Docker socket and no sudo, on a network the launcher
  fences off (`docs/standard/gha-runner/gha-slot`, lines 12-28 and 90-97).
  What the slots lack is D58's admission control over which workflow and
  ref may run. Their only rule is a convention: `workflow_dispatch` and
  pushes only. The per-slot compiler cache is writable and survives across
  jobs for up to seven days (lines 26-27).

  Migration Phase 4 step 5 then gives cpp-standard a slot of its own and
  moves `pc-smoke.yml` there, before any M2 control is proven
  (machine-bootstrap-migration.md, lines 222-225).

  Present exposure, folded in from F4: a container bound to a slot-enabled
  repository holds a token with workflows write for that one repository
  (`agent-secrets.bash`, line 106), so it can push a branch whose workflow
  runs on that repository's slot and writes to its cache. A container bound
  to any other repository cannot.

  The design's runner App is org-level with an encrypted key. The slot App
  has repository Administration write, and its key is a plain root-owned
  file (gha-runner README, lines 3, 9 and 19). §11 calls the iptables
  `gha-fence` "the job fence", which is not the Glossary's "The fence".
- **Fix:** Describe the slot runner in §6 as a second runner path, with its
  own App and key storage. Do not activate a cpp-standard slot until
  runner-side admission (D58 or an equivalent per-repository allowlist of
  ref and workflow) is in place and proven. State the present exposure of
  slot-enabled repositories, including the shared writable cache. Rename
  the iptables fence.
- **Raw:** ic-1, ir-2, zo-14, cp-3, cb-3, cb-4, cb-16, des-2; plus F4
  (des-3) and the token-scope part of F31 (ic-19).
- **Codex review:** partly holds. The JIT, `--rm`, socket and network claims
  hold (gha-slot, lines 12-28). F4's "any project container" was too broad
  (agent-secrets.bash, line 106). The blocker narrows to activating the
  cpp-standard slot (migration plan, lines 222-225).
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #218.

#### F2. The inputs that configure the hosts are not trust roots, and nothing says who applies them

- **Severity:** Blocker
- **Sections:** Glossary (89-90); §6 Trust roots (972-996) and Owned roots
  (1011-1031); §11 (1300-1316); §12 (1361-1362).
- **Decisions:** D139, D141, D149, D150, D155.
- **Problem:** Trust roots are "files whose change reaches the owner's
  hardware". Since Phase 3, the PC's declared config is the checkout's
  `mise.pc.toml`, and that checkout tracks `main`. A merge does not deploy
  by itself: Phase 3 applied nothing and restarted nothing
  (machine-bootstrap-migration.md, line 208). But the next apply on the PC
  installs what `main` holds:
  - systemd units and iptables rules for the slots, as root (`mise.pc.toml`,
    lines 23-59);
  - the runner launcher, from `docs/standard/gha-runner/`;
  - the `agent-secrets` user service, from `docs/standard/agent-auth/`
    (`mise.pc.toml`, lines 501-508). It runs as the PC user, and that user
    can fetch the all-repository App key.

  `mise.mac.toml` will do the same on the Mac, and the agents image is the
  Mac's credential-service image (F7). None of these is in the trust-root
  list. The owned-roots list covers `.mise/tasks/**` but not the machine
  configs or `docs/standard/**`. CODEOWNERS lists `/mise.pc.toml` and
  `/docs/standard/gha-runner/`, which neither design list has.

  Folded in from F38: the trust-root list in the D149 row is D108's stale
  list, with no `publish.yml` and no `gate-removals.toml`.
- **Fix:** For each host-affecting input, say what selects, updates and
  applies it and under which identity. The inputs are: `mise.pc.toml`,
  `mise.mac.toml`, the files they source (`docs/standard/gha-runner/**`,
  `docs/standard/agent-auth/**`) and the credential-service image. Add them
  to the trust roots, or record why each is left out. Widen D149's accepted
  risk to them. Point the D149 row at §6 for the list.
- **Raw:** cb-2, des-1, ir-9, cp-3; plus F38's path-list part (des-20).
- **Codex review:** partly holds. "Tracking `main` deploys every merge" was
  wrong (migration plan, line 208), and `agent-secrets` is a user service,
  not root (`mise.pc.toml`, line 503). `toolchains/*/linux/**` is an owned
  root, not a trust root, by design (design lines 979-986 and 1016-1024).
  The trust gap stands.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed in part; #227
  decides the trust-root list, and the remainder moved to #247. #247 left
  F2 as it was, blocked on #227: the trust-root list, D149 and who applies
  each input follow #227's decision.

#### F3. M2 entry needs a decision: who starts containers and certification after isolation, where agents run, and what each may read

- **Severity:** Major
- **Sections:** §6 The fence (852-854) and Credential storage (943-952); G5
  (200-208); M2 entry gate (1285-1287); Alternatives (1557-1558); Risks
  (1623); Settled questions (1390); Cut order item 12 (1215); M3 file plan
  `runner/mac/agent-token.plist` (1990); §12 (1341-1382).
- **Decisions:** D137, D143, D150, D155.
- **Problem:** Before M2, D137 lets agents on the Mac host use the PC's SSH
  and Docker, and the design's §6 lines 852-854 accept that. From M2, D127
  isolates agent sessions from the PC SSH key, the Docker context and the
  keys. These rules coexist until M2. What is missing is the M2 hand-off:
  - who starts `certify:ubuntu`, `agents:image`, `agents:up` and
    `agents:refresh` once agent sessions are isolated (they all drive the
    PC's Docker over SSH);
  - where agents run, given that D17 and G5 place them in the Tart VM, which
    G5 calls provisional, while D143 places them in project containers;
  - which credentials each of those sessions may read.

  The Alternatives entry that rejects all "Agents using the PC's Docker over
  SSH" is stale since D137. Folded in from F5: the M3 `agent-token.plist`
  broker and D155's `agent-secrets` both mint one-hour App tokens.
- **Fix:** Record an M2 entry decision covering the three points above.
  Mark the Alternatives entry as amended by D137. Keep two brokers only if
  both execution environments remain, and say so.
- **Raw:** ir-1, zo-4, ic-4, cb-8, des-4; plus F5 (zo-3, ic-5, des-25,
  cp-6).
- **Codex review:** partly holds. Pre-M2 use is allowed (design lines
  852-854; D137), so the unconditional Blocker was overstated. The post-M2
  launcher and the stale rejection are real gaps.
- **Recommendation:** keep, as a Major M2 entry decision.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #219.

#### F4. A container agent can run code on the PC runner slots

- **Severity:** merged into F1
- **Sections:** §12 Accepted risks (1378-1381); Risks row 1595.
- **Decisions:** D141, D155.
- **Why:** Codex review: the claim was too broad. Each token is scoped to one repository (agent-secrets.bash, line 106), so only containers bound to slot-enabled repositories are exposed. F1 now states that exposure.
- **Raw:** des-3.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F5. The design gives agents two homes: the Tart VM and project containers

- **Severity:** merged into F3
- **Sections:** G5 (200-208); §6 (852-854, 943-946); Settled questions (1390); §12 (1341-1382).
- **Decisions:** D143, D155.
- **Why:** Codex review: where agents run is one part of the M2 hand-off decision, so it is decided with F3.
- **Raw:** zo-3, ic-5, des-25, cp-6.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F6. The second agent App and its Doppler tokens are missing from Identities and Credential storage

- **Severity:** Major
- **Sections:** Glossary Identities (124-132); §6 Identities (914-929) and
  Credential storage (941-952); §11 (1305-1307); M2 entry gate (1285-1287);
  setup step 6 (1686-1703); M1a `AGENTS.md` row (1840).
- **Decisions:** D141, D153, D155.
- **Problem:** §6 says agents push as `cpp-standard-agents` "on cpp-standard
  only". Container agents push to cpp-standard as `ray-manaloto-agents[bot]`.
  That App is installed on every repository with workflows write, and its key
  is in the Doppler project `agent-containers`. The service token that
  fetches the key is on both the PC and the Mac, so §11's "PC-only Doppler
  config" is no longer the only source.

  The D127 condition does not list this token. The setup steps have no step
  or "Done when" check for this App. The `AGENTS.md` row does not say which
  App applies where.
- **Fix:** Add the App, its key location and both token files to the
  Glossary, §6 and §11. Add the token to the D127 list. Add a setup step with
  a check. Say which identity the merge rules and the digest treat as "the
  agent App".
- **Raw:** cp-6, zo-5, ir-13, ic-6, cb-5, des-5, des-22.
- **Codex review:** holds. D155 assigns the two Apps to their environments, but the design's Glossary and §6 still list one; the PC-only Doppler config (D141) and the `agent-containers` token (D155) serve different purposes, and both are missing from Credential storage.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed in part; the
  remainder moved to #247, which finished it in the design.

#### F7. Choosing a project image on the Mac also replaces the Mac's credential service

- **Severity:** Blocker (for the Mac credential boundary)
- **Sections:** §12 Logins with no typing (1361-1370).
- **Decisions:** D152, D155.
- **Problem:** On the Mac, `agents:up` compares the project image with the
  image of the running `agent-secrets` container. If they differ, it
  removes the service and starts the selected project image as the new
  service, with the host's Doppler configuration and the credential state
  folder mounted (`.mise/tasks/agents/up`, lines 56-64). Two consequences
  follow:
  - an ordinary project image change replaces the service for every Mac
    project;
  - if the new image cannot serve credentials, every project's tokens
    expire.

  That image also installs four agent CLIs with unpinned `curl | bash`, so
  the process holding the all-repository App key runs on the least-pinned
  image.
- **Fix:** Give the service its own pinned, minimal image, chosen
  independently of any project image. Verify that a project image change
  leaves it running. Verify that a service upgrade can recover from a
  failed start before the working instance is retired.
- **Raw:** des-6.
- **Codex review:** holds and widens (`agents/up`, lines 56-64). Raised from
  Major.
- **Recommendation:** keep, as a Blocker.
- **Owner:** kept (ticket #142, 2026-11-18): moved to #221.

#### F8. D118's weekly owner wait on the Action SHA batch has no mechanism after D149

- **Severity:** Major
- **Sections:** §6 Trust roots (998-1002); §7 Updates (1073-1076).
- **Decisions:** D148, D149, D152.
- **Problem:** The design leaves this question to this review. D118's wait
  rode on the code-owner review that D149 dropped. `.github/rulesets/main.json` has
  `require_code_owner_review: false` and an approval count of 0. D148's
  preset auto-merges digest and pin updates with no cooldown, and Action SHAs
  are pin updates. D152 asks for updates every day, while §7 still batches
  Action SHAs weekly.
- **Fix:** All six reviewers agree that the code-owner wait is gone. Five
  (zo, ir, ic, cb, des) say record D118 as superseded: from M2 the Action
  SHA updates merge on the required checks, with the owner's look after
  merge. cp instead keeps an owner look by convention: Renovate does not
  automerge the batch, and the owner queues it once a week, labelled "a
  convention, not a guard" as D128 does. ic, cb and des offer the same
  owner look as an option, through a Renovate `automerge: false` rule on
  the trust-root paths. des adds a mechanical check: verify that each new
  SHA matches its upstream release tag. Also decide whether Action SHAs
  stay weekly or move to daily. Add a risk row.
- **Raw:** cp-10, zo-9, ir-5, ic-2, cb-13, des-11.
- **Codex review:** holds, as the unresolved D118 policy choice. The tally in the Fix is as the six reviewers gave it.
- **Recommendation:** keep. Supersede D118 by a new decision row. The
  `automerge: false` convention is the owner's choice.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed (D170).

#### F9. The D131 one-time read at M2 needs a baseline and a receipt, and cannot pre-review what already ran

- **Severity:** Major
- **Sections:** M2 entry gate (1288-1292); Risks row 1596; M2 file plan
  `spikes/m2/README.md` row (1976).
- **Decisions:** D149.
- **Problem:** The design asks whether the read "still earns its place".
  Risk row 1596 already lists it as a mitigation. §6 gives the trust-root
  path list, but the read names no starting commit, and nothing records that
  it was done. The README row that lists every gate item omits it. An M2
  read also cannot review, before they run, host files that the PC already
  applies before M2 (F2).
- **Fix:** Five reviewers (cp, ir, ic, cb, des) say keep the read; one (zo)
  says drop it and row 1596's reliance on it. If it is kept:
  - name the starting commit;
  - record the reviewed SHA range in `spikes/m2/README.md`;
  - state which paths first run at M2, where the read is a pre-execution
    review, and which the owner can only review after the fact.
- **Raw:** cp-16, ir-3, ic-3, cb-14, des-12 (keep); zo-10 (drop).
- **Codex review:** partly holds. "No path list" was wrong: §6 lines 979-986
  give one. The baseline, the receipt and the timing distinction stand.
- **Recommendation:** keep the read, with a baseline and a receipt. Close
  the question in a decision row.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F10. Phase `m2` of `repo:rulesets` adds nothing the design names, and one check guards nothing

- **Severity:** Major
- **Sections:** §6 The repository settings are checked daily (1033-1045); M2
  entry gate (1289-1291); file plan rows `main.json` (1892) and
  `spikes/m2/README.md` (1976).
- **Decisions:** D149.
- **Problem:** Row 1892 records that the task accepts only `bootstrap` and
  `m1a` today, and it schedules `m1b` and `m2` for later work, which the M1a
  cut moved to the follow-up spec. But after D149 the design never says what
  `m2` adds: "`m2` adds no code-owner review" is its only content. Yet
  "`repo:rulesets --phase m2` is applied" is an M2 gate condition. The daily
  check also still fails if `main` stops dismissing stale approvals, though
  no PR ever needs an approval.
- **Fix:** In the follow-up spec, list what `m2` adds, for example
  runner-group or merge-group settings. Otherwise drop the phase and change
  the gate to "`repo-verify` green at `m1b`". Give the stale-approvals check
  a reason, or remove it.
- **Raw:** cp-17, zo-11, zo-12, ir-4.
- **Codex review:** partly holds. The missing CLI phase is already documented
  at design line 1892, so it is not new. The undefined increment stands.
- **Recommendation:** keep, routed to the follow-up spec "M1a trust roots and
  repository rules".
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #220.

#### F11. With no human look before merge, the post-merge backstop is itself editable

- **Severity:** Major
- **Sections:** §6 Hosted jobs (865-871) and Trust roots (988-996); Risks
  rows 1596 and 1624.
- **Decisions:** D149.
- **Problem:** D149's accepted risk rests on "the required checks, the
  fixtures and the ratchet are the guards". Row 1624 accepts that a
  same-repo PR can add a job named like a required check, and names the
  post-merge run on `main` as what catches a faked result. That run's
  workflow is itself a trust root that a PR can change and merge on the
  checks. GitHub cannot bind a check to one workflow without Enterprise
  Cloud (row 1624).
- **Fix:** Record the residual risk under D149. Credit a new check as a
  guard only with evidence that the merge queue enforces that check's
  identity.
- **Raw:** des-13.
- **Codex review:** holds as narrowed. The same-PR refusal proposed before
  does not work: the two changes can land in separate PRs, and row 1624
  records the binding limit. That fix was removed.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F12. `minimum_release_age`: the design gives two values, and `mise.toml` has the old one

- **Severity:** Major
- **Sections:** §3 `[settings]` (616-620); §7 (1068-1072); M1a `mise.toml`
  row (1842); Schema (1905).
- **Decisions:** D148, D152.
- **Problem:** §7 says D148 changes the cutoff to `0s` ("not yet applied
  there"). §3, the file row and the schema still specify a fixed cutoff for
  lock reproducibility (M0 (i)). `mise.toml` line 11 holds
  `"2026-11-13T00:00:00Z"`.

  D148 also mixes two settings. Renovate's release age decides when a PR
  opens. mise's `minimum_release_age` is the cutoff the lock-parity result
  depended on. Whether that reason still holds with exact pins "was not
  checked".
- **Fix:** Rerun the M0 (i) lock-regeneration check without a cutoff. If it
  holds, remove or zero the key and update §3, the row and the schema. If it
  does not, keep the date, set only Renovate's release age to 0, and amend
  D148.
- **Raw:** zo-6, cp-5, ic-7, ir-6, cb-12, des-10.
- **Codex review:** holds (`mise.toml`, line 11).
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #222.

#### F13. Integrating D148's `CI Check` and auto-merge with cpp-standard's required checks, queue and owner-held updates

- **Severity:** Major
- **Sections:** §7 Shared update configuration (1077-1090), Merge rule
  (1091-1110) and Base upgrades (1111-1114); §6 settings check (1038-1041);
  file rows `ci.yml` (1883), `hk.pkl` (1884) and `renovate.json5` (1963);
  Settled questions "Ubuntu upgrades" (1394).
- **Decisions:** D148, D152.
- **Problem:** D148 already decides cpp-standard's adoption. It also decides
  the three repositories' ownership, the rollout order (cpp-core, kb,
  dotfiles, then cpp-standard), and an acceptance test: a failing PR is
  blocked and a passing one merges by itself. Design lines 1077-1089 describe
  the glue. The unsolved part is integration:
  - D148's required `CI Check` does not fit cpp-standard's six required job
    names, and the daily check fails on any other list;
  - the preset auto-merges through GitHub's native auto-merge alongside the
    required merge queue;
  - the preset auto-merges digest updates, which would merge an Ubuntu base
    switch that D36 reserves for the owner. Major compiler bumps and
    capability-lock changes also wait for the owner (§7, lines 1103-1106).

  The `renovate.json5` and `hk.pkl` rows still describe configs of their
  own. Folded in from F35: the owner's base-switch merge is a convention
  under D149, not a guard, and is not labelled as one.
- **Fix:** Map `CI Check` onto the required-check list. Rewrite the two file
  rows. Extend D148's acceptance test to show three things:
  - a passing update enters the merge queue;
  - a failing required check blocks it;
  - base switches, major compiler bumps and capability-lock changes keep
    their owner-held treatment, labelled as conventions.
- **Raw:** zo-8, cp-4, ir-6, ic-8, cb-12, des-10; plus F35's convention
  part (cp-19).
- **Codex review:** holds as narrowed. D148 (decisions-log.md, line 156)
  already settles adoption, ownership, rollout and the acceptance test, so
  those parts were removed. Capability-lock changes were added.
- **Recommendation:** keep, narrowed to integration.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #222.

#### F14. mise version declarations: §11 calls the floor a pin, and some copies are outside D146's list

- **Severity:** Major
- **Sections:** §11 mise pin (1338-1339); Schema (1903, 1947); Alternatives
  (1519-1520).
- **Decisions:** D146.
- **Problem:** D86 makes `min_version` a floor, and that stands:
  `mise.toml` line 5 sets it to the oldest mise that can read the file,
  which today is the same 2026.11.9. §11 calls it a pin, and the schema
  calls `image/base.inputs.toml` "the only mise pin". The copies outside
  D146's list drift: `agents.Dockerfile` (line 18) and the PC runner image
  in `mise.pc.toml`, still at 2026.11.5 from an undigested tag. Folded in
  from F28: `agents.Dockerfile` and `ubuntu-cert.Dockerfile` declare their
  Ubuntu base digests separately, though both are equal today (lines 16
  and 17).
- **Fix:** Reword §11 so `min_version` is a floor. List every mise and
  Ubuntu-base declaration as one group that one Renovate rule bumps and
  `pins:validate` checks, including the copies outside D146's list.
- **Raw:** cp-7, zo-19, ir-7, ic-9, cb-10, des-9; plus F28's pin part
  (des-19).
- **Codex review:** partly holds. The floor's meaning is settled by D86 and
  is not reopened. The wording and the undeclared copies stand.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed in part; the
  remainder moved to #247, which finished it in the design.

#### F15. G1 ("every input is pinned") against unpinned agent CLIs, auto-merged skills and D41's owner approval

- **Severity:** Major
- **Sections:** G1 (164-174); §9 Agent tooling (1136-1139); §12 Updates
  (1357-1360); §7 (1083-1085); M1b row (1969).
- **Decisions:** D143, D147, D148, D152, D155.
- **Problem:** D152 leaves the agent CLIs and plugins unpinned. D148's
  skills marketplace auto-merges upstream skill changes every day. §9 still
  says plugins are added "only with the owner's approval". Agents load these
  unreviewed instructions while holding workflows write (D155), and
  trust-root changes merge with no human look (D149). The combined risk is
  that an upstream skill change steers an agent into editing a self-hosted
  workflow, and it is stated nowhere. G1 is not scoped to exclude the agent
  image.
- **Fix:** Scope G1 to the toolchain, tools and runner images, and say the
  agent image is unpinned by choice. Say that D41's approval is per plugin,
  not per content change. Record the commit each marketplace was at for every
  build. Add the combined risk to the table.
- **Raw:** zo-7, ic-14, ic-20, zo-21, des-16.
- **Codex review:** holds. D41 governs adding a plugin and D152 governs updating it, so the gap is unreviewed content arriving through updates.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #228.

#### F16. The risk table lacks the D155 and D148 risks that no other finding carries

- **Severity:** Major
- **Sections:** Risks & Mitigations (1581-1625); §12 Accepted risks
  (1378-1381).
- **Decisions:** D148, D155.
- **Problem:** §12 states D155's accepted risks, but the risk table has no
  row for them: org-wide App reach, and a copyable long-lived
  `CLAUDE_CODE_OAUTH_TOKEN`. The table also has no row for D148's shared
  preset and hk-config import, which every project trusts at a tag, making
  them a single point of compromise.
- **Fix:** Add a row for each, with its trigger, mitigation and decision.
- **Raw:** cp-11, ir-10, des-7.
- **Codex review:** partly holds. The runner-slot, agent-image, Action SHA
  and plugin rows are carried by F1, F7, F8 and F15. D138 already documents
  failure and undo, and D140 already has a version warning. Those were
  removed here.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F17. Alternatives lists none of the options D136 to D155 rejected

- **Severity:** Nit
- **Sections:** Alternatives, "From the review stages" (1483-1580).
- **Decisions:** D138, D139, D140, D143, D147, D151, D153, D155.
- **Problem:** The feature-spec standard requires rejected options with
  their reasons. The decision rows record them, but the design does not.
  Examples:
  - D138: a plain HTTP proxy, TLS MITM, a fallback to direct;
  - D140: `seccomp=unconfined`, CDI;
  - D143 and D147: the `agents:sync` seed volume;
  - D151: Docker Sandboxes;
  - D153: a per-container gh login;
  - D155: widening the skills-sync App, a workspace Codex token, and the
    broker and branch guard;
  - D139: keeping machine setup in dotfiles.
- **Fix:** Add one entry per decision, with its reason.
- **Raw:** des-8.
- **Codex review:** partly holds. The decision rows give the reasons, §12 names the superseded seed volume and logins, and lines 1570-1576 already carry D149's alternatives. The design still omits the others. Downgraded to a Nit.
- **Recommendation:** keep, as a Nit.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F18. §11, §12 and the shared repositories have no place against the Level 1 date

- **Severity:** merged into F19
- **Sections:** Overview (28-40); The Problem (157-160); §10 Critical path and Cut order (1159-1217); §11; §12.
- **Decisions:** D136, D137, D139, D141, D143, D148, D150, D152, D155.
- **Why:** Codex review: the M1a cut and the time-budget decision recorded after D155 define what must pass by 2026-11-27. What is left is that the design text does not say §11 and §12 sit outside that, which is part of F19's scope and plan-reference item.
- **Raw:** zo-1, cp-2, ic-13.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F19. Detailed Implementation has no rows for what D136 to D155 added, and does not place that work against the Level 1 date

- **Severity:** Major
- **Sections:** Overview (28-40); §10 Critical path and Cut order
  (1159-1217); Detailed Implementation introduction (1627-1636); M1a file
  plan (1837-1897); Schema task list (1909-1912); Files changed elsewhere
  (2015-2026); §11 apt cache (1328-1331); §12 OpenCode (1376-1377).
- **Decisions:** D136, D137, D138, D139, D140, D141, D142, D143, D144, D145,
  D147, D148, D150, D151, D152, D154, D155.
- **Problem:** No row covers any of these:
  - `docs/standard/{macos,ubuntu}.md`, `ubuntu-cert.Dockerfile`,
    `ubuntu-seccomp.json`, `agents.Dockerfile`, `agent-plugins` and
    `agent-auth/*`;
  - `mise.{pc,mac,ubuntu,ubuntu-cache}.toml`;
  - the `certify:*`, `pc:*` and `agents:*` tasks.

  The owner's one-time steps (`agents:app-create`, `agents:pc-doppler`,
  `agents:agy-login`) have no setup step. `mise.ubuntu.toml` is a second
  owner of Ubuntu apt pins next to the planned `apt*.toml`, and the design
  never names it. Folded in from F37, the apt-cache bullet relies on that
  unnamed `ubuntu` environment.

  Folded in from F18: the M1a cut defines what must pass by 2026-11-27, but
  the design text does not say that §11, §12 and the shared repositories sit
  outside it. Folded in from F36: a container made before D154's model change
  needs a one-line edit on its old volume, and no step owns that.
- **Fix:** Add a table of the machine and agent-container files, with these
  columns: path or task, decision, status, who runs it, its check, and (O),
  (P) or neither. Extend the task list. Say which file owns the Ubuntu apt
  pins. State that §11, §12 and the shared repositories are outside the
  Level 1 gate, and point to the decision that defines it.
- **Raw:** ir-8, cp-2, cb-11; plus F18 (zo-1, cp-2, ic-13), F36 (zo-21) and
  F37 (cp-13).
- **Codex review:** holds as merged.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed in part; the
  remainder moved to #247, which finished it in the design.

#### F20. The Glossary still calls the dotfiles setup agent the only installer, and the Tart step gives no digest

- **Severity:** Major
- **Sections:** Glossary "the setup agent" (80); §6 Credential storage
  (947-949); Tart on the Mac (1730-1735); M2 `pc-runner.md` row (1981);
  Files changed elsewhere (2019-2024).
- **Decisions:** D136, D139, D141, D150, D155.
- **Problem:** The text says the dotfiles setup agent is "the only session
  that installs or changes software and credentials on the owner's
  machines". cpp-standard tasks now make Doppler tokens and an App, and
  register host services. Which migration phase moves which role is not
  stated. The Tart step says the agent pulls the image "by digest", but it
  gives no digest value (design lines 1733-1735).
- **Fix:** Redefine the setup agent as a role that ends piece by piece,
  naming the migration phase for each piece. Give the full image reference
  with its digest in the Tart step.
- **Raw:** cp-1, zo-13, ir-11, des-15.
- **Codex review:** partly holds. Tart is already pinned at 2.41.1 in
  `.mise/conf.d/vm.toml`, so "make Tart a cpp-standard pin" was removed. The
  stale installer role and the missing digest stand.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F21. The Non-Goals still exclude the agent-setup cleanup that D150 takes on

- **Severity:** dropped
- **Sections:** Non-Goals (236-239).
- **Decisions:** D141, D150.
- **Why:** Codex review: the migration plan moves the agent rules unchanged as one shared source (machine-bootstrap-migration.md, line 274). Copying existing rulings is not the "cleaning up" that design lines 236-239 exclude, and those lines already include the migration.
- **Raw:** zo-2, ic-15.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F22. Agent-runnable tasks and the image build run `agy`, which D155 and AGENTS.md forbid

- **Severity:** Blocker (for agent use of the affected tasks)
- **Sections:** §12 Plugins and skills (1349-1356) and Subscriptions
  (1371-1375); Open Questions.
- **Decisions:** D147, D152, D155.
- **Problem:** AGENTS.md and design line 1375 say no agent runs `agy`. The
  owner's D155 ruling governs this. The following run it with no guard:
  - `agents:refresh` runs the agy installer, `agent-plugins refresh` (which
    runs `agy plugin install`) and `agy --version` inside the running
    container, which holds the persistent login volume
    (`.mise/tasks/agents/refresh`, lines 19-22);
  - the image build runs `agy --version` and `agy plugin install`
    (`agents.Dockerfile`, lines 73 and 101).

  The guard on `agents:agy-login` checks only that stdin and stdout are
  terminals (lines 15-18), and an agent session can have a terminal.
  Dropping the agy plugins alone would leave the `--version` calls. Folded
  in from F34: "how the Antigravity CLI's plugins come back" is open inline
  but not in Open Questions.
- **Fix:** Remove every `agy` call from agent-runnable build, refresh and
  version-reporting paths. Put any call that is needed into a separate
  owner-started action, with a guard that does not rest on a terminal check.
  Reconsider the rule only through a new explicit owner decision.
- **Raw:** zo-16, ic-12, cb-6, des-18; plus F34's agy-plugin part (cp-15).
- **Codex review:** holds and widens (`refresh`, line 22; `agents.Dockerfile`,
  line 73; `agy-login`, lines 15-18). Two of the three earlier options left
  the violation in place, so the options were removed. Raised from Major.
- **Recommendation:** keep, as a Blocker.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; D166 and
  D167 had settled the rest.

#### F23. §12 describes plugin and skill mechanisms that are not the ones built

- **Severity:** Major
- **Sections:** §12 Plugins and skills (1349-1356); §7 (1083-1085).
- **Decisions:** D143, D145, D147, D148, D152.
- **Problem:**
  - D147 decided on "no sync code of our own" and `mise dot` tracking. §12
    instead names the `agent-plugins` script, and no decision row records
    the switch. The tracked-config replay D147 planned is not carried over.
  - §12 says the shared `~/.agents/skills` folder exists in containers and
    that Claude Code reads it through a link. The agents image creates
    neither, and `~/.claude` is a per-container volume.
  - The `ray-manaloto/skills` marketplace is added for Claude Code only.
- **Fix:** Record the switch to the script as an amendment of D147, or carry
  the replay over. Fix the skills-folder claim, or the Dockerfile. Name the
  harnesses that get the skills marketplace.
- **Raw:** zo-17, ic-11, cb-7, des-16.
- **Codex review:** partly holds. D144 and D145 do cover both Spack and
  skills, so cp-14's citation complaint was removed.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed (D171).

#### F24. Spack's pre-image probe has no owner or output

- **Severity:** Nit
- **Sections:** §11 Spack (1332-1337); Open Questions.
- **Decisions:** D142, D144, D145.
- **Problem:** §11 marks Spack's container probe as open, but names no owner
  and no output. It says the probe decides which apt packages mise now
  supplies, without naming the apt list it changes. Its tense ("Below it sit
  apt … plus `gfortran-16`") reads as present, though no config installs
  `gfortran-16` yet. Folded in from F34, the probe is not in Open Questions.
- **Fix:** Name the probe's owner, its output and the apt list it changes.
  Mark the Spack layering as planned. Add the probe to Open Questions.
- **Raw:** zo-15, cp-12, ic-18, cb-19, des-24; plus F34's probe part
  (cp-15).
- **Codex review:** partly holds. Downgraded from Major to documenting the
  probe.
- **Recommendation:** keep, as a Nit.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed in part; the
  remainder moved to #247, which finished it in the design.

#### F25. M2 reconciliation: `m2-trust-backlog.md` against §12, D149 and D155

- **Severity:** Major
- **Sections:** §12 (1341-1382); M2 entry gate (1259-1292), through
  m2-trust-backlog.md.
- **Decisions:** D143, D149, D155.
- **Problem:** The backlog calls itself deferred starting material for the
  M2 design. Its des-4-5 item asks for a PC devcontainer that opens only
  `main` or owner-authored commits, with no host mounts. §12's project
  containers open agent branches and bind-mount host folders. Whether
  des-4-5's devcontainer is the same thing as the §12 project container is
  not established. The backlog does not mention D149 or D155.
- **Fix:** When the M2 trust design starts, reconcile the backlog with §12.
  Say whether des-4-5 covers the project containers. Add D149's dropped
  review and D155's App as inputs.
- **Raw:** zo-18, des-4.
- **Codex review:** partly holds. Recast from "stale" to an M2 reconciliation
  item, because the backlog is deferred material by its own account.
- **Recommendation:** keep, recast as above.
- **Owner:** kept (ticket #142, 2026-11-18): moved to #219.

#### F26. §11 should carry D140's full launch contract, and keep the certification receipt apart from the gate's

- **Severity:** Major
- **Sections:** §11 Certification playbooks and Containers on the PC
  (1317-1327).
- **Decisions:** D136, D137, D140.
- **Problem:** §11 gives the certification container `--cap-add PERFMON` and
  the seccomp profile, but not `-e container=docker`. D140 records why that
  matters: an apt run in a privileged container once changed the PC's
  sysctls. The launcher sets it (`.mise/tasks/certify/ubuntu`, line 125), but
  an implementer following only §11 would miss it, along with the device
  scope and the profile-version warning. §11 also does not separate a
  certification result from the Level 1 gate's result. Folded in from F28:
  a certification result for one image does not cover another image.
- **Fix:** Carry D140's complete launch contract into §11 by reference: the
  startup environment, the device scope and the profile-version warning.
  Name the certification receipt separately from the gate receipt.
- **Raw:** cp-8; plus F28's certification part (des-19).
- **Codex review:** holds as replaced. PERFMON is approved, and D137 keeps
  R2 counters outside the Level 1 gate. The missing `container=docker`
  holds (`certify/ubuntu`, line 125).
- **Recommendation:** keep, as replaced.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F27. There are two p2996 build configurations

- **Severity:** Major
- **Sections:** §11 (1317-1324); M0 results (h) (1241-1244); M1a
  `toolchains/p2996/build.sh` row (1860); Risks row 1592.
- **Decisions:** D136, D137.
- **Problem:** D136 builds p2996 with every LLVM project and runtime that
  builds on the platform. On Ubuntu it adds offload and NVPTX, and D137 uses
  that configuration on the PC. The M1a row and the M0 (h) budget build only
  the C++ runtimes. The text does not say which configuration is the
  standard, or whether the larger set fits the hosted budget.
- **Fix:** State that the certified host p2996 is a separate install with
  its own name and inputs, and that the CI toolchain keeps the M0 (h) set.
  Alternatively make them two flag sets of one `build.sh` (D85).
- **Raw:** ic-10, des-14.
- **Codex review:** holds: the larger D136 build profile is unmeasured against the hosted budget.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed; moved to
  #226.

#### F28. Four Ubuntu images with separate pins, and none of them both certified and gated

- **Severity:** merged into F14, F26 and F27
- **Sections:** Overview items 4-5 (28-32); §11 (1317-1324); §12 (1343-1347); devcontainer row (1866).
- **Decisions:** D137, D143, D155.
- **Why:** Codex review: there is no Spack image yet, and the two present Dockerfiles share one Ubuntu base digest (agents.Dockerfile, line 16; ubuntu-cert.Dockerfile, line 17). The duplicate declarations go to F14, the certification-versus-gate evidence to F26, and the larger build profile to F27.
- **Raw:** des-19.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F29. A public file under `docs/standard/` names a private machine and a private repository

- **Severity:** Major
- **Sections:** §11 (1302-1311), for the files D141 moved in; Open Questions
  Q1 (252-258).
- **Decisions:** D141.
- **Problem:** The runner README that D141 moved into this public repository
  names the PC's machine name and a private repository in its first lines.
  The project's rule keeps machine names in Doppler. Q1's scrub covered only
  `docs/designs/`. The Elephant confirmed the lines at 283866d; they are not
  repeated here. The repository named is private (checked with
  `gh repo view`).
- **Fix:** Scrub the README now. Widen Q1's scrub to `docs/standard/**`, and
  add a check that keeps it clean.
- **Raw:** cb-17, rated Nit by that reviewer; the Elephant raised it to
  Major because the leak is live in a public repository.
- **Codex review:** holds. The identifiers are present in the README's first lines; repository visibility was checked with `gh repo view`, not by Codex.
- **Recommendation:** keep, and fix it ahead of the resolve step.
- **Owner:** kept (ticket #142, 2026-11-18): moved to #223.

#### F30. "Tailnet names, never LAN addresses" against a break-glass LAN alias

- **Severity:** Nit
- **Sections:** §11 Machine configs (1313-1316).
- **Decisions:** D150.
- **Problem:** `mise.mac.toml` renders a break-glass `pc-lan` SSH host from
  `PC_LAN_HOST`, and the migration plan keeps it.
- **Fix:** Record the break-glass exception in §11, or drop the alias.
- **Raw:** cb-9, des-21.
- **Codex review:** holds as a real D150 exception (`mise.mac.toml`; migration plan, line 273). Downgraded, because nothing shows routine use of the break-glass route.
- **Recommendation:** keep, as a Nit.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F31. Retiring the unused `GEMINI_API_KEY` needs the provisioning contract changed first

- **Severity:** Nit
- **Sections:** §12 Logins and Accepted risks (1361-1381).
- **Decisions:** D155.
- **Problem:** `agent-secrets` no longer uses `GEMINI_API_KEY`, but
  `agents:pc-doppler` still lists it among the names it requires
  (`.mise/tasks/agents/pc-doppler`, line 28) and copies it from the source
  config (line 120). Deleting only the destination value lets the helper
  restore it. Removing both copies makes the next provisioning run stop.
- **Fix:** If the key is retired, change the provisioning contract first.
  Verify a rerun and a rotation without that name, then remove the key from
  the intended config only.
- **Raw:** des-17. The token-scope part (ic-19, cp-6) moved to F1 and F6.
- **Codex review:** holds (`pc-doppler`, lines 28 and 120). The heading
  change was dropped: D155's Claude credential is a subscription OAuth
  token, so "Subscriptions, not API keys" is accurate.
- **Recommendation:** keep, narrowed as above.
- **Owner:** kept (ticket #142, 2026-11-18): moved to #224.

#### F32. On the Xcode base, the weekly CUJ 1 run means something else (an M3 item)

- **Severity:** Nit
- **Sections:** M3 `mac-gate.yml` row (1992); §11 (1322-1324); §8 table
  (1126-1127).
- **Decisions:** D136.
- **Problem:** `macos-golden-gate-xcode:27.2` comes with Xcode installed, so
  the weekly "CUJ 1 run from vanilla" no longer proves an Xcode or CLT
  install from a clean macOS. D136's measurement of CPU counters on the host
  also has no line in the §8 table.
- **Fix:** In the M3 PR that D136 names, restate what the weekly CUJ 1 run
  proves on the Xcode base. Reconcile the host counter measurements with §8,
  alongside F26.
- **Raw:** cp-9, zo-22, ir-12, ic-17, des-23.
- **Codex review:** partly holds. D136 and design lines 1322-1324 defer the
  vanilla-reference edits to M3 on purpose, and the `vm/inputs.toml` row
  (1987) names no vanilla image. The naming complaint and the "change now"
  fix were removed.
- **Recommendation:** keep, as an M3 item.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F33. The migration steps M1 to M3 share names with the milestones

- **Severity:** dropped
- **Sections:** §11 Machine configs (1313-1316); Glossary Milestones (76).
- **Decisions:** D150.
- **Why:** Codex review: §11 already says "migration step M1" (design line 1315), which tells the two apart.
- **Raw:** cp-18, zo-20, ic-16.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F34. Stale statements about `AGENTS.md` and the `mise.pc.toml` header

- **Severity:** Nit
- **Sections:** M1a `AGENTS.md` row (1840); §11 (1302-1311).
- **Decisions:** D141, D155.
- **Problem:** The `AGENTS.md` row says the file "holds only the EGM notes",
  but it now has the `agy` rule and the skills sections. The `mise.pc.toml`
  header still says the dotfiles file applies until Phase 3, but Phase 3 is
  done.
- **Fix:** Update the row and the header.
- **Raw:** cb-15. The probe and agy-plugin questions (cp-15) moved to F24
  and F22.
- **Codex review:** holds as narrowed.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed in part; the
  remainder moved to #247, which finished it in the design.

#### F35. The Glossary's "Agent session" names only Claude and Codex

- **Severity:** Nit
- **Sections:** Glossary "Agent session" (79).
- **Decisions:** D154.
- **Problem:** §12 adds OpenCode and the Antigravity CLI as agents in
  project containers. D155's rule that only the owner runs `agy` still
  applies.
- **Fix:** Widen the definition to the participating agents, and keep the
  owner-only `agy` rule beside it.
- **Raw:** cp-19. The owner-switch convention moved to F13.
- **Codex review:** holds as narrowed.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F36. The design names a model ID that has already changed once

- **Severity:** dropped
- **Sections:** §12 OpenCode (1376-1377).
- **Decisions:** D154.
- **Why:** Codex review: D154 records the current model on purpose. The old-volume migration it implies moved to F19.
- **Raw:** zo-21.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F37. The apt-cache bullet assumes an undefined `ubuntu` environment

- **Severity:** merged into F19
- **Sections:** §11 apt cache (1328-1331).
- **Decisions:** D138.
- **Why:** Codex review: the unnamed `mise.ubuntu.toml` is part of F19's apt-pin ownership item.
- **Raw:** cp-13.
- **Owner:** dispositioned with the finding it was merged into, or not at all if dropped.

#### F38. Setup step 1 still describes the commit review that D149 ended

- **Severity:** Nit
- **Sections:** setup step 1 (1650-1651).
- **Decisions:** D149.
- **Problem:** Step 1 still says the step is "reviewed by a separate agent
  session (the commit review)", and D149 ended that review.
- **Fix:** Mark step 1's review as historical, without rewriting what D149
  said at the time.
- **Raw:** ic-21. The stale trust-root list (des-20) moved to F2.
- **Codex review:** holds as narrowed.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F39. M0-Linux's end date is the planned date; its exit review happened a day later

- **Severity:** Nit
- **Sections:** M0-Linux exit review (1294-1298); Glossary Milestones (76);
  M0 results (1221-1222).
- **Decisions:** D149.
- **Problem:** D84 planned the M0-Linux exit review for 2026-11-16. D149
  records that it was held on 2026-11-17. Design lines 76 and 1221-1222
  still give 2026-11-16 as the end date, without saying it was the plan.
- **Fix:** Label 2026-11-16 as planned and 2026-11-17 as actual. Leave D84
  and D149 as recorded.
- **Raw:** cp-21.
- **Codex review:** holds (D84 at decisions-log.md, line 92; D149 at line
  157). The earlier drop recommendation was reversed.
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): the design text changed.

#### F40. `agent-secrets` registration reports success with a stale token

- **Severity:** Major
- **Sections:** §12 Logins with no typing (1361-1370).
- **Decisions:** D155.
- **Problem:** `refresh_dirs` logs and skips a repository whose token cannot
  be minted (`agent-secrets.bash`, lines 108-111). `register` then accepts
  any non-empty token file that already exists (lines 142-145). A project
  registered earlier therefore reports success while it holds an expired
  token.
- **Fix:** Make registration tell a fresh usable token from stale state.
  Add an acceptance case: break the dependency, check that registration
  fails, then restore the dependency and check that it recovers.
- **Raw:** new item from the Codex adversarial review.
- **Codex review:** holds (`agent-secrets.bash`, lines 108-111 and 142-145).
- **Recommendation:** keep.
- **Owner:** kept (ticket #142, 2026-11-18): moved to #221.

## Disposition table

One row per decision. "Sections" are the design sections the decision
touches: where the design cites it, plus the main sections its findings name
(each finding lists its own sections in full).
The resolve step (ticket #142, 2026-11-18) set each disposition to
"reviewed, no change", "changed in the design" (with the sections changed)
or "moved to #<issue>"; a decision with both kinds of finding has both in
one cell. Findings moved: F1 to #218; F3 and F25 to #219; F10 to #220; F7
and F40 to #221; F12 and F13 to #222; F29 to #223; F31 to #224; F27
to #226; F2 to #227; F15 to #228. For a moved finding the design states what
is open and names the issue. Six findings changed the design only in part:
the remainder of F2, F6, F14, F19, F24 and F34 moved to #247, which
finished F6, F14 (with D175 and #252), F19,
F24 (with #253) and F34, and left F2 blocked on #227. F22 was
settled before this step by D166 and D167. Four decision rows came out of
it: D170 (F8), D171 (F23), D172 and D174 (F1).

| Decision | Design sections | Findings | Merged or dropped here | Disposition |
|---|---|---|---|---|
| D136 | §11 Certification playbooks; G1; §8 table; Tart setup step; M3 file plan; §10 Cut order | F19, F20, F26, F27, F32 | F18 (to F19) | changed in the design (§8; §11 Certification playbooks and Containers on the PC; Glossary; the Tart setup step; Files changed elsewhere); moved to #226 and #247 |
| D137 | §11 Certification playbooks and Containers on the PC; §6 Credential storage; M2 entry gate; Alternatives | F1, F3, F19, F26, F27 | F18 (to F19), F28 (to F14, F26 and F27) | changed in the design (§6 Public repository and The fence; §11; Alternatives; Risks); moved to #218, #219, #226 and #247 |
| D138 | §11 apt cache; Alternatives; Detailed Implementation | F17, F19 | F37 (to F19) | changed in the design (§11 apt cache; Alternatives; Files changed elsewhere); moved to #247 |
| D139 | Overview; Glossary (setup agent); Non-Goals; §11 Machine configuration; Files changed elsewhere | F2, F17, F19, F20 | F18 (to F19) | changed in the design (Glossary; §6 Trust roots; the Tart setup step; Files changed elsewhere); moved to #227 and #247 |
| D140 | §11 Containers on the PC; Alternatives; Detailed Implementation | F17, F19, F26 | none | changed in the design (§11 Containers on the PC; Alternatives); moved to #247 |
| D141 | §11 Machine configuration; §6 The fence, Runner VMs, Identities, Credential storage; Trust and Owned roots | F1, F2, F6, F19, F20, F29, F34 | F4 (to F1), F18 (to F19), F21 (dropped) | changed in the design (§6 Public repository, Identities, Credential storage and Trust roots; Glossary; §11; Open Questions Q1; Risks; the `AGENTS.md` row); moved to #218, #223, #227 and #247 |
| D142 | §11 Spack; Open Questions | F19, F24 | none | changed in the design (§11 Spack; Open Questions Q9); moved to #247 |
| D143 | §12 Project agent containers; §9 Agents; Settled questions; G5; §6 The fence | F3, F15, F17, F19, F23, F25 | F5 (to F3), F18 (to F19), F28 (to F14, F26 and F27) | changed in the design (G1; §6 The fence; §9; §12 Plugins and skills; Alternatives; Risks); moved to #219, #228 and #247 |
| D144 | §11 Spack; §12 Plugins and skills | F19, F24 | none | changed in the design (§11 Spack; Open Questions Q9); moved to #247 |
| D145 | §11 Spack; §12 Plugins and skills | F19, F23, F24 | none | changed in the design (§12 Plugins and skills, by D171; §11 Spack); moved to #247 |
| D146 | §11 mise pin; Schema of the configuration; Alternatives | F14 | none | changed in the design (§11 mise version); moved to #247 |
| D147 | §12 Plugins and skills; §9 Agents; Open Questions | F15, F17, F19, F22, F23 | none | changed in the design (§12 Plugins and skills, amended by D171; §9; Alternatives; Risks); moved to #228 and #247 |
| D148 | §7 Updates; §3 [settings]; Schema; Open Questions (Q6); M1a and M1b file plans | F8, F12, F13, F15, F16, F19, F23 | F18 (to F19) | changed in the design (§3; §7; Schema; Risks; the `renovate.json5` row; D170); moved to #222, #228 and #247 |
| D149 | Status header; §6 Trust roots, Owned roots, settings check; §7 Merge rule; §10 M2 entry gate, M0-Linux exit review; Risks; setup steps; M1a file plan | F1, F2, F8, F9, F10, F11, F25, F38, F39 | none | changed in the design (Status; Glossary; §6 Trust roots and the settings check; §7; §10; Risks; setup step 1; the `spikes/m2/README.md` row; D170 supersedes D118); moved to #218, #219, #220, #227 and #247 |
| D150 | Overview; Non-Goals; Glossary; §11 Machine configuration; Files changed elsewhere | F1, F2, F3, F19, F20, F30 | F18 (to F19), F21 (dropped), F33 (dropped) | changed in the design (Glossary; §6 Trust roots and The fence; §11 Machine configs; Alternatives; Files changed elsewhere); moved to #218, #219, #227 and #247 |
| D151 | §12 Logins, Subscriptions; Alternatives | F17, F19 | none | changed in the design (Alternatives; Files changed elsewhere); moved to #247 |
| D152 | §7 Updates; §9 Agents; §12 Updates; G1; Risks | F7, F8, F12, F13, F15, F19, F22, F23 | F18 (to F19) | changed in the design (G1; §7; §9; §12 Plugins and skills; Risks); moved to #221, #222, #228 and #247 |
| D153 | §12 Logins; Glossary and §6 Identities; setup step 6 | F6, F17 | none | changed in the design (Glossary; §6 Identities and Credential storage; setup step 6; Alternatives); moved to #247 |
| D154 | §12 OpenCode; Glossary (Agent session) | F19, F35 | F36 (dropped) | changed in the design (Glossary, Agent session; Files changed elsewhere); moved to #247 |
| D155 | Overview; §12 Logins, Subscriptions, Accepted risks; §6 Identities, Credential storage; Trust roots; M2 entry gate; Settled questions | F1, F2, F3, F6, F7, F15, F16, F17, F19, F20, F22, F25, F31, F34, F40 | F4 (to F1), F5 (to F3), F18 (to F19), F28 (to F14, F26 and F27) | changed in the design (Glossary; §6 Public repository, Identities, Credential storage and Trust roots; §10 M2 entry; setup step 6; Alternatives; Risks; the `AGENTS.md` row); moved to #218, #219, #221, #224, #227, #228 and #247 |

## Certification failures

Ticket #142 also lists the failures the two certifications left.

- **Ubuntu, E2:** clangd 23.1.5 beside clang 23.1.6. D137, an owner-sourced
  row, records that E2 stays FAIL while clangd's version differs from the apt
  snapshot; the owner took that as the recorded acceptance (ticket #142,
  2026-11-18). No check exempts it: it stays a FAIL in the certification
  output until the versions match.
- **macOS, P10:** linking a p2996 program with `-fuse-ld=lld`. The owner
  accepted it as a known upstream failure (D172).

## Outside scope

These raw findings concern decisions outside D136 to D155. They are not
part of this review's dispositions. They are passed to the coordinator for
triage.

- **cb-1 (Blocker): §6 Credentials and Every merge goes through the merge
  queue.** Concerns D23 and D109. The design says the `main` ruleset has "no
  bypass actor", and that the check "never fails because one was added".
  `main.json` has an OrganizationAdmin bypass in pull-request mode.
  `--verify` requires that bypass, counts the org admins, and fails on any
  parameter that differs from `main.json`, so an added protection fails the
  check. Moved to #225.
- **cp-20 and zo-20: Status, Inputs and M1a.** The design cites the four decisions recorded after
  D155 and "Spec #122", while the header and Inputs say "D1 to D155". The review
  state of those four decisions is not stated.
- **ir-14 and part of cb-15: "PR 6" references after the M1a cut.** Many rows and
  steps still say "PR 6". The `AGENTS.md` and devcontainer rows also belong
  here. The agent App's `actions: write` removal moved out of M1a, and the
  manifest still grants it.
- **cb-18: §6 Job permissions.** `author-email.yml` has no row.
- **cb-20: file plan row 1892.** The row names an owner-run `--apply`, but
  the task has no such flag; it applies when `--verify` is absent.

## Appendix: comprehension paraphrase

The `egm-comprehension` reviewer read only the design. This is its account,
kept as the protocol requires.

**What this proposes.** D136 to D155 add three things to Level 1.

1. cpp-standard takes over machine setup for the Mac and the PC, and in the
   end all of dotfiles, through a migration plan. This brings per-host mise
   configs, certification checklists, an apt cache, Spack in throwaway
   containers and a newer mise pin.
2. Each project and its agents run in one container. Plugins come from each
   agent's own CLI, unpinned. A host service hands each container
   short-lived GitHub App tokens and the Claude Code token, so no one logs
   in.
3. D149 drops the M2 code-owner review, so trust roots merge on green checks
   like any other file. D148 and D152 add shared Renovate, hk and skills
   repositories and remove the release cooldown.

**How the existing system works, per the design.**

- Agents open PRs as the `cpp-standard-agents` App.
- Every PR runs the Linux gate on hosted runners, with no secrets, and
  merges through the merge queue once the required checks pass. No human
  approves anything.
- Only `publish.yml` signs. `toolchain:fetch` and `image:verify` check its
  attestations.
- From M2, the self-hosted runners take only allowlisted `main` workflows,
  each in a throwaway VM behind a job-start hook.
- The owner looks after merge.
- A daily `repo:rulesets --verify` checks the settings.
- Until each migration step, dotfiles keeps running what it runs.
