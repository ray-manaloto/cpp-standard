Status: resolved

# Goldfish Annotated Review Report

## Owner decisions (2026-11-13)

The owner walked through K1-K13 one at a time. The rest were applied as
proposed (K14-K22 and the nits), the contest stands (intro sentence only),
and the declined nits stay declined. Where an owner decision differs from a
proposed edit below, the decision wins. Each decision is a row in the
decisions log:

| Finding | Decision | Log |
|---|---|---|
| K1 | A job-start hook baked into each runner image. It checks repository, event, `refs/heads/main` and an allowlisted workflow ref, fails closed, and kills the worker on refusal (`always()` steps still run). Negative test in M0 (i). | D58 |
| K2 | Toolchains are packslip-signed GitHub Releases, installed by mise's `packslip:` backend pinned to `builder.yml@refs/heads/main`. Images are attested on GHCR. PR builds use the `pr-<n>-` namespace only. Immutable releases, a tag ruleset, a `.N` republish suffix, `toolchain:audit` and a GHCR mirror. The `publish` Environment is dropped. | D59 |
| D54 | Kept and re-recorded with its full consequences (release deletion, dispatch, and disabling workflows under Actions write). | D60 |
| K3 | The builder runs on `merge_group`; tool bumps are grouped; `artifact:check` has a 3-hour timeout. | D61 |
| K4 | `artifact:check` covers Linux only; Mac toolchains build after merge; Mac pins come in a separate PR. | D62 |
| K5 | `mac-probe.yml` is dispatched from `main` and requires the approved review's `commit_id` to equal the head SHA; ruleset settings are verified. | D63 |
| K6 | jouet `gate-guard` (advisory), the hk/CI gate-policy check (enforcing), and owned `gate-policy.toml`, `hk.pkl` and `.jouet/**`. | D64 |
| K7 | gha-outrunner: a libvirt VM per job on the PC and a Tart clone on the Mac. Fine-grained runner PAT on the hosts only. | D65 |
| K8 | `toolchain-env.lock.json`, exported with `mise bootstrap status --json` plus `mise ls --json`, replaces hand-written host versions. | D66 |
| K9 | M0 (h) with ordered fallbacks. | D67 |
| K10 | `tools.toml` folded into `mise.toml`; per-platform `mise.lock` slices; daily retention; two-VM slot sharing; about 150 GB. | D68 |
| K11 | `image/base.inputs.toml` pins file; mise pinned by `min_version`. | D69 |
| K12 | PC SSH and Docker only on the Mac host; tailnet ACL. | D70 |
| K13 | The agent App gets `actions: write`; the key sits behind the host `agent:token` broker. | D71 |
| Nit | The third owner-confirmed difference is recorded. | D57 |

**Target:** `docs/designs/environment-standard.md` (lines 1-901)
**Findings:** `docs/designs/level-1/critic_report.md` (Stage 7: `egm-design`, `egm-structural`, `egm-style`)

**Summary:** 22 findings plus a group of nits.
- 22 are PROPOSE FIX.
- 1 is CONTEST (Issue 23, a style nit).
- 2 need the owner's choice inside a fix: K1 ((a) or (b)) and K12.
- The nits not proposed for fixing are DECLINE.

## Prioritized Findings & AI Suggestions

