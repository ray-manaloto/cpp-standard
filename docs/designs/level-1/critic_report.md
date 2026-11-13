# Stage 7: Critic Review

* **Target:** `docs/designs/environment-standard.md`, FeatureRange lines 1-901
* **Date:** 2026-11-13
* **Reviewers:** `egm-design`, `egm-structural` and `egm-style`, run in parallel in fresh contexts. The design and structural reviewers used `feature-spec-standard.md`.
* **Verdicts:**
  - design: 2 Blocker, 10 Major, 7 Nit;
  - structure: 6 Major, 10 Nit;
  - style: 13 Major, 23 Nit.
* Line numbers refer to the design before any Stage 7 fix.

## 🔴 Blockers (design)

**K1. Any PR branch workflow can run on the owner's PC and Mac.**
- D54 accepted that a same-repo PR runs its own workflow file before review, but only the GHCR-write side of that was considered. The same workflow file can also set `runs-on: [self-hosted, …]`.
- A runner registered to this repo, or to the org's default group, accepts jobs from any workflow on any event. CODEOWNERS and the ruleset only govern merges.
- So nothing enforces "the PC and Mac run only reviewed `main` code" (§6, G8, D48).
- Restricting a runner group to selected workflows is probably not available on the Free plan; the reviewer marked this *verify*.
- Agents working from a fork would not fix this either: fork PR workflows can also target self-hosted runners.
- **Fix options:**
  - **(a) A runner-side job-started hook** (`ACTIONS_RUNNER_HOOK_JOB_STARTED`). It aborts unless the event is push, schedule or dispatch on `refs/heads/main`, and the workflow is on an allowlist baked into the runner image.
  - **(b) Register the self-hosted runners only to a separate repository that agents can't push to.** `main` triggers it with an explicit SHA.
  - **Either way:** add an M1a negative test (an App PR adding a `runs-on: self-hosted` job must not run), and a new weak point.

**K2. Tags named by hash, first writer wins, and PR publishing together let unreviewed builds become `main`'s artifacts.**
- The tag covers only the input files. PR builds publish into the same namespace that `main` consumes, and "never overwrite" is enforced only by our own task (D54).
- Future hashes are predictable (the next p2996 commit is public). So a branch workflow can pre-publish a poisoned artifact under a future tag, and the `main` builder then skips the build because the tag exists.
- The sha256 annotation is written by the same publisher, so it proves nothing.
- Every consumer runs these compilers, including the PC and the Mac. That is a second way past the fence.
- The owner accepted D54 without seeing this consequence.
- **Fix:**
  - PR artifacts get their own namespace (`…-pr-<n>-<hash>`), which `main`, the runners and the VM never use.
  - Only builder runs on `main` publish the tags `main` uses, and they never skip a tag that a non-`main` run created.
  - **GitHub artifact attestations** are checked on every non-PR pull (`--signer-workflow …/builder.yml --source-ref refs/heads/main`).
  - Optionally, push the `main` tags with a credential held only in the `main`-restricted Environment, so the Environment actually protects something (*verify* that GHCR accepts App tokens).
  - Re-record D54 with its full consequences.

## 🟡 Major

