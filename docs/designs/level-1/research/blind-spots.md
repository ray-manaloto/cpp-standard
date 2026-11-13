# Blind spots in the Level-1 plan (2026-11-13)

Skeptical review of the owner's brainstorm input, decisions-log (D1-D13) and the research reports. Ranked, weakest first.
"Input" means the owner's brainstorm input and session notes, which are private and not published here. Paths are relative to docs/designs/level-1/. "Unverified" = not checked first-hand.

## 1. The gate is the opposite of the stated root problem (churn, side issues)
- Issue: the root problem is lost time to side issues. D11 ("every tool, every piece of setup, now") plus D12 (daily image rebuild, exact apt pins) plus D10/D13 (custom image pipeline) plus D7 (vcpkg day 1) plus D9 (sccache) turns Level 1 into a multi-week infra project before any glaze FIX line.
- Evidence: decisions-log.md D7, D9-D13; the input flags process weight as a cause; research/tooling-build-analysis.md rates most of D11's tools "later"/"skip" (cppcheck, ClangBuildAnalyzer, Esri LWYU "skip for now", FuzzTest "skip day 1", AFL++ "later") because modules/reflection break them.
- Ask: which 3 tools are truly gate-blocking, and will you accept Level 1 = build+ut+coverage+sanitizers+format only, with the rest as dated Level-1.5 tickets?

## 2. No time budget or weekly "progress" definition (input gap 21 never answered)
- Issue: Level 1 has a done-condition but no deadline, no cap on hours/week, no kill criterion. Without one, "just one more tool" wins again. Also nothing says glaze FIX starts by date X.
- Evidence: the input's "Level 1 is done when..."; input item 21 is still open in decisions-log "Open".
- Ask: what is the calendar date by which glaze FIX Orchestra code must start, and what do you cut if Level 1 is not done by then?

