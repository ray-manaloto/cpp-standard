# Goldfish brainstorm report: Level 1 of cpp-standard

* **Mode:** BRAINSTORM
* **Date:** 2026-11-13
* **Concept:** cpp-standard as (a) the written C++ standard, (b) an empty C++20-module reference project, (c) a reflection canary of pinned upstream projects, built from one mise bootstrap project (Tart macOS VM with the agents inside it, Ubuntu 26.04 arm64/amd64 images), gated by `mise run ci` across LLVM 23, GCC 16.2 and clang-p2996 on self-hosted runners fenced to the owner's account.
* **Evidence read by the reviewers:** `decisions-log.md` (D1-D20, including open question 6 on the runner fence), the reports in `research/`, and the owner's private brainstorm input and handoff note, which are not published here ("the input" below). There is no code yet, so every finding is about the design and the decision record.

## Reviewer status

| Reviewer | Role title | Status |
| --- | --- | --- |
| `egm-design` | Skeptical Architect Brainstormer | completed |
| `egm-codebase-details` | Technical Accuracy & Reuse Brainstormer | completed |
| `egm-zoom-out` | Contrarian / YAGNI Scope Brainstormer | completed |
| `egm-comprehension` | Naive Reader & Developer Ergonomics Brainstormer | completed |
| `egm-implementation-readiness` | Implementation Readiness & Operations Brainstormer | completed |
| `egm-structural` | Structure & Long-Term Maintenance Brainstormer | completed |
| `egm-inventive-catalyst` | Inventive Catalyst Brainstormer | completed |

All seven ran on the first attempt. The synthesizer checked these claims against the files: `p2996-linux.md:12` leaves `compiler-rt` out of the p2996 build; `tart-macos.md:44` says macOS guests cannot run nested virtualization; `blind-spots.md:27` and `bootstrap-docs.md:71` say Homebrew cannot pin a version; `external-image-examples.md:31` rates LLVM release tarballs through mise's `github:` backend as the "Recommended primary" source; the blank lines between the rows of the decisions table (lines 11, 13, 15 and so on) break it after D2.

## Overall verdict

Every lens reached the same conclusion: **as written, Level 1 is not ready to be planned, and in its current size it risks becoming the largest side issue in the program.** The core idea holds up under review: one written standard, one locked environment, one `mise run ci`, with everything else parked. The objections are about what surrounds that core:

- it has no end date;
- the owner writes no reflection code during it;
- it adds a VM, an image pipeline and self-hosted runners before any glaze FIX work;
- several decisions rest on things nobody has tested (agents in a macOS VM, p2996 sanitizers, gcov on GCC modules);
- the runner fence cannot tell the owner from the agents.

Severity labels: **Blocker** means the concept cannot proceed as stated. **Major** means it needs a decision before drafting. **Nit** means a fix during drafting.

---

## 1. Scope against the root goal

### 1.1 Level 1 has no timebox or kill rule. Blocker.
* **Lenses:** zoom-out, design, implementation-readiness, inventive-catalyst.
* **Concerns:** D5 ("once every Level-1 goal is met"), D11 ("every tool... now"), D19; `blind-spots.md` item 2; input gap 21.
* **Problem:** nothing limits how long Level 1 takes. D11 asks for every tool now, and D19 still wires all of tier 2 "from day 1". This is the same pattern that overtook the earlier "one lane at a time" ruling.
* **Recommendation:** set a calendar date, suggested 2 to 3 weeks out, on which glaze FIX work starts whatever state Level 1 is in. Whatever is unfinished on that date becomes a dated ticket. Write down in advance which items are cut first if the date slips.

### 1.2 The learning goal gets nothing: no reflection code of the owner's own. Blocker.
* **Lenses:** zoom-out, design, inventive-catalyst (also implied by codebase-details and comprehension).
* **Concerns:** D20 ("no reflection code of our own"), D3, D14.
* **Problem:** the canary proves only that other people's reflection code compiles. It teaches packaging, not `^^`, splicing or performance. Because the reference project is empty, the hard path glaze FIX depends on (GCC 16 `-freflection` plus named modules plus coverage) is never exercised. Level 1 can turn green while that path stays unproven.
* **Recommendation (all three lenses converged on this):** add one small owned reflection module of under about 100 lines to the reference project, for example a reflected enum-to-string or a struct-to-FIX-tag serializer. Build it only on GCC 16 and clang-p2996 (per D3). It does three jobs at once:
  - it is the learning vehicle;
  - it gives the 100% rule real code to measure, on reflection and modules;
  - it is a first piece of glaze FIX.

