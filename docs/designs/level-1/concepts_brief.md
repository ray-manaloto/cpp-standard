# cpp-standard: the Level 1 C++ environment and project standard

* **Author:** ray-manaloto
* **Date:** 2026-11-13

## Overview

The owner keeps losing time to side issues and to agent sessions that collide with each other. This brief consolidates the decisions about the owner's C++ work into one standard so that a single project, glaze FIX, can go ahead without the setup moving underneath it.

`ray-manaloto/cpp-standard` is a public repository in the free `ray-manaloto` GitHub organisation. It holds three things:

1. **A written standard** for how every C++ project is set up.
2. **A small reference project** built with C++20 modules, which proves the standard works.
3. **A reflection canary.** It builds and tests pinned upstream projects that use C++26 static reflection: glaze, reflect-cpp, simdjson and rosetta.

One mise bootstrap project builds the environment, with every input pinned and updated by Renovate. The environment is:

- a Tart macOS VM, where the AI agents also run;
- Ubuntu 26.10 container images for arm64 and amd64 (D25), used as devcontainers locally and as GitHub Actions job containers.

`mise run ci` is the gate. It builds the code, runs the ut tests, checks 100% line coverage per compiler, runs the sanitizers, and runs the tier-1 tools. It uses three compilers, each with a fixed role: LLVM/clang 23, GCC 16.2 and Bloomberg clang-p2996. Heavy jobs run on self-hosted runners on the owner's PC and Mac.

Every other C++ project is parked. glaze FIX is built on this standard after Level 1, and Level 2 is a separate brainstorm that decides what glaze FIX implements.

The 25 decisions behind this brief are in `decisions-log.md` (D1 to D25). The evidence is in `research/`. The independent review is in `goldfish_brainstorm_report.md`.

## Analysis

The Goldfish review (7 fresh-context lenses) concluded that **the concept is not ready to plan as it stands.**

What survived the review: one written standard, one locked environment, one `mise run ci`, and everything else parked.

The objections are about what has been added around that core. In its current size, Level 1 risks becoming the biggest side issue in the programme, which is the problem it was meant to solve.

### Blocking objections (to resolve before or in `/egm-draft`)

1. **Level 1 has no end date and no cut-off rule.** D11 and D19 ("all tooling now") and D5 make Level 1 open-ended.
   - Proposed fix: set a date about 2 to 3 weeks out when glaze FIX starts regardless. Anything unfinished becomes a dated ticket.
2. **The owner writes no reflection code.** The D20 canary only proves that other people's code compiles. The owner's stated learning goal is C++26 reflection, and an empty project never exercises GCC `-freflection` together with modules and coverage.
   - Proposed fix: one owned reflection module of about 100 lines, built on GCC 16 and clang-p2996. It is the learning vehicle, the code the 100% rule measures, and a first piece of glaze FIX.
   - This reverses part of D20, which is the owner's call.
3. **Session collisions are only reported, never prevented.**
   - D15 reports the session cap but blocks nothing.
   - Moving the agents into one VM (D17) moves the collisions there.
   - The D15 check cannot run in GitHub Actions, because the session list exists only on the local machine, which a GitHub Actions job cannot read.
   - Proposed fixes: block tab creation beyond the cap, one worktree per agent, a merge queue, and a weekly token budget per agent.
4. **Running the agents inside the Tart VM (D17) has never been tested.**
   - A macOS guest cannot use nested virtualization, so agents there cannot run Docker or the Linux devcontainers.
   - Untested: whether agent sign-in survives re-cloning the VM, whether the terminal multiplexer works across the VM boundary, and sanitizers in a macOS guest.
   - Apple allows two macOS VMs at once. The dev VM and the runner VM use both, and one Mac carries dev, CI and the arm64 Linux containers.
   - Proposed fix: a pass/fail spike ("M0") before anything else. If it fails, the agents stay on the host.
