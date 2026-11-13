# Stage 5 re-audit: Zoom Out after the D42-D47 fixes

* **Target:** `docs/designs/environment-standard.md` (916 lines, after the Stage 5 fixes)
* **Date:** 2026-11-13
* **Reviewers:** `egm-zoom-out` and `egm-inventive-catalyst`, in new fresh contexts, with the first report (`zoom_out_report.md`) as input
* **Zoom-out verdict:** changes requested. 1 Blocker, 6 Major, 10 Nit.
* **Catalyst verdict:** 9 Major, 6 Nit (advisory).
* **Re-audit cap:** reached. This was the one Stage 5 re-audit allowed. Further fixes are checked by Stages 6-9, not by another Stage 5 run.

## Status of the first report's items

| Status | Items |
|---|---|
| **Closed** | A1 (capability lock), A4, A8, A9, A11, A12, A14-A20, A22, A23 |
| **Partly closed** | A3 (one pins file feeds both layers), A5 (App key must be in Actions; digest write-back), A6 (builder runs PR code), A7 (M1 still mixes critical and non-critical work), A10 (new clone-and-run endpoint), A21 (`secret:set` is still a dotfiles task) |
| **Closed as written, but replaced by a new problem** | A2 (trust split by file name → R1), A13 (vcpkg cache → R7) |

## New findings, merged and deduplicated

| # | Severity | Finding | Raised by | Lines |
|---|---|---|---|---|
| R1 | 🔴 Blocker | **The pins files can run code, and unreviewed PR code still reaches self-hosted hardware.** `pins.toml` is a mise conf.d fragment, so it can add `[tasks]`, `[env]`, `[hooks]` or apt sources. `inputs.toml` holds configure and CMake arguments, and its tarball URLs are not checked. `mise.lock` holds download URLs. The trusted builder reads `inputs.toml` from open PR branches and builds them on the PC and the Mac, with no owner approval. The publish job then pushes the result to GHCR. Renovate pins-only PRs also reach the PC under path routing, which contradicts CUJ 4. | ZO B1, IC M2 | 352-378, 398-409, 534-544, 806-813 |
| R2 | 🟡 Major | **A pins PR tests the old compiler.** `ci.yml` runs in the image named in `digests.toml`, so a PR that changes apt or toolchain pins is gated on the old binary. The real compiler change arrives later in a separate digest PR, which is classed as a leaf and merges itself unseen. That digest PR is also a bot write-back, the pattern D43 removed. | IC M1, ZO M2 | 216-229, 411-424, 813, 832 |
| R3 | 🟡 Major | **A3 is back one layer down.** One `pins.toml` holds both the apt pins (base) and the tool pins (tools), so a leaf bump touches a base input. Also, an owner-gated LLVM minor bump still blocks every other base change once the old pin disappears. | ZO M1, IC M8 | 401-419, 568-572 |
| R4 | 🟡 Major | **There is a build cycle on day one.** The tools image bakes in p2996, but the p2996 builder runs in the tools image. Every daily p2996 bump would also rebuild the tools image and the golden VM. | ZO M3 | 416-429 |
| R5 | 🟡 Major | **The fence costs more than it protects before 2026-11-27.** The critical path is arm64, which runs on hosted runners, and the PC is x64. GitHub Environments can't require approval "only when owner paths change". The owner would approve each agent PR twice. The D43 reason for keeping self-hosted runners (p2996 build time) applies only to the builder. | ZO M4, IC M5 | 127-130, 517-544, 731-733, 831 |
| R6 | 🟡 Major | **The merge rule promises checks that don't run.** Leaf PRs merge themselves "when the fixtures pass", but the fixtures don't run on leaf PRs. Mac-only pins can merge themselves although the macOS gate runs only after merge. | ZO M5, IC M6, IC N4 | 223-226, 505-506, 568-572, 856 |
| R7 | 🟡 Major | **Credentials and identity.** `image.yml` acting as the App needs the App key in Actions. An App with only contents and pull_requests write can't push workflow files, so the agents can't write the M1 workflows. A vcpkg GHCR cache would put `packages: write` in PR jobs. The "OCI/NuGet" backend isn't backed by research (GitHub's NuGet feed isn't GHCR), and the only dependency, ut, is header-only. `triplets:gen` is a generator, which goes against D8. | IC M3, ZO M6 | 465-468, 549-553, 761-770, 820-821, 832 |
| R8 | 🟡 Major | **`linux:run` adds an unfenced way to run code on the PC.** It is a clone-and-run endpoint reachable over the private network. The Mac runner also has no network policy. | IC M4, ZO N10 | 436-440, 880-882 |
| R9 | 🟡 Major | **Golden image publishing.** Pushing a 30-50 GB Tart image to GHCR needs a write token on the Mac, or a hosted runner with more than its 14 GB of disk. Its only consumer is the Mac itself. | IC M7, ZO N5 | 427-430, 876 |
| R10 | 🟡 Major | **The cut order depends on itself, and M1 is misplaced.** Cut 5 (Mac runner) comes before cut 6 (Mac p2996), but Mac p2996 is built on the Mac runner. M1 is still about 45 files, including non-critical ones (agent tooling, triplets, cache), and its workflows use runners that M3 sets up. | ZO M7, IC M9 | 608-637, 792-843, 882 |
| R11 | 🟢 Nit | The toolchain tree hash includes the README and smoke test, so editing the README rebuilds Mac GCC. One p2996 recipe for every OS means a glibc change also rebuilds macOS. | IC N1 | 369-372 |
| R12 | 🟢 Nit | The declared host compiler, binutils, glibc and SDK values are neither updated nor checked against the builder's actual environment. | IC N2 | 360-363 |
| R13 | 🟢 Nit | A PR waiting on the builder is never woken up when the artifact appears. | IC N3 | 384-386 |
| R14 | 🟢 Nit | The encoder may have no working coverage tool: M0 (b) and M0 (c) are both unproven, with no fallback. clang-format's handling of `^^` and `[: :]` is unverified. | IC N5, N6 | 92-101, 482-483 |
| R15 | 🟢 Nit | Whether mise reads `[bootstrap.packages]` from conf.d, and whether Renovate's mise manager finds the file there, is untested. | ZO N2 | 398-399 |
| R16 | 🟢 Nit | Some files are marked both O and P, which path-based CODEOWNERS can't express. `toolchain:fetch` inside `docker build` needs `.git`. | ZO N3, N4 | 820, 889, 802 |
| R17 | 🟢 Nit | The GHCR cleanup workflow and the automated Q4 promotion are YAGNI. | ZO N6, N7 | 176, 777, 910 |
| R18 | 🟢 Nit | `caps:update` would need every environment orchestrated from one machine. It can merge the per-environment CI artifacts instead. | ZO N8 | 819 |
| R19 | 🟢 Nit | The Q1 scrub must also cover this design file (personal identifiers and internal tooling names). | ZO N9 | 167, 711, 782 |
| R20 | 🟢 Nit | Smaller fixes. Weak point 2 says Mac GCC is "last but one", which is wrong. The D46/D45 citation is swapped. `vm/inputs.toml` versus the D36 process. The task lists don't match. G5 still names dotfiles' `secret:set` while saying dotfiles is not a dependency. | ZO N1, N10, A21 | 110, 266, 366, 392, 875 |