| # | Finding | From | Lines |
|---|---|---|---|
| K3 | **The merge queue builds input combinations that no builder ever built.** Two queued PRs that both touch inputs produce a merged commit with a new hash. `artifact:check` stays pending, so the queue stalls, and with daily Renovate this will happen routinely. Fix: run the builder on `merge_group` and post its status to the merge-group SHA. Or queue input-changing PRs one at a time and group all tools bumps into one daily PR. Give `artifact:check` a timeout. | design M1 | 256-261, 300-305, 473-495 |
| K4 | **p2996 and GCC automerge (D56) contradicts the Mac gating.** The p2996 commit is also in `macos.inputs.toml`. Mac hashes build only after the owner approves, and `artifact:check` needs every tag. So every p2996 PR waits for the owner anyway. Fix: limit `artifact:check` to Linux tags, build Mac toolchains only after merge from `main`, and bump `macos.inputs.toml` in a separate PR that the owner reviews. | design M2 | 294-297, 480-481, 495, 702-710 |
| K5 | **Owner approval is per PR, not per commit, and the trigger for the Mac job is undefined.** An agent can push new commits after the owner approves. A `pull_request_review` event would run the branch's own workflow file. Fix: start Mac PR jobs only through a `workflow_dispatch` defined on `main`, with an explicit SHA that must match the approved review's `commit_id`. Require the ruleset settings "dismiss stale approvals" and "require approval of the most recent push". Make `repo:rulesets --verify` check those settings, the merge queue and the list of required checks. | design M3 | 432-437, 480-481, 654-655, 685-687 |
| K6 | **Agents can weaken the gate's own guards without review.** Presets, probes and `src/` merge without the owner. A PR can drop `-fsanitize=thread` from a preset, or add coverage-exclusion markers, without changing the capability lock. The fixtures don't run on such a PR, and "exclusions checked in review" names no reviewer. Fix: make presets and `probes.cmake` owned roots, or run `ci-must-fail` on every PR that touches `cmake/**`. Add a tier-1 check that compares exclusion markers against an owned allowlist. | design M4 | 593-596, 607-624, 677-679 |
| K7 | **The PC runner as described can't run its jobs.** It is "unprivileged, with no Docker socket", but it must run `container:` jobs and build images. Fix: say how. Either the runner image is built from the tools tag and runs jobs without `container:`, or it uses rootless podman or sysbox, with the trade-off stated. | design M5 | 476-479, 639, 653-657 |
| K8 | **Nothing updates `inputs.toml` when the base image changes the builder's environment.** An automerged glibc, binutils or `g++-16` bump breaks the next toolchain build on `main`. Fix: build Linux toolchains inside the base tag. Add `toolchain:declare --check` on PRs that change the base, or have Renovate update `inputs.toml` in the same PR through `postUpgradeTasks`. | design M6 | 449, 454-466 |
| K9 | **A hosted p2996 build is on the critical path but unproven.** Hosted runners have about 14 GB of free disk. The 61-76 minute figure was measured without compiler-rt, and the arm64 figure is unverified. Fix: add M0 (h), a cold build with compiler-rt on `ubuntu-26.04-arm` that records peak disk and wall time, plus written fallbacks. | design M7 | 476-477, 753 |
| K10 | **The Mac golden VM would rebuild daily, fill the disk and collide with the two-VM limit.** Its hash covers all of `tools.toml` and `mise.lock`. Each image is 35-50 GB, and nothing deletes old ones. Fix: hash only the macOS inputs, keep the last 2 images, build in the runner slot, and state the disk budget. | design M8 | 450, 539-547 |
| K11 | **The Ubuntu digest and the mise version sit in an owned root, so they need daily owner reviews.** Fix: move them into `image/base.inputs.toml`, a pins file, and pass them as build arguments. | design M9 | 449, 530-533, 673-674 |
| K12 | **The PC's Docker is reachable from the agent VM, which contradicts the fence.** `DOCKER_HOST=ssh://<linux-host>` is root on the PC. Line 214 also lets agents use "the PC devcontainer". Fix: PC SSH and Docker credentials exist only on the host, never in the agent VM. Reword the fence. | design M10 | 63, 174-175, 214, 549-553 |
| K13 | **Agent App permissions and its key.** `linux:run` needs Actions write to dispatch a workflow, which the App doesn't have (*verify*). Agents that hold the App's private key could leak a credential that never expires and has `workflows: write`. Fix: either add Actions write, or have `linux:run` open a draft PR instead. Keep the key on the host behind a broker that hands only short-lived tokens to the VM. | design M11 | 82, 549-551, 659-661 |
| K14 | **There is no Risks & Mitigations section,** which the standard requires. "Weak points" mixes unproven items with accepted risks. Scale limits are scattered or missing: Actions concurrency, cold-build minutes, Renovate PR volume, the two-VM limit and the 14 GB disk. Fix: add an H2 table with columns Risk / Kind / Trigger or check / Mitigation / Decision. | structure M1 | 335-373 |
| K15 | **Some rejected alternatives give no trade-off.** These are the Ubuntu bump, Mac-first, the PC runner (only a quote), "every tool gating", host-native development, and "all three compilers everywhere". | structure M2, design N3 | 788-790, 817-823, 850, 890-898 |
| K16 | **"Forking mise" cites a maintainer stance without a link, and gives the wrong reason.** The real reason is rebase cost: mise releases about daily and `bootstrap.rs` is about 7,000 lines. Fix: link CONTRIBUTING.md. | structure M3, design N3 | 819-820 |
| K17 | **Four alternatives from the research are missing:** hosted macOS runners, the `vsavkov` p2996 image, conda clang through `conda:`, and Dependabot. | structure M4 | §1, §2, §7 |
| K18 | **The inputs and D-numbers are not links.** The level-1 files sit one directory down, and "(research)" is vague. | structure M5 | 34-36, 350 |
| K19 | **Content is repeated in several places:** the digest list, the D54 risk (4 places), the merge rule, the tier-1 list and the fence rule. Fix: keep one copy in the section that owns each topic and link to it from the others. | structure M6, style N11 | many |
| K20 | **Terms are used with more than one meaning:** "lock", "gate", hash versus tag, and the names of the Mac VMs. | style M3-M6 | many |
| K21 | **Overclaims and internal contradictions:** <br>- "Neither can break `main`" (CUJ 5). <br>- "The one exception" (there are two). <br>- "No Actions job holds a secret" and "holds no token" (GITHUB_TOKEN). <br>- "Merges through the merge queue", which implies owned roots don't. <br>- The Tart digest is described as both hashed and not hashed. <br>- "Runs cleanly" can't be measured. <br>- The G1 measure is hard to parse. | style M7-M13, design N5 | 122, 140, 305, 450-466, 482, 653-679 |
| K22 | **The status line and decision range are stale, and milestone names are used before they are defined.** | style M1-M2, structure N1-N2 | 4, 52, 259, 331 |