5. **The self-hosted runner fence (D16) trusts the account the agents push as.**
   - Agents push as the owner's personal account.
   - The `if:` check lives in workflow files that any push can edit.
   - The canary builds untrusted upstream code on the same Mac as the agents' credentials.
   - D16 also contradicts its own mitigation note about Renovate.
   - Proposed fixes: a separate agent GitHub identity; CODEOWNERS and a branch ruleset on `.github/**`; Renovate and the canary on hosted runners only; single-use runners with no secrets.
6. **clang-p2996 cannot do the job D3 gives it.**
   - The planned build leaves out `compiler-rt`, so it has no sanitizer runtimes and no coverage runtime.
   - Nothing supplies p2996 on the Mac.
   - D1 and D3 disagree, and there is no single table of compiler × OS × project kind × check.

### Major objections

7. **GCC on the Mac (D2).**
   - A fresh machine can't pin it, because `brew pin` only holds an existing install.
   - D2 still installs it through dotfiles, which D17 and D18 retire.
   - Majority view: in Level 1, GCC runs only on Linux.
8. **Expiring apt.llvm.org pins and Renovate volume (D12) would bring the churn back.** Two alternatives:
   - LLVM release tarballs through mise's `github:` backend, with checksums in `mise.lock`. The research rated this the primary option.
   - Resolve the packages once and publish content-addressed toolchain layers that image builds reuse by digest.

   Either way: one weekly Renovate batch that merges itself when CI is green, clang-p2996 bumped by hand, and a retention rule for GHCR.
9. **The gate is weak.**
   - 100% coverage of an empty project is trivially met.
   - gcov on GCC named modules is unverified.
   - vcpkg does not run upstream test suites, so the canary has to build from source, stay report-only, and sit outside `mise run ci`.
   - Proposed fix: negative-control fixtures that must make CI fail: one uncovered line, one ASan overflow, one TSan race and one format violation.
10. **The decision record is not ready for drafting.** It needs a status for each decision, provisional decisions marked as such, one list of open questions, one definition of done, a glossary, and in-repo copies of the evidence that currently lives in local paths. One reviewer also suggests moving the toolchain, images and workflows into a separately versioned repository.

### Inventive contradictions and the Ideal Final Result

The report lists nine contradictions (C1 to C9), each with a resolution and its cost. Examples: "everything pinned" against "always the latest"; "isolated VM" against "real performance numbers"; "all tools on day 1" against "stop the churn".

The **Ideal Final Result**:
- the repository holds only intent plus digests;
- updates arrive and merge on their own when CI is green;
- the gate proves its own checks fail when they should;
- environments are cheap to throw away and rebuild;
- the owner's attention goes to one digest and to writing reflection code.

### Proposed milestone order (from the review)

- **M0.** Spikes: agents in the Tart VM, gcov on GCC modules, p2996 with compiler-rt.
- **M1.** An arm64 image and `mise run ci` on hosted runners, with the owned reflection module.
- **M2.** amd64 and lint.
- **M3.** The Mac/Tart runner.
- **M4.** clang-p2996 and a glaze-only canary.
- **M5.** Tier-2 tools.

All of it is timeboxed.

## Goals vs. Non-Goals

* **In-Scope Goals:**
  - One written C++ standard covering compilers and their roles, standard libraries, CMake 4.5 presets, vcpkg triplets, sccache, tests, coverage, sanitizers and tool tiers.
  - An empty C++20-module reference project.
  - A reflection canary on GCC 16 and clang-p2996.
  - One mise bootstrap project that builds the macOS VM and the Ubuntu 26.10 arm64 and amd64 images, with every input pinned and updated by Renovate.
  - `mise run ci`, identical locally and in GitHub Actions.
  - Self-hosted runners with a defined fence.
  - A daily digest with no model calls, and EGM reviews triggered by changes.