### [Issue 1] K1 [`egm-design`] - Severity: Blocker
*   **Affected Scope:** [Lines 170-175, 63, 367-373, 633-657](../environment-standard.md#L170-L657) (G8, Glossary, weak point 9, §6)
*   **Discrepancy Description:** Any PR branch workflow can declare `runs-on: [self-hosted, …]` and run on the owner's PC and Mac before review. Nothing on the runner side enforces "PC and Mac run only reviewed `main` code".
*   **Rationale:** D54 lets same-repo PRs run their own workflow file. CODEOWNERS and the ruleset only control merges, and restricting runner groups to selected workflows is probably not available on the Free plan. Fork PRs could also target self-hosted runners.
*   ***AI Suggestion:*** PROPOSE FIX (the owner chooses (a) or (b))
*   ***Justification:*** Valid. I wrote G8 and §6 as though routing alone kept code away from the runners. A workflow file chooses its own runner, so the fence has to be enforced on the runner side.
*   ***Proposed Edit:***
    *   Location: §6, a new bullet "Runner-side enforcement"; the Glossary "fence" entry; a new weak point 10; M1a in §10 and Detailed Implementation.
    *   Change, option (a), which I recommend:
        - Both ephemeral runner images set `ACTIONS_RUNNER_HOOK_JOB_STARTED` to a script baked into the runner image, not read from the repository.
        - The script aborts the job unless all of these hold:
          - `GITHUB_EVENT_NAME` is `push`, `schedule` or `workflow_dispatch`;
          - `GITHUB_REF` is `refs/heads/main`;
          - `GITHUB_WORKFLOW_REF` is on the image's allowlist (`builder.yml`, `post-merge.yml`, `mac-gate.yml`, `mac-probe.yml`).
        - The Mac exceptions (D55, Mac PR toolchain builds) run through a `workflow_dispatch` on `main` with an explicit SHA (see K5), so they also pass the hook.
        - The allowlist changes only when the runner image is rebuilt by the owner.
    *   Change, option (b):
        - The self-hosted runners register only to a separate repository, `cpp-standard-runners`. Only the owner can push to it.
        - Its workflows check out cpp-standard at a `main` SHA they are given.
        - Agents have no access to that repository.
    *   Both options add:
        - an M1a negative test: an App PR that adds a `runs-on: self-hosted` job must not run;
        - weak point 10: "The fence depends on the runner hook (or the separate repository) being intact."
        - This text replaces "Routing is by …" in the fence glossary entry.

### [Issue 2] K2 [`egm-design`] - Severity: Blocker
*   **Affected Scope:** [Lines 467-495, 367-373, 642-646](../environment-standard.md#L467-L495) (§2 steps 2-5, weak point 9, §6 diagram)
*   **Discrepancy Description:** PR builds and `main` builds publish into the same tag namespace, and the first writer wins. Future hashes can be predicted. A branch workflow can pre-publish a poisoned artifact under a tag that `main` will later use without rebuilding.
*   **Rationale:** The tag covers only the input files. "Never overwrite" is enforced only by our own publish task (D54). The sha256 annotation is written by the same publisher, so it proves nothing.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. I presented D54 as "GHCR write only, no secret exposed". I missed that a pre-published tag becomes a compiler that `main` trusts, so the owner never saw this consequence.
*   ***Proposed Edit:***
    *   Location: §2 steps 2, 4 and 5; weak point 9; the §6 diagram; Detailed Implementation rows for `artifact:publish`, `toolchain:fetch` and `builder.yml`.
    *   Change:
        1. **Separate namespaces.**
           - PR builds publish as `pr-<n>-<name>-<os>-<arch>-<hash>`.
           - Only builder runs on `refs/heads/main` publish the tags `main` uses (`<name>-<os>-<arch>-<hash>`).
        2. **Attestation, not tag existence.**
           - The `main` builder decides a tag is "done" only if that tag carries a GitHub artifact attestation signed by `builder.yml` at `refs/heads/main`. Otherwise it rebuilds and replaces the tag.
           - The publish job generates the attestation with `actions/attest-build-provenance` (`id-token: write`, `attestations: write`).
        3. **Verification on every pull.**
           - `toolchain:fetch` and every image pull outside PR jobs (the PC, the Mac, the dev VM, post-merge jobs and the devcontainer) run `gh attestation verify --signer-workflow ray-manaloto/cpp-standard/.github/workflows/builder.yml --source-ref refs/heads/main`.
           - They refuse the artifact if the check fails.
           - PR jobs pull their own `pr-<n>-…` tags.
        4. **Re-record D54** with its full consequence: a branch workflow can push any tag, but nothing outside PR jobs uses an artifact without a `main` attestation.
        - Drop the `publish` Environment, which protects nothing (nit G3).
        - Remove the misleading "only `main` and builder runs" wording.

### [Issue 3] K3 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 256-261, 300-305, 473-495](../environment-standard.md#L473-L495) (§2, CUJ 5)
*   **Discrepancy Description:** When two PRs that change inputs are in the merge queue together, the merged commit has a hash that nothing has built, so the queue stalls.
*   **Rationale:** The builder doesn't run on `merge_group`, and it posts statuses only to PR heads.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. With daily Renovate PRs this will happen routinely.
*   ***Proposed Edit:***
    *   Location: §2 step 3 and step 5, §7, `builder.yml` row.
    *   Change:
        - The builder also runs on `merge_group`. It builds merge-group tags on hosted runners, under the PR namespace, and posts status to the merge-group SHA.
        - Renovate groups every `tools.toml`/`mise.lock` change into one daily PR (`groupName: tools`).
        - `artifact:check` fails after 3 hours with the message "artifact `<tag>` not built; see builder run `<url>`".

### [Issue 4] K4 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 294-297, 480-481, 495, 702-710](../environment-standard.md#L702-L710) (CUJ 4, §2, §7)
*   **Discrepancy Description:** D56 automerge for p2996 and GCC contradicts the Mac gating. The p2996 commit is also in `macos.inputs.toml`, so every p2996 PR waits for the owner anyway.
*   **Rationale:** Mac hashes build only after owner approval, and `artifact:check` needs every tag.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. This is an internal contradiction I introduced.
*   ***Proposed Edit:***
    *   Location: §2 step 3, §2 step 5, CUJ 4, §7.
    *   Change:
        - `artifact:check` covers Linux tags only.
        - Mac toolchains are built only after merge, by the `main` builder on the Mac.
        - Renovate bumps `macos.inputs.toml` in its own PR, labelled Mac-only, which waits for the owner until Q4.
        - `linux.inputs.toml` bumps follow D56.
        - The D55 PR-time Mac probe job stays, because it runs only when the capability lock changes.

### [Issue 5] K5 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 432-437, 480-481, 654-655, 685-687](../environment-standard.md#L432-L437) (§1 D55, §2, §6)
*   **Discrepancy Description:** Owner approval applies to a PR, not to a specific commit. Commits pushed after approval would run on the Mac, and the trigger for the Mac job is undefined.
*   **Rationale:** A `pull_request_review` event would run the branch's own workflow file.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: §1 macOS entries paragraph; §6 owned roots and ruleset bullet; `rulesets/main.json` row.
    *   Change:
        - The Mac probe job runs only through `mac-probe.yml`, a `workflow_dispatch` workflow on `main`, which the owner starts with the PR number. It is allowed by the K1 hook.
        - The job reads the PR's latest approving review through the API. It refuses to run unless that review's `commit_id` equals the PR head SHA. It then checks out exactly that SHA.
        - The ruleset requires "dismiss stale approvals" and "require approval of the most recent reviewable push".
        - `repo:rulesets --verify` also checks:
          - those two settings;
          - that the merge queue is required;
          - the required checks: `ci`, `pins:validate`, `artifact:check`.

### [Issue 6] K6 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 593-596, 607-624, 677-679](../environment-standard.md#L593-L679) (§5, §6)
*   **Discrepancy Description:** Agents can weaken the gate's own guards without review. Presets, probes and coverage-exclusion markers merge without the owner, the capability lock doesn't notice, and the fixtures don't run on those PRs.
*   **Rationale:** The capability lock records what a compiler can do, not what the presets turn on.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. "Checked in review" named no reviewer.
*   ***Proposed Edit:***
    *   Location: §5 step 4; §5 "fixtures run" list; §6 owned roots.
    *   Change:
        - Add `CMakePresets.json`, `cmake/presets/**` and `cmake/probes.cmake` to the owned roots.
        - Add a tier-1 check, `coverage:exclusions`: every exclusion marker must match an entry (file and hash of the line) in `coverage-exclusions.toml`, which is owned. So a new exclusion forces an owned-file change.
        - Rewrite §5 step 4: "Exclusions are reviewed by the owner through `coverage-exclusions.toml`."

### [Issue 7] K7 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 476-479, 639, 653-657](../environment-standard.md#L653-L657) (§2, §6)
*   **Discrepancy Description:** The PC runner as described can't run its jobs. It is unprivileged with no Docker socket, but it is expected to run container jobs and builds.
*   **Rationale:** `container:` jobs and `docker build` both need a container runtime.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: §6 PC runner bullet; `pc-runner.md` row.
    *   Change:
        - The PC runner image is built `FROM` the current `main` tools tag, plus the runner agent, and is verified by attestation (K2).
        - PC jobs run directly in that image without `container:`. That covers Linux toolchain builds and heavy post-merge jobs.
        - The PC never builds images. Images build on hosted runners (D49).
        - Each job runs in a fresh container of that image, started by a small supervisor on the PC that holds the registration token.

### [Issue 8] K8 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 449, 454-466](../environment-standard.md#L454-L466) (§2 step 1)
*   **Discrepancy Description:** Nothing updates `inputs.toml` when the base image changes the builder's environment, so the next `main` toolchain build breaks.
*   **Rationale:** Toolchain hashes leave out the base tag, but the builder fails if its host values don't match `inputs.toml`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: §2 step 1 "The builder checks the declared environment".
    *   Change:
        - Linux toolchains build inside the current base tag.
        - A required check on every PR that changes the base, `toolchain:declare --check`, reads the new base's host compiler, binutils and glibc. It fails if `linux.inputs.toml` differs.
        - Renovate's `postUpgradeTasks` runs `toolchain:declare --write` so the same PR updates `inputs.toml`. That also changes the toolchain hash, so the rebuild is intended.

### [Issue 9] K9 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 476-477, 753](../environment-standard.md#L753) (§2, §10 M0)
*   **Discrepancy Description:** The hosted p2996 build is on the critical path but unproven against about 14 GB of free disk, and the arm64 timing is unverified.
*   **Rationale:** `research/p2996-linux.md` gives 61-76 minutes without compiler-rt, and marks the arm64 figure UNVERIFIED.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: §10 M0 list.
    *   Change: add **M0 (h)**: a cold p2996 build with compiler-rt on `ubuntu-26.04-arm`, recording peak disk and wall time.
        - Fallbacks, in order:
          1. build under `/mnt` after freeing preinstalled toolsets;
          2. build only the needed runtimes;
          3. build arm64 p2996 only from `main`, on the PC (amd64) or a larger hosted runner.
        - It goes on the critical-path list.

### [Issue 10] K10 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 450, 539-547](../environment-standard.md#L539-L547) (§2 table, §3 macOS VM)
*   **Discrepancy Description:** The golden VM would rebuild daily, fill the disk, and collide with Apple's limit of two VMs.
*   **Rationale:** Its hash covers all of `tools.toml` and `mise.lock`, each image is 35-50 GB, and nothing deletes old ones.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: §2 table golden-VM row; §3 macOS VM list.
    *   Change:
        - The hash covers `vm/inputs.toml` and the `macos-arm64` entries of `mise.lock` only.
        - The two newest golden images are kept and older ones are deleted.
        - It is built in the runner slot, one job at a time with runner jobs.
        - Disk budget: about 150 GB, which is 2 golden images plus 1 dev VM.

### [Issue 11] K11 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 449, 530-533, 673-674](../environment-standard.md#L530-L533) (§2, §3, §6)
*   **Discrepancy Description:** The Ubuntu digest and the mise version sit in an owned root, so every bump needs a daily owner review.
*   **Rationale:** `image/base.Dockerfile` is an owned root.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. It contradicts D50 and G1.
*   ***Proposed Edit:***
    *   Location: §2 table base row; §3 Linux images; §6 owned roots; the pins schema.
    *   Change:
        - New pins file `image/base.inputs.toml` holds the Ubuntu image and digest, and the mise version and sha256.
        - `pins:validate` covers it, and it is passed as build args.
        - The base hash covers it.

### [Issue 12] K12 [`egm-design`] - Severity: Major (the owner chooses within the fix)
*   **Affected Scope:** [Lines 63, 174-175, 214, 549-553](../environment-standard.md#L549-L553) (Glossary, G8, settled table, §3)
*   **Discrepancy Description:** The agent VM can reach Docker on the PC, which contradicts the fence. `DOCKER_HOST=ssh://<linux-host>` gives root on the PC.
*   **Rationale:** Agents run in the dev VM (D17). If the PC's SSH credentials are in that VM, agents can reach them.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. D29 was chosen before D48. The owner's own devcontainer use and agent isolation conflict when both share one VM.
*   ***Proposed Edit:***
    *   Location: Glossary "fence"; settled table "Agents in the VM"; §3 "Linux runs from inside the VM".
    *   Change:
        - PC SSH and Docker credentials exist only on the Mac host, never in the dev VM.
        - The owner opens the PC devcontainer from the host terminal.
        - Agents reach Linux only through hosted runs (`linux:run`).
        - Remove "or the PC devcontainer" from the settled table.
        - The fence wording becomes: "Self-hosted runners run only reviewed `main` code. Agent code runs only in the dev VM and on hosted runners."

### [Issue 13] K13 [`egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 82, 549-551, 659-661](../environment-standard.md#L549-L551) (Glossary identities, §3, §6)
*   **Discrepancy Description:** `linux:run` needs Actions write to dispatch a workflow, which the App doesn't have. Agents that hold the App key could leak a credential that never expires.
*   **Rationale:** Dispatching a workflow needs the `actions: write` permission. The private key is long-lived.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: §3 "Linux runs from inside the VM"; §6 identities; G5; Glossary "Agent App".
    *   Change:
        - `linux:run` pushes the branch and opens or updates a draft PR. `pull_request` then runs `ci.yml` on hosted runners, and no Actions permission is needed.
        - The App key stays on the Mac host. A small broker task on the host (`agent:token`, run by the host, not the VM) mints one-hour tokens and hands only those into the VM.
        - The VM never sees the key.

### [Issue 14] K14 [`egm-structural`] - Severity: Major
*   **Affected Scope:** [Lines 335-373](../environment-standard.md#L335-L373) (Weak points)
*   **Discrepancy Description:** There is no Risks & Mitigations section, and the weak points mix unproven items with accepted risks.
*   **Rationale:** The feature-spec standard requires failure modes, security, scale limits and mitigations.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: replace "Weak points first" with a one-line pointer; add an H2 "Risks & Mitigations" after Alternatives Considered.
    *   Change:
        - The section is a table with the columns Risk | Kind | Trigger or check | Mitigation or fallback | Decision.
        - It holds weak points 1-9, K1 and K2's residual risks, and these scale rows:
          - hosted concurrency of about 20 jobs;
          - cold p2996 builds of 61-76 minutes or more per architecture;
          - Renovate PR volume;
          - the Apple limit of two VMs;
          - about 14 GB of hosted disk;
          - the Mac disk budget;
          - D56's codegen risk.

### [Issue 15] K15 [`egm-structural`, `egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 788-790, 817-823, 850, 890-898](../environment-standard.md#L788-L898) (Alternatives)
*   **Discrepancy Description:** Some rejected alternatives give no trade-off.
*   **Rationale:** The Alternatives Rule requires one.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. The reasons exist in D3, D17, D19, D36, D44 and D48.
*   ***Proposed Edit:***
    *   Location: each listed entry.
    *   Change: add one sentence each:
        - **all three compilers everywhere:** plain clang 23 can't compile P2996 (D3);
        - **host-native development:** collisions and dotfiles coupling (The Problem);
        - **every tool gating CI:** modules and reflection break most tier-2 tools (`research/tooling-build-analysis.md`), and four checks leave tidy, Valgrind, UBSan and hardening unguarded;
        - **in-place Ubuntu bump:** a red bump blocks every image update, and a manual bump is forgotten;
        - **Mac-first:** it puts the two least-proven items on the path to 2026-11-27;
        - **dropping the PC runner:** native amd64 toolchain builds and heavy post-merge jobs without hosted disk and time limits.

### [Issue 16] K16 [`egm-structural`, `egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 819-820](../environment-standard.md#L819-L820) (Forking mise)
*   **Discrepancy Description:** The entry cites a maintainer stance without a link, and gives the wrong reason.
*   **Rationale:** The standard forbids citing a maintainer without a link. The real reason against a fork is rebase cost.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: the "Forking mise" entry.
    *   Change: "Rejected by author: mise releases about daily and `bootstrap.rs` changes often (`research/mise-upstream-asks.md` §4), so a fork means rebasing and releasing binaries for each architecture. The `--skip tools` + `install --system` workaround already works. Requests go to Discussions; mise doesn't accept outside PRs ([CONTRIBUTING.md](https://github.com/jdx/mise/blob/main/CONTRIBUTING.md))."

### [Issue 17] K17 [`egm-structural`] - Severity: Major
*   **Affected Scope:** Alternatives (§1, §2, §7 choices)
*   **Discrepancy Description:** Four alternatives from the research are missing.
*   **Rationale:** They appear in `research/tart-macos.md` §4, `research/p2996-linux.md`, `research/external-image-examples.md` §3 and `research/mise-images.md` §5.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: Alternatives, the "From drafting" group.
    *   Change: add an entry for each, with its trade-off:
        - **Hosted macOS runners for the macOS gate:** free for a public repo, but the OS and SDK aren't controlled and the toolchain inputs need the pinned Tart base.
        - **The `vsavkov/clang-p2996` image:** third-party, Ubuntu 24.04, stale.
        - **conda-forge clang through mise `conda:`:** pinned and checksummed, but D12 chose apt, and conda GCC on macOS miscompiles.
        - **Dependabot:** it has no mise support.

### [Issue 18] K18 [`egm-structural`] - Severity: Major
*   **Affected Scope:** [Lines 34-36, 350](../environment-standard.md#L34-L36)
*   **Discrepancy Description:** The inputs and the D-numbers aren't links, and the research citation at line 350 is vague.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Location: the Overview inputs line; weak point 3.
    *   Change:
        - Use relative links: `level-1/concepts_brief.md`, `level-1/decisions-log.md`, `level-1/research/` and the report files.
        - Add a sentence: "Dnn means row Dnn in the decisions log."
        - Change "(research)" to `(level-1/research/tooling-perf-docs.md)`.

### [Issue 19] K19 [`egm-structural`, `egm-style`] - Severity: Major
*   **Affected Scope:** CUJ 6 / §9, the D54 mentions (4), the merge rule (3), tier-1 and fixture lists (G3 / §5), and the fence rule.
*   **Discrepancy Description:** The same content is repeated in several places.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid. The repeats have already drifted.
*   ***Proposed Edit:***
    *   Change: keep one normative copy and link to it from the other places:
        - the digest list in §9;
        - D54 in Risks;
        - the merge rule in §7;
        - the tier-1 list and fixtures in §5;
        - the fence in §6.
    *   CUJs and Goals state the outcome and link the section.

### [Issue 20] K20 [`egm-style`] - Severity: Major
*   **Affected Scope:** throughout
*   **Discrepancy Description:** Several terms have more than one meaning: "lock", "gate", hash versus tag, and the names of the Mac VMs.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Change:
        - Use "capability lock" and `mise.lock`, never a bare "lock".
        - "Gate" means `mise run ci` only. The macOS run is called "the post-merge macOS run".
        - G2 wording: "runs the tier-1 sanitizer checks"; "is the second compiler that must pass the gate".
        - "Inputs hash" means the value. "Tag" means the full name.
        - "Golden image" is the local Tart VM named by hash. The "dev VM" is a clone of it.
    *   Add the gate, golden image and dev VM terms to the Glossary.

### [Issue 21] K21 [`egm-style`, `egm-design`] - Severity: Major
*   **Affected Scope:** [Lines 122, 140, 305, 450-466, 482, 653-679](../environment-standard.md#L122-L679)
*   **Discrepancy Description:** Several statements overclaim or contradict each other.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Change:
        - **CUJ 5:** "Neither merges unless the required (Linux) checks pass on top of `main` and the other agent's change."
        - **§6:** "There are two exceptions, both started by the owner from `main`."
        - **Secrets:** "No Actions job holds a repository or Environment secret; `GITHUB_TOKEN` is the only credential."
        - **"Merges through the merge queue":** becomes "merges without owner review".
        - **Tart digest:** "Toolchain builds record the Tart digest; the golden image's hash includes it."
        - **Tier-2 promotion:** a tool moves up "when it reports zero findings on the reference project and the owner approves".
        - **G1 measure:** "The tags computed from a commit's inputs always resolve to the same toolchain versions."

### [Issue 22] K22 [`egm-style`, `egm-structural`] - Severity: Major
*   **Affected Scope:** [Lines 4, 52, 259, 331](../environment-standard.md#L4)
*   **Discrepancy Description:** The status line and the decision range are stale, and milestones are used before they are defined.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Valid.
*   ***Proposed Edit:***
    *   Change:
        - Status: "Draft, in EGM review (Stage 7 fixes applied)".
        - "D26 to D57".
        - Add a Glossary row "Milestones": M0 spike, M1a critical path, M1b cuttable, M2 amd64 and PC runner, M3 Mac, M4 canary, M5 digest and perf.
        - Remove the duplicate M0 definition in §10.

### [Issue 23] Style nit: "Rejected by author" → "owner" [`egm-style`] - Severity: Nit
*   **Affected Scope:** Alternatives, lines 786-903
*   **Discrepancy Description:** The phrase is repeated about 35 times, and the reviewer suggests "owner".
*   ***AI Suggestion:*** CONTEST
*   ***Justification:*** The EGM draft rule requires this exact phrasing: "Document author decisions as `Rejected by author: [technical rationale]`" (`egm-draft/SKILL.md`, Step 4.3). In this design the author is the owner (header line 3). I'll add one intro sentence, "All entries were rejected by the author (the owner) unless marked otherwise", but keep the phrase.
*   ***Proposed Edit:*** none, apart from the intro sentence.

### [Issue 24] Nits proposed for fixing [`egm-design`, `egm-structural`, `egm-style`] - Severity: Nit
*   ***AI Suggestion:*** PROPOSE FIX (each takes one line or less)
*   ***Proposed Edit:***
    *   Hashing:
        - Use `git rev-parse <sha>:<path>` blob ids (no filters).
        - Combine them as the sha256 of the "path\0blob\n" lines, sorted, truncated to 16 hex characters.
        - The devcontainer gets its tag from `initializeCommand: mise run image:tag --env-file`.
    *   Compiler table: the Mac GCC ASan cell reads "yes, `detect_leaks=0`, after M0 (e)".
    *   G1: add an accepted limit. The Mac golden image is local, and depends on the cirruslabs vanilla digest staying available.
    *   Move the settled-questions table into an H3 "Settled questions" at the end of the Technical Plan.
    *   Add "Measure:" lines to G2-G8.
    *   Add a § reference to each Alternatives entry. Move "required macOS gate" from Alternatives to Open Questions (Q4).
    *   CUJ 1: Mac LLVM comes through `mise.lock` (baked into the golden image), and GCC and p2996 are fetched. Note the p2996-only fallback.
    *   Move the cap and agent-session definitions into §9, and add a §9 bullet for the D41 agent tooling.
    *   Add a D-number for the third owner-confirmed difference (D57). Link ccache PR #1523. Cite the 66,000-line figure.
    *   Style wording:
        - "count" → "used as claims" / "where results are valid";
        - "works out" → "computes";
        - "Wake-up" → "Status";
        - "the existing rulings" → link to its source;
        - "allowlist" spelled one way, named "canary allowlist" and "pins allowlist";
        - "Each has a check, a fallback, or an accepted risk";
        - weak point 9 gets "an agent acting on bad instructions";
        - "macOS allows at most two macOS guest VMs per host";
        - one clause on what CMake bug #28242 does;
        - "read-only permissions except `security-events: write`";
        - "one must-fail fixture for each tier-1 check listed in §5";
        - G1 notes that Action SHAs are weekly;
        - the "Each either … or …" Alternatives entry becomes one bullet per option;
        - add "In an earlier draft" where the past tense refers to drafts the reader never saw.

### [Issue 25] Nits declined [`egm-style`, `egm-structural`] - Severity: Nit
*   ***AI Suggestion:*** DECLINE
*   ***Justification:*** Each is cosmetic, or its cost outweighs the gain.
    *   **British/American spelling mix:** recorded. It will be normalised to American in one pass at finalisation.
    *   **Mixed list markers:** recorded. Normalised at finalisation.
    *   **Regrouping Alternatives by design area:** the per-entry § references in Issue 24 give the same navigation.