## 🟢 Nits (grouped)

- **Hashing details:**
  - Use `git hash-object --no-filters`, or take blob ids from the commit.
  - State how the hashes are combined, and the hash length.
  - Say how the devcontainer gets its computed tag.
- **Mac GCC:** the ASan cell should say "`detect_leaks=0`, pending M0 (e)".
- **G1 reproducibility:** the Mac is local only and depends on the cirruslabs base image. Record this as an accepted limit.
- **The `publish` Environment protects nothing** unless it is given a credential (ties to K2).
- **Settled questions:** move them out of "Open Questions".
- **Weak points:** they use terms before §1-§10 define them.
- **Goals:** only G1 has a measure.
- **Alternatives:**
  - grouped by review stage, not by design area;
  - "Rejected by author" repeated about 35 times;
  - line 903 is "deferred", not rejected.
- **Formatting:** mixed list markers; spelling mixes British and American English.
- **CUJ 1:** contradicts §1 and §2 on the Mac LLVM source, and misses the p2996-only fallback.
- **Agent sessions and cap:** defined inside a CUJ instead of §9. D41 agent tooling has no Technical Plan home.
- **Missing references:** the third owner-confirmed difference has no D-number; ccache PR #1523 has no repo link; the 66,000-line figure has no citation.
- **About 23 smaller wording items** from the style reviewer, for example "count" → "used as claims", "works out" → "computes", "Wake-up" → "Status", and pointing "the existing rulings" to its source.

## What held up (all three reviewers)

* The Linux-first critical path, the cut order and the M0 exit review.
* The capability lock as the automerge signal, with D56's residual risk stated.
* The build job with no token, kept separate from the hosted publish job.
* Toolchains kept out of images, and apt pins separated from tool pins.
* Nearly every claim tied to a D-number.

## Author (Elephant) notes for the owner

* **K1 and K2 both come from D54, combined with self-hosted runners and tags named by hash.** You accepted D54 on the premise "only GHCR write, no secret exposed". The critic shows two further consequences:
  - an agent's branch workflow can run on your PC and Mac;
  - it can pre-publish a compiler that `main` later trusts.
* **Moving agents to a fork, the option you rejected, would not fix K1.** Fork PR workflows can also target self-hosted runners.
* The runner-side fixes (K1 a or b) and the separate PR tag namespace with attestations (K2) work whether or not D54 stands.
* K3-K13 are concrete mechanism gaps. K14-K22 are document quality.