### 1.3 Session collisions are reported, not prevented. Blocker.
* **Lenses:** zoom-out, design, inventive-catalyst.
* **Concerns:** D15 ("Nothing is blocked"), D17, D18; input sections A1 and A4.
* **Problem:** the root cause the owner named is parallel sessions colliding and process weight. D15 only adds a line to a daily digest. Moving the agents into one VM moves the collisions there; it does not remove them. Two agents pushing to main still race, and each push still starts the full matrix. Codebase-details adds that the D15 check cannot even run in GitHub Actions, because the session list exists only on the local machine, which a GitHub Actions job cannot read.
* **Recommendation:**
  - Enforce the cap now with a PreToolUse hook that blocks new agent sessions beyond the cap (under 20 lines, no new repo).
  - Add hard limits: one worktree and one branch per agent, a merge queue on main, and CI concurrency that matches runner capacity.
  - Set a token or dollar budget per agent per week; the brief has none, and the input cites a $580 cost for one agent session.
  - If a digest check stays, run it as a local mise task on a launchd timer that publishes its result for the digest to read.
  - Inventive-catalyst notes that the 2-VM limit could enforce the cap physically on the Mac side.

### 1.4 Tier 2 "wired from day 1" is the scope creep. Major.
* **Lenses:** zoom-out, codebase-details, design, implementation-readiness, inventive-catalyst.
* **Concerns:** D11, D19; `tooling-build-analysis.md`, `tooling-perf-docs.md:184-194`.
* **Problem:** the owner's own research rates several of these tools "skip", "later" or impossible in this setup:
  - MLIR metrics from ordinary C++ builds are not possible;
  - BOLT is ELF-only and missing from Homebrew LLVM;
  - mrdocs has no module support (#1142);
  - perf counters inside a Tart guest are unverified;
  - ClangBuildAnalyzer and Esri link-what-you-include are rated "later" and "skip".

  Each report-only tool still needs integration, triage and digest plumbing.
* **Recommendation:** tier 1 only in Level 1. Every tier-2 tool becomes a dated ticket that enters when glaze FIX needs it. Remove MLIR and Esri. Mark BOLT and perf as Linux-only. Put mrdocs on a watchlist. Use clang-tidy `misc-include-cleaner` before IWYU, as glaze does. Zoom-out would also defer TSan until there is concurrent code; codebase-details would keep it and add one small threaded test so it checks something.

### 1.5 Digest and EGM cadence tooling is new process code. Major.
* **Lenses:** zoom-out, implementation-readiness.
* **Concerns:** D14, D15.
* **Problem:** a scheduled workflow, `review:*` tasks, daily drift checks and tier-2 listings add to the process weight the input names as a cause (A4).
* **Recommendation:** for Level 1, track the checklist as one GitHub issue with checkboxes or a Projects board, review it by hand once a week, and run `/egm-drift-report` at milestones. Build the digest in the last milestone, if at all.

---

## 2. The Mac and VM foundation (D16, D17)

### 2.1 Agents inside the Tart VM is an untested foundation. Blocker.
* **Lenses:** implementation-readiness, design, codebase-details, comprehension, zoom-out.
* **Concerns:** D10, D14, D17, D18; open question 1; `tart-macos.md:15`, `:44`.
* **Problem:** macOS guests cannot run nested virtualization, so an agent in the VM cannot run the Ubuntu devcontainers that D10 makes the Linux dev loop. An agent there cannot reproduce half of `mise run ci`, yet D14 ticks items only on a green `mise run ci`. None of the following has been tested:
  - agent sign-in, keychain, secrets and token persistence in a guest that gets re-cloned;
  - the terminal multiplexer across the VM boundary;
  - ASan, UBSan and TSan in a macOS guest;
  - whether a mise-installed Tart binary keeps its entitlements.

  Codebase-details adds that giving the VM the host's Docker socket gives it root on the host, which defeats D17's isolation.
* **Recommendation:** run a timeboxed spike (M0) with pass/fail results:
  1. clone the digest-pinned vanilla image and run `mise bootstrap`;
  2. run a clang-23 ASan+TSan hello test;
  3. run one agent session that stays signed in across a VM restart;
  4. drive a Linux container on the host or the PC over SSH or a Docker context.

  If any step fails, the agents stay on the host for Level 1, and the VM serves only as the fresh-Mac test and the runner. Either way, turn open question 1 into a decision that records the trust boundary chosen for Linux work: a remote Docker context, a Tart Linux VM, or SSH to the PC. Zoom-out goes further and would defer D17 entirely in favour of worktrees plus the devcontainer.

### 2.2 One Mac does everything, and Apple's 2-VM limit is already used up. Blocker.
* **Lenses:** design, implementation-readiness, inventive-catalyst.
* **Concerns:** D16, D17; `tart-macos.md` "Limits".
* **Problem:** the one Mac hosts the dev VM, the CI-runner VM and the arm64 Linux containers. A persistent dev VM plus an ephemeral runner VM fill both macOS VM slots, so a separate fresh-Mac test has nowhere to run. CI competes with development for CPU, RAM and disk. When the Mac sleeps, reboots or runs out of disk, both development and CI stop. Mac gate items exist only while the Mac is awake.
* **Recommendation:**
  - Name the Mac as the bottleneck in the brief.
  - Decide that one VM role is also the fresh-Mac test. Either the runner VM clones fresh for each job (implementation-readiness), or the dev VM is rebuilt from the bootstrap each week (inventive-catalyst). Design argues that one VM should not be both the fast runner and the fresh-Mac test; it suggests a Packer-baked runner image plus a separate weekly fresh-Mac job.
  - Move Linux CI to the PC and to hosted arm runners, so the Mac runs only macOS jobs.
  - Write down what happens when the Mac runner is offline: the job times out in the queue and shows as pending, not red.

### 2.3 No disk budget. Major.
* **Lenses:** design.
* **Concerns:** D17; `tart-macos.md` section 2; input A3.
* **Problem:** a 30 GB image, plus 35-80 GB per VM for two VMs, plus Ubuntu images carrying LLVM, GCC and a 2.8 GB p2996 prefix for two architectures, plus sccache (60 GB in the past) and vcpkg caches. All of it lands on a host that already has 160 GB unexplained and a 99 GB legacy directory.
* **Recommendation:** write a disk budget per component, set `TART_HOME` and the cache locations, add prune jobs, and free the legacy directories before installing Tart.

### 2.4 Bare-metal benchmark numbers have no home. Nit.
* **Lenses:** implementation-readiness, inventive-catalyst.
* **Recommendation:** for Level 1, take benchmark numbers from the PC, or from the Mac host with xctrace as a recorded exception. CI gates only on callgrind instruction counts. Inventive-catalyst calls this a separate, fenced "measurement executor".

---

## 3. Security of self-hosted runners on a public repo (D16, open question 6)

### 3.1 The fence trusts the identity the agents use. Blocker.
* **Lenses:** implementation-readiness, design, codebase-details, zoom-out, inventive-catalyst.
* **Concerns:** D16, D17, D20; open question 6 (decisions-log lines 119-125).
* **Problem:**
  - Agents push as the owner's personal account. Any workflow change an agent makes, including one caused by prompt injection while reading upstream code, passes the `github.actor` check.
  - The check is written inside workflow files that the same push can edit.
  - The D20 canary builds untrusted upstream code by design (rosetta was pushed one day ago and has no licence), on the same Mac that hosts the dev VM with the agents' credentials.
  - Implementation-readiness recalls, without having checked, that the Free plan probably cannot restrict runner groups to chosen workflows. If so, the `if:` conditions are the only fence.
* **Synthesizer note:** D16 names Renovate as an allowed bot on the self-hosted runners, but the open question 6 mitigation says Renovate PRs run on hosted runners only. The draft must pick one; every lens that addressed it picked hosted-only.
* **Recommendation:** the lenses agree on these:
  - Renovate PRs and the canary run on hosted runners only, with a minimum release age of at least 1 day.
  - Give the agents a separate machine user or GitHub App identity, so the owner's account means the owner.
  - Add CODEOWNERS plus a branch ruleset so changes to `.github/**` and to `mise.toml` tasks need the owner's review before they reach a self-hosted job.
  - Put self-hosted jobs behind an environment with required reviewers, or allow them only from protected branches.
  - Ban `pull_request_target` and pin every action by SHA.
  - Use JIT, single-use runner registration, with no secrets beyond `GITHUB_TOKEN`. Push to GHCR only from hosted jobs.
  - Put the runners on an isolated network segment, with no route from the runner VM to the dev VM.
  - Self-hosted runners only replay digest-pinned layers and never resolve or fetch new inputs (inventive-catalyst).

  Zoom-out adds that a public repo already gets free hosted x64 and arm64 Linux minutes. With p2996 deferred, hosted runners could cover the whole gate, and self-hosted runners would wait until a shortage is measured.

### 3.2 A containerised PC runner cannot run `container:` jobs. Major.
* **Lenses:** codebase-details.
* **Concerns:** D10, D16.
* **Problem:** D10 runs the Linux CI jobs inside the toolchain images. A runner that is itself a container needs Docker-in-Docker or the host's socket to start job containers, which defeats "containerised, ephemeral".
* **Recommendation:** use actions-runner-controller in container mode, or an ephemeral VM per job on the PC. Do not write a custom runner wrapper.

---

## 4. Compiler roles that do not fit together (D1, D2, D3, D6)

### 4.1 clang-p2996 cannot fill the sanitizer or coverage role D3 gives it. Blocker.
* **Lenses:** codebase-details, implementation-readiness, design.
* **Concerns:** D1, D3, D19; `p2996-linux.md:12`; `prior-image-work.md:79`.
* **Problem:**
  - The planned p2996 build leaves out `compiler-rt` ("add only if sanitizers... required: UNVERIFIED cost"). Without it there are no ASan, UBSan or TSan runtimes and no profile runtime, so p2996 can neither run sanitizers nor produce the llvm-cov report D3 requires at 100%.
  - p2996 has no Mac supply route. The research covers only Linux GHCR artifacts. The old Mac build lives in dotfiles, which D17 retires; it takes hours and needs four macOS 27 SDK patches. Inside an ephemeral VM it would be rebuilt every time.
  - CMake `import std` with p2996's libc++ is unverified.
  - No decision says who runs sanitizers for reflection projects on Linux.
* **Recommendation:**
  - Decide now whether `compiler-rt` goes into the p2996 build. If it does, check that ASan and the profile runtime work. If not, drop p2996's sanitizer and coverage roles for Level 1.
  - Give GCC 16 ASan and UBSan the Linux sanitizer role for reflection code.
  - Either design a content-addressed macOS p2996 artifact, built on the PC or the Mac, or state that reflection gates run on Linux only in Level 1.
  - Zoom-out would go further and defer p2996 entirely, using GCC 16 `-freflection` alone until it blocks real work.

### 4.2 There is no single compiler role matrix, and D1 and D3 contradict each other. Blocker.
* **Lenses:** comprehension, structural (also design and codebase-details).
* **Concerns:** D1 (line 9), D3 (line 12), D6, D14, D19, D20.
* **Problem:**
  - D1 says p2996 runs "only in projects that use reflection". D3 says projects without reflection "build on all 3 compilers". The empty reference project is a non-reflection project, so the log says both that it does and that it does not build on p2996.
  - D3 claims to amend D1, but D1 still reads as current.
  - Several cells are not decided anywhere:
    - who runs TSan for reflection code;
    - whether Mac GCC is a gate or only installed;
    - whether the canary owes any coverage.
* **Recommendation:** add one derived table to be the single source of truth. Rows: compiler × OS × architecture × project kind (plain, reflection, canary). Columns: standard library, build, ut, coverage tool, ASan, UBSan, TSan, Valgrind, clang-tidy, format, tier. Every cell reads "gate", "report" or "N/A because …". Generate the D14 checklist from this table.

### 4.3 Mac GCC cannot be pinned, and D2 depends on dotfiles, which D17 retires. Major.
* **Lenses:** codebase-details, implementation-readiness, design, comprehension, inventive-catalyst, zoom-out.
* **Concerns:** D2 against D17 and D18; `blind-spots.md:27`; `bootstrap-docs.md:71`; decisions-log line 72; `tooling-perf-docs.md:15`.
* **Problem:**
  - `brew pin` only stops upgrades on a machine that already has the formula. A fresh VM gets whatever gcc Homebrew ships that day.
  - D2 installs GCC "through mise bootstrap packages in dotfiles", but D18 says dotfiles is not a dependency.
  - Upstream GCC 16 does not support aarch64-darwin; Homebrew builds from Iain Sandoe's branch.
  - `libsanitizer` has no aarch64-darwin entry, and a GCC LSan run hung for over 100 seconds during research.
  - Nothing says the cpp-standard bootstrap installs Homebrew in the VM.
* **Recommendation:** the majority view is that GCC is Linux-only in Level 1 (conda gxx 16.2.0) and the Mac gate is clang only; Mac GCC can return later as a reporting-only leg. If Mac GCC stays, move its install into the cpp-standard bootstrap and fail when `g++-16 --version` is not 16.2.0. For a real pin, use a private tap with a versioned formula, or capture the 16.2.0 bottle by sha256 through mise's `http:` backend. Inventive-catalyst notes that relocating the bottle's dylibs is unverified.

### 4.4 The daily default compiler and preset for reflection work are undefined. Major.
* **Lenses:** comprehension.
* **Concerns:** the concept's "LLVM/clang 23 daily default"; D3, D8.
* **Problem:** glaze FIX cannot use plain LLVM. Nothing says which preset an agent picks by default in a reflection project, or which compiler feeds clangd and `compile_commands.json`. clang-tidy is tier 1 "on plain-clang targets" only, so it silently covers nothing in reflection projects.
* **Recommendation:** name a default preset per project kind, for example `dev` mapping to clang23 in plain projects and to gcc16-reflection in reflection projects, and name the clangd source. State which analyzers and sanitizers may be absent for reflection code.

### 4.5 Preset names are not specified, and naming them by major version will churn. Major.
* **Lenses:** comprehension, structural.
* **Concerns:** D8 (line 22).
* **Problem:** D8's layer names already mix styles ("gcc16, clang, p2996"). p2996 is based on LLVM 21. A newcomer cannot write `cmake --preset …` from the record. If names carry major versions, the move to clang 24 or GCC 17 renames presets in every consumer repo.
* **Recommendation:** list the exact preset names, and say which ones `mise run ci` runs on each host. Structural recommends naming by role (`llvm`, `gcc`, `p2996`) and keeping versions in the mise lock.

---

## 5. Reproducibility and update churn (D10, D12, D13, open question 2)

### 5.1 "Pin everything" against apt.llvm.org deleting old builds. Blocker for the root goal.
* **Lenses:** inventive-catalyst, codebase-details, design, implementation-readiness, zoom-out, structural.
* **Concerns:** D10 ("every input pinned by hash") against D12; `bootstrap-handson-2.md:39`; `external-image-examples.md:12`, `:31`.
* **Problem:**
  - D12 accepts that "a pin dies within days", so an older commit cannot rebuild its image. The pin is then only a record of what was built.
  - apt.llvm.org serves a branch snapshot (`23.1.6~++20261108…`), while the Mac has Homebrew 23.1.5, so "LLVM 23" means two different builds.
  - Every expired pin creates another Renovate PR running the full matrix, which recreates the churn the program exists to stop.
  - No GHCR retention rule protects the image digest that D12 calls the record.
* **Recommendations (alternatives; the draft should pick one):**
  - **Change the source** (codebase-details): install LLVM release tarballs through mise `github:llvm/llvm-project` with `asset_pattern`, which keeps checksums in `mise.lock`. The project's own research rates this "Recommended primary". The fallback is conda-forge clang/libcxx 23.1.5. First confirm that the Linux tarballs ship libc++ and compiler-rt. This keeps mise-first and removes the daily churn.
  - **Separate resolving from replaying** (inventive-catalyst, design): keep apt.llvm.org, but a resolve job that runs only when inputs change publishes the exact .deb set as a content-addressed GHCR artifact. Image builds then replay from that digest and never contact apt. Treat every unstable upstream (LLVM debs, the p2996 prefix, conda GCC, the Homebrew GCC bottle) as such a "toolchain layer".
  - **Whichever is chosen:** `devcontainer.json` and the CI `container:` reference the image by digest. A GHCR retention rule never deletes a digest that main references. An in-repo manifest maps each commit to its image digest and package versions. Mark this decision as one-way.

### 5.2 One person against the Renovate volume. Major.
* **Lenses:** inventive-catalyst, implementation-readiness, design, zoom-out.
* **Concerns:** open question 2; `blind-spots.md` estimates 20-40 PRs a week.
* **Recommendation (consensus):**
  - One weekly grouped Renovate "train" PR for the image inputs, merged automatically when green on hosted runners.
  - A minimum release age of at least 1 day, and `prConcurrentLimit` of about 3.
  - p2996 bumped by hand each month, never merged automatically.
  - Automerge for Actions and tool pins only. Workflow-file changes always need a human.
  - Inventive-catalyst adds: bisect a failed train automatically by group, and report the failure in the digest rather than opening more PRs.

### 5.3 The cost of building clang-p2996. Major.
* **Lenses:** implementation-readiness, zoom-out, design.
* **Concerns:** D3, D20; `p2996-linux.md` lines 6-7 and 23-32.
* **Problem:** a cold build takes 61-76 minutes per architecture on hosted runners, and nobody has checked that it fits in a hosted runner's roughly 14 GB of free disk. The p2996 pin policy is also inconsistent: the input says "latest commit", the legacy setup opened a daily HEAD PR, and the research names pin `562409c7`.
* **Recommendation:** add a decision that sets the pin, a monthly manual bump, and the Mac source. Publish content-addressed artifacts for Linux, and for macOS too if Mac p2996 stays. Zoom-out would use `vsavkov/clang-p2996` as a stopgap only if p2996 is needed at all in Level 1, although the research says not to depend on those images.

### 5.4 The repo depends directly on new mise features. Major.
* **Lenses:** structural.
* **Concerns:** D13; `mise-upstream-asks.md`.
* **Problem:** `mise bootstrap` is new and has known gaps, and mise takes no outside PRs. The image builds, the fresh-Mac setup and the VM all call it directly.
* **Recommendation:** put it behind one entry-point task (for example `mise run env:provision`) so the provisioning method can change in one place. Zoom-out suggests starting the image as one Dockerfile in risu729's pattern: a digest-pinned `ghcr.io/jdx/mise`, then `ubuntu:26.04@sha256`, then `mise install --locked`. Build arm64 first and add amd64 once it is green.

---

## 6. What the gate actually proves (D3, D14, D19, D20)

### 6.1 100% coverage on an empty project proves little, and gcov on GCC modules is unverified. Major.
* **Lenses:** zoom-out, design, implementation-readiness, codebase-details, inventive-catalyst.
* **Concerns:** D3, D14, D19; `blind-spots.md` item 4; `tooling-build-analysis.md:54`, `:173`.
* **Problem:** 100% of almost nothing passes trivially. Whether gcov and gcovr can read GCC named-module units has not been tested. If they cannot, the GCC 100% gate can never pass, on exactly the compiler reflection depends on.
* **Recommendation:**
  - In M0 or M1, run gcov and gcovr on one named module that uses `import std`. If that fails, record a written exclusion instead of chasing it.
  - Apply the 100% rule to owned code only. The owned reflection module from finding 1.2 gives it something real to measure.
  - **Negative controls** (inventive-catalyst): add fixtures that must make CI fail (one uncovered line, one ASan heap overflow, one TSan race, one clang-format violation) and a meta-test that asserts they do fail. The gate then proves it works without needing real code.

### 6.2 The canary cannot run upstream tests "through vcpkg", and it should not block the gate. Major.
* **Lenses:** codebase-details, structural, zoom-out, design.
* **Concerns:** D14 (only a green `mise run ci` on main ticks an item), D20.
* **Problem:**
  - vcpkg ports install libraries; they do not build or run the upstream test suites. Running glaze's reflection26 tests or simdjson's tests needs each project's own source tree at a pinned commit.
  - The compiler flags differ per project: glaze uses `-freflection -fexpansion-statements`, while the log assumes `-freflection-latest`.
  - Pins close to upstream HEAD, GCC's roughly 41 open reflection bugs and experimental p2996 will turn main red for reasons the owner does not control. The allow-list becomes a weekly chore.
  - rosetta is one day old and has no licence.
  - glaze already runs gcc16-reflection and p2996 CI upstream, so the canary repeats work that is already done.
* **Recommendation:**
  - Build the canary from source at a pinned commit per project, using vcpkg only for their dependencies, with a flag set per project.
  - Run it as a separate, report-only scheduled workflow outside `mise run ci`, on hosted runners.
  - Each allow-list entry carries an upstream issue link and an expiry date.
  - Drop rosetta, or wait until it has a licence and some age.
  - Zoom-out would keep glaze only, since it is the FIX dependency.
  - Never put rosetta build outputs in any public cache or in GHCR.

### 6.3 `mise run ci` cannot run the full gate from where the agents work. Major.
* **Lenses:** comprehension (also design 2.2).
* **Concerns:** D14, D17; open question 1.
* **Recommendation:** define `mise run ci` per host, with explicit tasks `ci:mac`, `ci:linux-arm64` and `ci:linux-amd64`, plus a documented way for an agent in the VM to start the Linux legs. State how source is shared between the VM and the devcontainers.

---

## 7. CI capacity, caches and debuggability

### 7.1 The matrix is too big for two self-hosted runners. Major.
* **Lenses:** design.
* **Concerns:** D3, D16, D19, D20.
* **Problem:** a rough count gives 30-40 jobs per push, and D16 runs them on a push to any branch while agents push often. With one PC and one Mac VM, the queue grows faster than it drains, and an ephemeral Tart runner re-bootstraps on every job unless its image is pre-baked.
* **Recommendation:** a fast PR lane (one compiler per OS: build, ut and ASan); the full matrix on main through a merge queue; the canary and image rebuilds on a schedule; concurrency groups with cancel-in-progress.

### 7.2 Ephemeral runners lose their caches. Major.
* **Lenses:** design, zoom-out.
* **Concerns:** D6, D7, D9, D16.
* **Problem:** with more than 15 triplet and sccache key namespaces, every cache falls back to the GitHub Actions cache. That cache has a size cap and evicts entries, and its sccache backend goes read-only when rate-limited (#2593). D9's "one clean build" is ambiguous: it could mean no cache at all, or an empty build directory with a warm cache (comprehension). D9 states as fact that sccache caches module builds, but the tooling report marks that UNVERIFIED (codebase-details).
* **Recommendation:** use persistent cache volumes on the PC and the Mac host, read-only for PR jobs and writable from main, or publish the vcpkg binary cache to GHCR. Set a size budget per cache. Build only the triplets the reduced matrix needs. Zoom-out would defer sccache until build time is measured as a problem. Mark D9 as pending until it is checked.

### 7.3 There is no plan for debugging a failed run on an ephemeral runner. Major.
* **Lenses:** codebase-details.
* **Concerns:** D14, D16, D19.
* **Recommendation:** every job uploads as artifacts its CTest JUnit output, sanitizer logs, `sccache --show-stats`, vcpkg `buildtrees/*.log`, the image digest and the compiler `--version`. The digest links to them. Otherwise diagnosing a red run needs a rerun, which is the churn Level 1 is meant to remove.

---

## 8. How the repository is split

### 8.1 One repo holds about nine concerns that change at very different rates. Blocker (structural); others treat it as part of the scope problem.
* **Lenses:** structural.
* **Concerns:** D5, D10, D12-D16, D18, D20.
* **Problem:** the repo would hold:
  - the standard document, which rarely changes;
  - the reference project;
  - the canary, which moves with upstream;
  - the bootstrap project;
  - the image pipeline, with daily rebuilds and apt pins that expire in days;
  - the p2996 build and its publishing;
  - the reusable workflows;
  - the agent harness for the VM;
  - the digest and session-cap tooling.

  glaze FIX will pin the workflows and the bootstrap ref to this repo, so it would receive upgrade PRs for changes that do not concern it. The digest and session-cap check are portfolio tools, not part of a C++ standard.
* **Recommendation:** split by change rate. A toolchain repo holds the bootstrap, images, the p2996 build, the runner and VM setup and the reusable workflows; it releases with semver tags and image digests. cpp-standard holds the document, the reference project and the canary. The portfolio tooling moves out. If the owner keeps one repo, use top-level directories, workflows filtered by path, and separate release tags (for example `workflows-v1`).

### 8.2 The reference project does not test what an outside project will use. Major.
* **Lenses:** structural.
* **Recommendation:** the reference project consumes the workflows, bootstrap and image only through their public, versioned interfaces: a cross-repo `workflow_call` at a tag, a pinned bootstrap ref, and the published image digest. This holds even if it stays in the same repo.

### 8.3 The agent harness is versioned inside the C++ standard. Nit.
* **Lenses:** structural.
* **Recommendation:** give it its own directory, an owner and a README contract, and state when it moves out.

---

## 9. The decision record itself (needed before `/egm-draft`)

### 9.1 Amendments live in later rows, and the rows they change still read as current. Blocker.
* **Lenses:** structural, comprehension.
* **Concerns:**
  - D1/D3;
  - D5, which lists three roles while the concept has grown to include the canary, bootstrap, images, VM harness and runners;
  - D10/D16 (D10 says hosted runners build the images; D16 moves the heavy jobs to self-hosted runners; D10 says "Renovate or Dependabot");
  - D16 against the unpublished handoff note, which still said private;
  - D2 against `blind-spots.md:27`.
* **Recommendation:** add a Status column (Accepted, Provisional, Amended by Dn, Superseded, Challenged). Rewrite amended rows in their final form, and keep the history in a changelog.

### 9.2 Decisions still waiting on research are filed as decisions. Major.
* **Lenses:** structural, comprehension.
* **Concerns:** D9, D10, D11, D13 (each says "pending").
* **Recommendation:** mark each one Provisional, name the report that will settle it, and state what result would reverse it. Update D13 with the round-2 hands-on results.

### 9.3 The open-question lists are stale and duplicated. Major.
* **Lenses:** structural, comprehension.
* **Concerns:** lines 128-133 against D3 and D4; the two separate open-question sections; the 15 blind-spots items have no recorded outcome.
* **Recommendation:** keep one numbered list. Close the questions D3 and D4 already answered. Record an outcome for every blind-spots item.

### 9.4 There is no goals/non-goals section, and "done" is defined in three places. Major.
* **Lenses:** structural.
* **Concerns:** the unpublished handoff note, D14, D19; non-goals scattered across D4, D17, D18.
* **Problem:** the root goal never appears in the log, so no decision can be checked against it. The three definitions of done disagree.
* **Recommendation:** add Goals (including the root goal in so many words), Non-goals (each with the decision that excludes it), and one definition of done that other places point to.

### 9.5 Evidence links will break when the repo is scrubbed for going public. Major.
* **Lenses:** structural, implementation-readiness.
* **Problem:** the evidence column points to session IDs, branches in private repositories and paths outside the repo, which D16 requires scrubbing. Git history keeps everything ever committed, so the scrub has to happen before the first public push.
* **Recommendation:** copy or summarise each piece of outside evidence into `research/` first, so every decision has at least one evidence link inside the repo.

### 9.6 Undefined terms, no "start here" page, and broken markdown. Major and Nit.
* **Lenses:** comprehension, structural.
* **Problem:**
  - These terms are never defined: ut, Q2/Q3, resolute-23, EGM/Goldfish, "the PC", fnox, risu729, the owner's personal account vs ray-manaloto, "glaze FIX" vs "glaze fork", and "hardening flags".
  - The session cap's number is never stated.
  - There is no page telling a new agent how to enter the VM, which preset to use, which task does what, where the Linux legs run, and which secrets exist where.
  - Blank lines between the table rows end the table after D2 (Nit).
* **Recommendation:** add a glossary; it also serves as the scrub list. Make a one-page AGENTS.md "operating card" a gate item, checked against the role matrix (4.2). Remove the blank lines between table rows.

### 9.7 Decisions are not marked as one-way or reversible. Nit.
* **Lenses:** design, structural.
* **Recommendation:** mark D10, D12, D13, D16 and D17 as one-way doors, since they are costly to undo, and give them the deeper review. Decide the cheap ones (D8, D9) quickly. Record Tart as reversible, with a hosted macOS runner as the fallback.

### 9.8 Version and date inconsistencies. Nit.
* **Lenses:** codebase-details.
* **Problem:** `mise-images.md:48` names `llvm-toolchain-resolute-22`, while D12 says resolute-23. CMake 4.5.0 was released one day before the decisions (2026-11-12). The p2996 pin policy is inconsistent (see 5.3).
* **Recommendation:** reconcile these, and hold CMake at exactly 4.5.0 until 4.5.1.

### 9.9 No plan for running beside the old setup. Major.
* **Lenses:** implementation-readiness.
* **Concerns:** D4, D17, D18.
* **Recommendation:** freeze the host toolchain as it is, without removing it, until the Level-1 checklist is green, and define how to roll back if the VM setup fails partway through. Record the cpp-utilities catalogue 0.2.0 dependency in D4.

---

## 10. Reuse before writing anything new. Nit.
* **Lenses:** zoom-out, codebase-details.
* **Recommendation:** start each part from existing work, which D4 already allows to be copied with a source link:
  - glaze's workflows for clang-tidy, coverage, sanitizers, quickfuzz and p2996 (`gcc.yml`, `p2996-reflection.yml`);
  - CppReflectionAD's presets and its cache-keyed p2996 build;
  - libCat's `jdx/mise-action` setup;
  - risu729's Dockerfile and Renovate `packageRules`;
  - hk's built-in format hooks;
  - github-action-benchmark;
  - cirruslabs' Packer templates for the Tart runner image;
  - actions-runner-controller for the PC runner.

---

## Inventive contradictions (inventive-catalyst, with support from the other lenses)

| # | Contradiction | Resolution principle | Proposed resolution | Cost |
| --- | --- | --- | --- | --- |
| C1 | Pin everything against apt.llvm.org deleting old builds | Prior action; separation in time; segmentation | A resolve job publishes content-addressed toolchain layers to GHCR, and image builds replay them by digest. Alternatively, change the source to LLVM release tarballs in `mise.lock`. | You run a small artifact mirror with a retention policy; the resolve job is new code. |
| C2 | Latest everything against reproducibility | Separation in time and by condition; dynamics | A locked **gate lane**, plus a scheduled report-only **edge lane** that resolves "latest" and promotes its digests after N green days. | Edge-lane CI time; promotion logic; the gate lags upstream by N days. |
| C3 | One person against the Renovate volume | Intermediary; self-service | One weekly train PR, automerged on green, with failed trains bisected by group; p2996 bumped by hand. C1 removes the apt churn. | Updates arrive up to a week late. |
| C4 | Full VM isolation against bare-metal numbers, nested virtualization and the 2-VM limit | Separation in space; extraction; cheap dispensables | The VM is for writing code only. Linux runs and measurements are delegated to the PC or host executors, behind a fence. The dev VM is rebuilt weekly from the bootstrap, so it doubles as the continuous fresh-Mac test. The VM count caps sessions physically. | Remote-execution latency; each delegated path needs its own fence. |
| C5 | A 100% gate against an empty project and upstream canaries | Separation by condition; blessing in disguise | 100% applies to owned code only. Negative-control fixtures prove that each check actually fails when it should. | Fixtures to maintain; one per tier-1 tool. |
| C6 | Learning reflection against "no reflection code of our own" | Segmentation; separation by condition | One owned reflection module of under about 100 lines, built only on GCC 16 and p2996. It is learning vehicle, coverage subject and glaze FIX prototype at once (merges with C5). | clang-tidy and clangd cannot see it; GCC reflection bugs may need an exception path. |
| C7 | Free compute from a public repo against code running from trusted pushes | Inversion; separation in space | Self-hosted runners only replay pinned layers and never fetch. Trains and workflow changes run hosted until merged. | Hosted minutes; slower feedback on infrastructure changes. |
| C8 | "Every tool now" against "stop losing time" | Separation in time; dynamics | Tier 2 becomes dated tickets, promoted automatically after N clean edge-lane runs, under a timebox with a kill date. | The owner accepts a partial Level 1. |
| C9 | Homebrew GCC against pinning | Prior action | Capture the 16.2.0 bottle by sha256 as a layer, or drop Mac GCC from Level 1. | You own dylib relocation (unverified). |

## Ideal Final Result

Level 1 delivers what it is for with almost no ongoing attention from the owner:

- **The repository holds only intent and digests:** the written standard, the presets, one small owned reflection module, the negative-control fixtures, and digest references to toolchain layers it owns. Any commit can rebuild its toolchains, at any time.
- **Updates happen on their own:** an edge lane tracks "latest" and promotes after N green days. Renovate sends one weekly train that merges itself when green. Only workflow changes and p2996 bumps need a human.
- **The gate proves itself:** negative controls show that every tier-1 check fails when it should, and the 100% rule runs on real owned reflection code under both reflection compilers.
- **Environments are cheap to throw away:** the dev VM is rebuilt from the bootstrap on a schedule, so the fresh-Mac test runs continuously. Sessions are capped by a hard limit, not a report. Measurements run on bare metal.
- **The owner's attention** goes to one short digest and to writing C++26 reflection code. Every other side issue either resolves itself or waits for a scheduled slot.

## Where the lenses converged: a smaller Level 1 and a milestone order

The lenses did not all agree on how much to cut. Zoom-out cut the most; implementation-readiness and design kept more but put it in a strict order. The common ground:

- **M0, spikes, a few days, each with a pass/fail result:**
  - agents in the Tart VM (sign-in survives a restart, sanitizers work, Linux containers can be reached);
  - the 2-VM layout;
  - JIT single-use runner registration;
  - the gcov named-module probe;
  - whether p2996 gets `compiler-rt`.
- **M1, the first deliverable to verify:**
  - the public repo, with the security rules from 3.1 and the scrub done first;
  - a digest-pinned linux/arm64 image built from the bootstrap (clang 23 + libc++, conda gxx 16.2);
  - `mise run ci` on hosted runners: an empty module project plus the owned reflection module, ut, 100% llvm-cov and gcov coverage, ASan/UBSan/TSan, and negative controls;
  - a session-cap hook;
  - Renovate on a weekly train.
- **M2:** amd64, Valgrind, clang-format, clang-tidy, SARIF upload.
- **M3:** the Mac: the Tart runner VM and the fresh-Mac test, with a clang-only gate.
- **M4:** p2996 artifacts and the reflection canary (glaze first), report-only, on hosted runners.
- **M5:** tier-2 tools as dated tickets, and the digest.
- **A timebox over all of it:** glaze FIX starts on a fixed date.