* **Out-of-Scope Non-Goals:**
  - The glaze FIX implementation (Level 2).
  - cpp-core, which keeps running on free models and is salvaged later.
  - The other parked projects: the private prototype, cpp-utilities, the templates, cpp-playground, and the glaze spikes until Level 2.
  - The project-template generator.
  - Cleaning up the host's agent harness and the existing rulings.
  - The rest of the dotfiles cut, beyond retiring its C++ parts.
  - Windows.

## Alternatives Weighed

- **One compiler for Level 1, or all three everywhere** (Q2). Rejected by the owner in favour of a role per compiler (D1).
- **conda-forge GCC on macOS.** Rejected because it is built against libc++ and miscompiles `std::string` and `std::println`. Evidence: the private prototype's findings and the ctng-compilers feedstock patch 0002.
- **One coverage tool for every compiler** (gcov only, or llvm-cov only). Rejected by the owner: each compiler uses its matching tool (D3).
- **Merging the setup repos into cpp-standard, or keeping the private prototype active.** Rejected by the owner in favour of parking them and copying pieces over when needed (D4).
- **cpp-standard as docs only, or the standard kept in dotfiles.** Rejected by the owner (D5).
- **A preset generator** (the private prototype's Pkl generator or the cpp-utilities catalogue). Rejected by the owner in favour of hand-written layered presets (D8).
- **ccache.** Rejected because it does not support C++20 named modules (ccache manual; PR #1523 is still a draft).
- **LLVM release tarballs and conda-forge clang for Linux LLVM.** Rejected by the owner in favour of apt.llvm.org with exact pins (D12). The Goldfish review reopens this (objection 8).
- **`mise oci build`.** Rejected because it does not apply `[bootstrap.apt.sources]`. Reproduced: `E: Unable to locate package clang-23`.
- **A plain Dockerfile pipeline outside mise.** Rejected by the owner in favour of a mise bootstrap project (D13).
- **A private repository on hosted runners only.** Rejected because the Free plan gives 2,000 minutes a month, which is too few (D16).
- **Host-native development.** Rejected by the owner in favour of full isolation in a VM (D17). The review asks for a spike first (objection 4).
- **Forking mise.** Rejected because mise takes no outside PRs; feature requests go to Discussions.
- **Every tool gating CI, or only four checks gating.** Rejected by the owner in favour of two tiers (D19).

## Key Decisions & Staging for Next Steps

- **Carried forward as decided:** D1 to D25 in `decisions-log.md`.
- **Settled after the Goldfish review:**
  1. **End date (D21).** Level 1 ends on 2026-11-27. Whatever tier-1 items are green then form the standard, and glaze FIX starts regardless.
  2. **Owned reflection module (D22).** About 100 lines, shaped like FIX: a reflection-generated encoder for tagged fields, using P3394 annotations. It builds on GCC 16 and clang-p2996 at 100% coverage. The canary stays.
  3. **Collisions (D23).** One worktree per agent, a GitHub merge queue into main, and a local `review:cap` check. This replaces D15.
  4. **M0 spike approved (D24).** It covers agents in a Tart VM, gcov on GCC modules, and clang-p2996 with compiler-rt. If the Tart part fails, the agents stay on the host. The approval is recorded only; the owner assigns the work.
- **Still provisional, to settle in `/egm-draft`:**
  - D2 (GCC on the Mac);
  - D12 (apt.llvm.org pins versus LLVM release tarballs);
  - D16 (the runner fence and a separate agent identity);
  - D17 (depends on the M0 result);
  - the gate's negative-control fixtures.
- **Open questions from the decisions log:**
  - the limits of the VM;
  - Renovate volume;
  - dropped asks (Apple Silicon profilers, a research index, the timing of the cpp-core salvage);
  - checks before going public (scrubbing local paths, the FIX Orchestra licence, rosetta's missing licence);
  - posting the mise upstream asks;
  - the limits of the D16 fence.
- **The next EGM step is `/egm-draft`.** It produces a design for "cpp-standard: environment and project standard" from this brief and the reports in `research/`.