## The common root, as both reviewers put it

The fixes split trust **by file path and by runner**. But trust actually depends
on two other things: **whether a file's content can run code**, and **which
token a job holds**. Both reviewers propose the same correction:

1. **Run unreviewed code only on hosted runners.** Every PR and `merge_group`
   job is hosted, which is free for a public repo.
   - Self-hosted runners run only the trusted builder, which builds from
     `main` (or from a PR the owner has approved).
   - This drops the path-conditional Environment.
   - The PC runner can leave Level 1.
2. **Use one hash-keyed builder for images and toolchains alike.**
   - The image tag is a hash of the image inputs. PR CI works the tag out and
     waits for the artifact.
   - `digests.toml`, the digest PRs and their write-back go away.
   - Toolchains are fetched per job, not baked into images.
   - The apt pins get their own file, which is the base layer's only pins
     input.
3. **Keep write credentials only in an Environment restricted to `main`.** PR
   workflows run with read-only permissions. The vcpkg binary cache is dropped
   from Level 1.
4. **Check pins content, not just paths.** A hosted check validates that each
   pins file contains only allowed sections and tool names, and only
   allowlisted URL hosts. All flags move into `build.sh`.

## What held up (both reviewers)

* The capability lock (A1 is closed).
* A build job with no token, followed by a hosted publish job that holds the token.
* Tags derived from the git tree hash, with no lock file.
* The Linux-first critical path, with a cut order and an M0 exit review.
* clang-format pinned once through `pipx:`.
* `perf:instructions` as the only perf task in Level 1.
* A canary that starts with glaze only.
