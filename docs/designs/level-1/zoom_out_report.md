# Stage 5: Initial Zoom Out report

* **Target:** `docs/designs/environment-standard.md` (795 lines; FeatureRange 1-629, DetailedRange 630-795)
* **Date:** 2026-11-13
* **Reviewers:** `egm-zoom-out` (zoom-out-standard) and `egm-inventive-catalyst`, run in parallel in fresh contexts
* **GoldfishContext:** `level-1/decisions-log.md` and the reports in `level-1/research/`
* **Zoom-out verdict:** changes requested. 1 Blocker, 6 Major, 9 Nit.
* **Catalyst verdict:** 9 Major (two "close to Blocker"), 2 Nit. This persona can only give advisory ratings.

Line numbers refer to the design before any Stage 5 fix.

## Merged action list (deduplicated)

| # | Severity | Finding | Raised by | Design lines |
|---|---|---|---|---|
| A1 | 🔴 Blocker | **The must-fail fixtures can't catch a probe that turns a check off.** The fixtures skip on probe results (line 704), so when a probe goes off its fixture is skipped too. Nothing compares the probes against the §1 table, and leaf bumps (cmake, vcpkg) never run the fixtures. D39's accepted risk rests on a guard that doesn't work. | ZO B1, IC 1 | 259-262, 328-330, 465, 704, 747 |
| A2 | 🟡 Major | **Leaf automerge and the CODEOWNERS fence claim the same files.** CODEOWNERS owns all of `mise.toml`, `.github/**` and `image/**`. So mise tool bumps, Action SHA bumps and image-digest PRs all need the owner, which is "review everything" in practice. | IC 2 | 486-488, 498-505, 709, 711-712 |
| A3 | 🟡 Major | **Expiring apt.llvm.org pins plus owner-only compiler bumps.** Every image rebuild re-resolves apt. Once an LLVM pin expires while its PR waits for the owner, unrelated leaf PRs go red, so owner latency blocks automerge. | ZO M2, IC 3 | 77-79, 213-220, 375-393, 496-505 |
| A4 | 🟡 Major | **Runner routing contradicts the toolchain build path.** Routing is by actor and Renovate goes to hosted runners. An owner's approval doesn't change the actor, so a macOS toolchain bump can never reach the Mac runner. Who triggers `merge_group` decides routing by accident, and the D32 cron depends on who last edited it. | ZO M3, IC 5 | 355-366, 476-493, 708-710 |
| A5 | 🟡 Major | **Credentials and write-back.** No identity is named for CI writers (image-digest PRs, lock updates). PRs opened with GITHUB_TOKEN don't trigger checks. Self-hosted runners would need `packages: write`, which contradicts "no secrets". `toolchains/lock.toml` can drift out of step with `inputs.toml`, and the hash already makes it redundant. | ZO M3, ZO M4, IC 6 | 300-303, 339-366, 681-683, 689, 709 |
| A6 | 🟡 Major | **The actor fence is checked at merge time, but code runs at PR time.** An agent-App PR that changes `.mise/tasks/ci` or a workflow runs on the PC or Mac before the owner sees it. The PC is on the owner's private network and also runs a privileged perf container. | IC 7 | 476-489, 708, 711-712, 776 |
| A7 | 🟡 Major | **No critical path or cut order against the 2026-11-27 date.** M1 is about 45 files. Nothing says which items unblock glaze FIX, and there is no re-scope step after M0. | ZO M1 | 70-126, 535-544, 666-781 |
| A8 | 🟡 Major | **Mac CI has a single slot, and Mac GCC costs the most.** The single Mac runner carries the gate, three-stage GCC bootstraps, p2996 builds and cold VM bootstraps. A Tart or SDK change rebuilds both macOS toolchains. Mac GCC adds little over Linux GCC (no TSan/LSan, ASan hangs with `detect_leaks=1`). | ZO M6, IC 8 | 253-258, 339-366, 395-402, 686-688, 749-759 |
| A9 | 🟡 Major | **Lint tools differ between environments.** clang-format and clang-tidy come from the 23.1.5 tarball on the Mac but the 23.1.6 apt snapshot on Linux, so a tier-1 check can pass in the VM and fail in CI. | IC 4 | 89-90, 201-202, 310-314, 700, 727-730 |
| A10 | 🟡 Major | **Source doesn't reach the PC's Docker.** With `DOCKER_HOST=ssh://<linux-host>`, bind mounts resolve on the PC, so containers run from the VM can't see the VM's worktree. | IC 9 | 251-252, 292, 404-406, 690, 756 |
| A11 | 🟡 Major | **Perf tooling is in Level 1 although Level 1 numbers don't count.** It adds four perf tasks, a privileged container and an M0 PMU check, with no workload to measure yet. | ZO M5 | 148-149, 510-518, 540, 773-776 |
| A12 | 🟢 Nit | "100% line coverage" is undefined for consteval and reflection code (blind-spot #4). | IC 10 | 90-93, 441-442 |
| A13 | 🟢 Nit | The vcpkg triplets leave out the sanitizer axis that D6 requires, and no binary cache is named. | IC 11 | 430-431, 699 |
| A14 | 🟢 Nit | Stale "provisional" labels, and a G1 measure ("rebuild gives same versions") that D27 replaced with digest reproduction. | ZO N1 | 77-79, 98-99 |
| A15 | 🟢 Nit | The Mac GCC hash inputs leave out zstd and zlib, which D33 lists. | ZO N2 | 341-344, 686 |
| A16 | 🟢 Nit | `toolchain:fetch` is used but never defined. | ZO N3 | 689, 754 |
| A17 | 🟢 Nit | Reflection targets are switched off twice: by a cache variable and by a probe. | ZO N4 | 416, 696-697 |
| A18 | 🟢 Nit | The digest runs in Actions but reports `review:cap`, which runs only on the VM. | ZO N5 | 227, 531, 778-779 |
| A19 | 🟢 Nit | `toolchain/hash` could be `git rev-parse HEAD:toolchains/<name>`, which needs no new code. | ZO N6 | 348-350, 682 |
| A20 | 🟢 Nit | `usage` and `pitchfork` are listed with no use. | ZO N7 | 717-722 |
| A21 | 🟢 Nit | App creation is a one-off, so a runbook would do. `secret:set` is a host task, which goes against G5 and D18. | ZO N8 | 643-652, 790-791 |
| A22 | 🟢 Nit | Start the canary with glaze only. Make D36 a written process with no machinery in Level 1. | ZO N9 | 465-470, 506-508 |
| A23 | 🟢 Nit | The Q1-Q8 numbering differs from decisions-log's "Technical Plan Q6-Q14". | ZO note | 155-163 |

## Proposed transforms (from the reviewers)

* **A1 (two options).**
  - **Zoom-out:** treat `cmake/presets/matrix.json` as the expected table. Make it a tier-1 failure when a visible preset asks for a check whose probe is off. Fixtures follow the matrix, not the probes.
  - **Catalyst:** commit the probe output as `cmake/capabilities.lock.json`, with `mise run ci` comparing fresh probes against it. A legitimate change is accepted by running `caps:update` in the same PR. The lock is generated, so the reason D39 rejected a hand-kept table no longer applies. This also answers Q11.
* **A2.** Split files by trust boundary. Owner-owned: `.mise/tasks/**`, `cmake/**`, `fixtures/**` and the build scripts. Unowned: the pins files and a single `image/digest` file that workflows read through a setup job. Action SHA bumps stay owner-reviewed, batched weekly.
* **A3 (two options).**
  - **Zoom-out:** an LLVM snapshot rotation within the same major.minor is a leaf bump (with fixtures). major.minor bumps need the owner.
  - **Catalyst:** mirror the pinned LLVM `.deb` files to GHCR by inputs hash (the §2 pattern), or split the image into a compiler base layer and a tools layer, so leaf bumps never re-resolve apt.
* **A4 / A5.**
  - Separate building from checking. One trusted builder workflow on `main` builds every missing artifact on the right runner. PR jobs only require that the artifact for `hash(inputs)` exists.
  - Self-hosted runners upload only a workflow artifact. A hosted job with `packages: write` publishes it.
  - Drop `lock.toml` and derive the tag from the hash. If it is kept, add a tier-1 check that `hash == lock.hash`.
  - The agent App is the writer identity.
* **A6.** Make the runner sandbox the boundary: ephemeral, egress only, no tailnet, never privileged. PRs that touch owner paths need a GitHub Environment approval before any self-hosted job runs.
* **A7.** Add "Critical path to glaze FIX": the Linux arm64 image, GCC 16 and p2996 on Linux, the encoder, tier-1 CI for those presets, and the merge queue. Everything else goes in a cut order, cut first to last: perf, canary, Mac GCC, Mac p2996, Mac runner, amd64. Add an M0 exit review with pre-agreed cuts.
* **A8.**
  - Put Mac GCC last in the cut order.
  - A bootstrapped "runner golden" Tart image keyed by hash.
  - The macOS gate is not a required merge-queue check (it runs after merge or daily).
  - Split hash inputs into build inputs and environment constraints.
* **A9.** Pin clang-format through one platform-independent mise tool. Run tidy only in the Linux clang image.
* **A10.** Use git as the transport: push the branch, and the PC container clones at that SHA into a volume.
* **A11.** Keep the D35 table as the standard. Defer the `perf:*` tasks, the privileged container and the PMU check to Level 2, except perhaps `perf:instructions` (callgrind).

## What held up (both reviewers)

* Rejecting `mise oci build` in favour of a Dockerfile of about ten lines that only calls mise (reproduced on 26.04 and 26.10).
* `--skip tools` followed by `install --system --locked`, with mise.lock at mode 644 (tested).
* An inputs-hash GHCR cache for p2996 (the pattern is reused, not invented).
* Hand-written layered presets (D8), and clang-tidy only on plain-clang targets.
* Not forking mise, and keeping the upstream asks as drafts.
* The two-tier gate, the report-only canary and side-by-side base flips (D36).

## Author (Elephant) notes for the owner

* **A1 is the same weak point I flagged when D39 was decided.** Both reviewers found independently that the guard doesn't work as written. The catalyst's lock-file option keeps "probe and adapt" for optional features but makes a lost capability visible and owner-reviewed. It doesn't reverse D39.
* **A2, A4, A5 and A6 are one cluster: the fence and the automation as written don't fit together.** They are best fixed together, as one change to §2, §6 and §7.
* **A7 and A8 are scope questions that touch D21 and D26.** Those are your calls; the reviewers suggest sequencing, not reversal.