## 3. Learning goal (C++26 reflection for performance) has no place in the plan
- Issue: nothing in Level 1 produces reflection skill. By D3, reflection projects build only on GCC16 + clang-p2996, both "experimental" with ~41 open GCC reflection bugs and module bugs. Risk: months of environment, near-zero reflection practice, and the reference project is not even a reflection project, so it never proves the hard path.
- Evidence: D3; decisions-log "Reflection support" (GCC bugs 124200/125398, p2996 #262/#366); the input's scope says Level 1 does not design FIX.
- Ask: should the empty reference project include one tiny `^^`/`[: :]` target so the gate proves the reflection path and teaches you something?

## 4. Contradiction: D3 vs D1 vs D11 vs "100% per compiler" vs D13 one-config
- Issue: D3 says reflection projects have no plain-LLVM preset, so clang-tidy/IWYU/clangd (D11) cannot see reflection code at all (GCC .gcm unreadable by clang tools; plain clang has no P2996). Yet 100% coverage per compiler needs gcov on GCC modules, "UNVERIFIED". The gate then cannot be satisfied for exactly the code you care about. D1 still lists LLVM as the full gate and TSan role; D3 amends only partly (no TSan owner for GCC/p2996 stated; GCC ASan hung on Mac).
- Evidence: research/tooling-build-analysis.md headline 2 and gcovr row ("GCC modules + gcov UNVERIFIED"); research/tooling-perf-docs.md line 15 (GCC LSan run hung >100 s); D1/D3.
- Ask: for reflection code, which analyzers and which sanitizers are acceptable to be "absent", and does 100% coverage apply to generated/reflection-expanded lines?

## 5. D2 is stale against its own research: Homebrew cannot pin GCC; brew GCC is Sandoe's fork
- Issue: D2 relies on "exact versions plus brew pin". bootstrap-docs says brew cannot pin ("latest only"). On a FRESH Mac, brew gives whatever gcc is current, not 16.2.0, so the "fresh Mac" gate can break the day Homebrew moves to 16.3/17. Upstream GCC 16 does not support aarch64-darwin at all; you depend on iains' branch via Homebrew.
- Evidence: research/bootstrap-docs.md lines ~71, 116; decisions-log D2 and "Upstream GCC 16 does not support aarch64-apple-darwin".
- Ask: if Homebrew's gcc moves, do you fail the build, or pin by formula-revision/tap? Should GCC be Linux-only (Mac relies on Colima/Tart container) for Level 1?

## 6. apt.llvm.org pin rot makes D12 self-defeating
- Issue: exact pins die in days (apt.llvm.org deletes old builds); the legacy repo already had "llvm-apt-pin-churn" docs and an `llvm-bump` task. D12 accepts that old commits can't rebuild images. That conflicts with "reproducible/pinned" and creates daily Renovate PRs for one person plus a 2.5 h cold rebuild for p2996.
- Evidence: decisions-log D12; research/prior-image-work.md sections 3.2 and 6.
- Ask: would you take LLVM from a mirrored snapshot (e.g. your own GHCR layer / a release tarball by hash) instead of apt, accepting less "mise-first"?

## 7. GitHub Actions minutes and repo visibility are unaddressed
- Issue: D10 builds images on hosted runners, daily rebuild (D12), 3 compilers x 2 OS x 2 arch x sanitizers, p2996 cold build ~2.5 h. Actions minutes had run out at the time. cpp-standard was private at the time of review: private repos consume the quota, macOS runners bill 10x, arm Linux runners may not be free; GHCR images from a private repo are private, so devcontainers/other repos need auth (GITHUB_TOKEN/PAT); public repos get free Linux minutes and public GHCR. sccache GHA backend goes read-only when rate-limited (#2593).
- Evidence: D9 research (#2593); D10; research/mise-images.md line 113 (arm runner untested).
- Ask: public or private for cpp-standard and the glaze FIX repo? Use self-hosted runners for heavy jobs?

## 8. Secrets in CI not designed
- Issue: the local secret store is not usable in CI. CI needs a different path: GHCR push token, Renovate token, any registry credentials, vcpkg binary cache auth. Pinned Actions by SHA and fork-PR behavior (no secrets) are also unmentioned.
- Evidence: D7/D10 (binary cache, GHCR) with no secret plan.
- Ask: which secrets will CI need, and is "GITHUB_TOKEN only, no other secrets" an acceptable rule?

## 9. Renovate/Dependabot volume vs one person
- Issue: grouped image inputs, own PR for apt debs, daily p2996-HEAD PR, tool pins, vcpkg, Actions: easily 20-40 PRs/week, each triggering the expensive CI. Directly recreates the churn you want to stop; there is no automerge/cadence policy beyond "automerge apt debs".
- Evidence: D10, D12; research/prior-image-work.md section 3.1.
- Ask: weekly grouped PR and automerge-on-green only, with p2996 bumped manually monthly?

## 10. Who does the work?
- Issue: Level 1 as scoped is several parallel workstreams (image pipeline, Mac bootstrap, CI, tooling, docs generation). One contributor working serially takes weeks; parallel agents recreate the collision problem.
- Evidence: the input.
- Ask: how is Level 1 split into serial tickets, and what is the weekly budget?

## 11. Dropped: Apple Silicon profiler equivalents
- Issue: the input says "still need identifying", yet D11 lists perf/BOLT/llvm-mca as if available. Research found the answer (xctrace Time Profiler/CPU Counters work headless; leaks, sample available; BOLT is Linux-ELF only; Valgrind absent) but no decision records it, so nothing in the gate covers Mac profiling.
- Evidence: research/tooling-perf-docs.md headlines 2-5; decisions-log has no D for it.
- Ask: confirm "Mac = xctrace + leaks, Linux = perf/valgrind/BOLT in the container" as a decision, and does a profiling smoke test belong in the gate?

## 12. Dropped: EGM drift policing of agent docs; knowledge base/research index; harness cleanup
- Issue: owner's original goal included cleaning up old agent instruction docs and checking them with EGM. D1-D13 are all toolchain. No decision on drift (design doc vs code, agent instructions need their own standard), the C++ research index (P2996 papers, Orchestra spec), or a single source of truth for past rulings. These are the churn sources; they are not in Level 1.
- Evidence: the input, section 1 and gaps 14, 15, 17; decisions-log "Open" only lists Q3 and gaps generally.
- Ask: is a minimal agent-docs standard + a recurring EGM drift report part of Level 1 or explicitly Level 3?

## 13. cpp-core salvage timing and the open edge with dotfiles
- Issue: cpp-core is the only existing C++26 reflection library, closest to your learning goal, yet "out of scope" with 13 decisions (4 gating) waiting. D4 leaves "dotfiles pins cpp-utilities' catalogue 0.2.0" unresolved. D4 "copy pieces when needed" with cmake_template/the private prototype having 4 divergent preset generators means copying drift, exactly what D8 (hand-written layered presets) rejects.
- Evidence: D4; input items A2, 8, 19 ("cpp-core ... salvaged later").
- Ask: when is cpp-core's brainstorm scheduled, and should the reference project borrow its module layout rather than start empty?

## 14. FIX licensing and corpus questions never asked; hard-to-reverse choices not marked
- Issue: FIX Orchestra spec/XML repos (FIX Trading Community) have their own licence and the FIX versions/test corpus are undecided; glaze is MIT (fork vs new repo). Not decided: repo name/org, licence of the new repo. Reversibility is not recorded per decision: D13 (bootstrap-project, no `mise oci build`) leans on a new, pre-1.0 feature with upstream gaps (root data dir, no external PRs accepted to mise, only Discussions); D10/D13 are costly to undo, D8/D9 cheap.
- Evidence: input item 18; research/mise-upstream-asks.md section 0 and line ~134; D13.
- Ask: mark each D as one-way/two-way door, and who confirms the Orchestra licence before the repo goes public?

## 15. "Fresh Mac" gate is not testable as written
- Issue: the gate demands a fresh Mac, but no fresh Mac exists. Tart (openai/tart, FSL-1.1 licence, maintenance uncertain since Cirrus joined OpenAI) costs 30-50 GB/image, Mac awake, and brew/mise bootstrap on a fresh VM may differ from a real machine (SIP, Xcode, CLT, macOS 27 SDK patches for p2996). Disk space is already tight.
- Evidence: research/tart-macos.md lines 14, 53; input items A3, 20.
- Ask: is a Tart VM acceptable as "fresh Mac", run weekly rather than per commit, and where does its disk budget come from?
