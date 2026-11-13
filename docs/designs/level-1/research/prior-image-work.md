# Prior Linux toolchain image work: what exists, what broke, what to harvest

Date of research: 2026-11-13. Read-only research; nothing in the prior repos was changed.
Tags: [verified] = read in source or reproduced with a command; [claimed, unverified] = a doc or comment says so and it was not reproduced.
The private prototype is a private repository; its findings are summarised here without paths or quotes.

## 1. Short answer

Two real attempts exist, built on opposite ideas. Neither is the design the owner now wants. Take pieces from each.

| | private prototype, private (Nov 2026) | dotfiles-legacy (Jul-Oct 2026) |
|---|---|---|
| Builder | `mise oci build` (experimental) | Dockerfile + BuildKit bake |
| Base | Ubuntu 24.04, digest-pinned (not latest) | Ubuntu 26.04, digest-pinned |
| LLVM | conda clangxx 23.1.4 via `mise.lock`; BOLT from a 23.1.5 tarball | apt.llvm.org 22.1.8, exact version pins per package |
| GCC | conda gxx 16.2.0 plus apt g++-14 | conda gxx 16.2.0 on arm64 only; amd64 gets distro gcc + GCC 17 from kayari.org |
| p2996 | spec only, never built in the image | built from source in a cached stage |
| Update bot | none (manual two-commit digest flow) | Renovate, rich config; Dependabot for pip only |
| Used as CI job container | yes, proven | no, a devcontainer plus bake caches |

Nothing found anywhere contains cmake 4.5, vcpkg in the image, or sccache for the p2996 build in a Linux image. [verified: grepped]

## 2. The private prototype (private)

### 2.1 What it did
- One image is shared by CI container jobs and local analysis tasks. amd64 is built on a hosted runner, pushed to a private GHCR package, and pulled by a digest committed in the repository; arm64 is local-only. A change takes two commits: change the inputs, then record the new digest.
- The image is described in a mise config: conda `gxx 16.2.0`, conda `clangxx` held only by the lock, apt pins, and copied-in valgrind and BOLT. Base: Ubuntu 24.04 by digest.
- A build script runs mise inside a digest-pinned `buildpack-deps` container, checks sha256 sums for mise, the LLVM tarball and valgrind, builds valgrind from source, runs a locked `mise install`, then `mise oci build`.
- A workflow tags the image `inputs-<hash>`, skips the build when the tag exists, pushes, and compares the manifest digest with the recorded one.
- Its notes report a first CI build of about 8 minutes (estimate was 25) and a container-job test run of about 3.5 minutes. [claimed]

### 2.2 What broke and why
1. Container-job gotchas: jobs run as root with no sudo; `--privileged` is needed for `/proc/sys`; mise trust; the `runner.temp` host path; git must be in the image; a `safe.directory` failure killed one test run. [claimed, consistent with GitHub Actions behaviour]
2. apt.llvm.org cannot give an exact version: on 2026-11-10 the numbered suite served only `1:23.1.6~++20261108...`, not 23.1.5, and the build seen on 2026-11-04 was gone. [claimed]
3. `mise oci build` ignores `[bootstrap.apt.sources]` (so a third-party apt repo cannot be added) and skips fnox entries, as of mise v2026.11.6. [claimed, unverified]
4. Version mismatch: BOLT tarball 23.1.5 vs conda clang 23.1.4, recorded as an accepted gap. [verified: inconsistent text]
5. A placeholder digest gave `manifest unknown` before the digest commit; a private package returns 401 anonymously, so local pulls need `read:packages` and `docker login ghcr.io`. [claimed]
6. Actions minutes ran out in early November, so a later ADR allowed any builder to make the image, including emulated amd64 on the arm64 Mac. Whether valgrind runs under emulation is UNVERIFIED.
7. A macOS-only `CONDA_SUBDIR` value sat in a global mise config; its effect on Linux is UNVERIFIED.

### 2.3 Owner rulings
- 2026-11-10: Linux gets LLVM from apt, macOS from Homebrew. This task came from that ruling.
- 2026-11-10: Linux images keep conda gxx 16.2.0; the apt ruling covers LLVM only.
- Real conflict: apt cannot satisfy an exact pin (finding 2), so "apt for LLVM" and "every input hash-pinned" collide. Options considered: (A) apt latest with a recorded receipt, (B) keep the .debs, (C) the LLVM release tarball via mise `github:` with sha256, (D) Debian sid (rejected).

### 2.4 Other pieces in the private prototype
- Image shims, an MSan libc++ build script, CMake 4.4.5, extra tools (zip, unzip, pkgconf, curl, vcpkg), image checks and BOLT.
- A p2996 spec: clang-p2996 in the image, arm64 only for now, never replacing the default clang, a provenance file with commit, checksum and payload digest; MSan needs a separate libc++ built from the fork; HWASan needs a probe. Pin first `f17c8d6c`, later re-pinned to `562409c7`.

## 3. dotfiles-legacy (public; GitHub repo renamed, detached HEAD `aa4299f8`)

### 3.1 What it did [verified: read files]
- `.devcontainer/Dockerfile` (697 lines): `BASE_IMAGE=ubuntu:26.04@sha256:2260313b...`, mise installed by version, `mise-system.toml` + lock copied in, `mise bootstrap packages apply --manager apt` then `status --missing` as a drift gate.
- apt.llvm.org added by hand with fingerprint assertion (`6084F3CF814B57C1CF12EFD515CF4D18AF4F7421`), `.devcontainer/mise-system.toml:202-248` pins every `apt:clang-22`, `libc++-22-dev`, etc. to `1:22.1.8~++20260714015917+ca7933e47d3a-1~exp1~20260714135927.17`.
- `mise-system.toml:65`: `conda:gxx = { version = "16.2.0", os = ["linux/arm64"] }`; `:59,66,93` conda cmake/ninja/valgrind as `latest` (locked).
- `docker-bake.hcl` (282 lines): zstd level 19, provenance max plus SBOM, registry-tag caches for the heavy stages because a gha cache export exceeded the 1-hour Azure SAS token life.
- `.github/workflows/build-publish.yml`: matrix of amd64 and `ubuntu-26.04-arm` legs; job timeouts 10, 45, 60, 120 and 240 minutes (lines 99, 151, 297, 443, 557). A `p2996-prep` step probes `docker manifest inspect` and skips the 80-120 minute build on a hit.
- `renovate.json`: extends `github>jdx/renovate-config`; groups "image-build inputs" (Dockerfile, bake, mise-system toml); separate rule for apt.llvm.org debs (own automerging PR); own daily PR for `bloomberg/clang-p2996` HEAD with a `before 6am` schedule; custom managers for ubuntu digest, jdx/mise, gcc-latest. Dependabot only for pip (`.github/dependabot.yml`, 7-day cooldown). `gcc-sha-repair.yml` recomputes a sha after Renovate bumps a .deb.

### 3.2 What broke and why [claimed in code comments, git history confirms the PR numbers exist]
- Hard-coded LLVM target X86 broke the arm64 build after 52 minutes (#703, commit `5961be5a`, 2026-08-10).
- p2996 export shipped about 8.5 GB instead of 2.8 GB until PR #244 (`7e068904`, 2026-07-13). Docs disagree on the final size (about 500 MB in bake vs 2.8 GB uncompressed / 0.7 GB compressed in `P2996-CACHE.md`).
- `grep -q` in a pipe under `pipefail` caused SIGPIPE failures (#289).
- Exact apt pins went stale: the repo had a "llvm-apt-pin-churn" research doc and an `llvm-bump` task. Exact pin plus Renovate PR per bump is the legacy answer; it shows exact pins need a bot and a daily churn budget. [verified: renovate.json rule text]
- mise lock files made on macOS lack linux-x64 conda checksums; do not run `mise lock` on a Mac. [claimed in `P2996-CACHE.md`]
- Legacy claimed numbered suites "build RELEASED TAGS" (Dockerfile ~line 189). The private prototype observed `23.1.6~` snapshot builds on the same kind of suite. These may both be true at different times; legacy's claim holds only while the branch head equals a tag. [conflict, unverified]
- Cold base rebuild about 2.5 h, warm about 10 min (renovate.json rule text). [claimed]

### 3.3 Lessons stated in repo
`.claude/rules/local-devcontainer-first.md`: reproduce in a local container before pushing; same apt pin failed in the devcontainer but passed in a clean base container (#288).

## 4. The current dotfiles repo and a runner-image prototype

- `ray-manaloto/dotfiles` has no Dockerfile and no devcontainer. [verified: `git ls-files`]
- `python/toolchains/p2996/` (README, `mise.toml`, `src/p2996/*`) is macOS arm64 only. It builds with sccache (`SCCACHE_CACHE_SIZE=60G`), source from `refs/heads/p2996` of bloomberg/clang-p2996, four macOS 27 SDK patches. README says "hours; a rerun resumes". No Linux code path. [verified: README, mise.toml read]
- A separate, unpublished self-hosted runner prototype: base `ghcr.io/actions/actions-runner:2.338.2` (Ubuntu 24.04), `jdxcode/mise:2026.11.5` copied in, sccache 0.19.0 and uv 0.13.7 baked, sudo removed. It is a runner image, not a toolchain image: compilers come from mise per repo, installed by a "warm" step into a read-only volume. Image tags are version-pinned, not digest-pinned. Slot containers run uid 1001 with all capabilities dropped; a GCC reflection compile uses about 1.4 GB per job. [claimed]
- Owner decision 2026-11-09: public repositories run in one-job containers, private ones in VMs later.

## 5. glaze and glaze-build-setup

- `glaze` and the local `glaze-build-setup` are forks of upstream glaze. Their `.devcontainer/Dockerfile`, `devcontainer.json` and many `.github/workflows/*.yml` are upstream files, not the owner's image work. [verified: file list; contents not audited]
- The owner-built parts: hand-written `triplets/x64-linux-{gcc16,clang23,p2996}[-asan|-tsan].cmake` and presets `clang23-*`, `gcc16-*`, `p2996-*`. These consume a toolchain image that does not yet exist.
- Options raised earlier for getting clang-p2996 at commit `562409c` on Linux x86: build in CI with actions/cache keyed on the SHA ("first build ~1-2 h on a free runner", cache evicts after 7 days); build once and push to GHCR; or use the third-party `vsavkov/clang-p2996` image dated Dec 2025. No answer was recorded. [claimed]
- An x86 benchmark table used g++-14 and clang-18 and is to be redone with the three target compilers. Local p2996 at `f17c8d6`, newest `562409c` (2026-11-03). Mac numbers used GCC 16.2.0, Homebrew clang 23.1.4 and p2996 f17c8d6.

## 6. How p2996 should be built for Linux

Facts, from dotfiles-legacy `.devcontainer/Dockerfile` (stage `clang-builder-cold`, lines ~424-531) and `P2996-CACHE.md`:
- Shallow `git fetch` of one commit, out-of-tree Ninja build, install to `/opt/clang-p2996`.
- CMake flags: Release; `LLVM_ENABLE_PROJECTS="clang;lld"`; `LLVM_ENABLE_RUNTIMES="libcxx;libcxxabi;libunwind"`; ONE target backend only (X86 or AArch64, picked from TARGETARCH); `LLVM_CCACHE_BUILD=ON`; no tests, examples, benchmarks, bindings, terminfo; `CLANG_DEFAULT_CXX_STDLIB=libc++`. [verified]
- Build host compiler is distro gcc/g++ (not conda). [verified]
- Smoke test: `#include <meta>` with `-std=c++2c -freflection -freflection-latest -fexpansion-statements -stdlib=libc++ -fsyntax-only`. [verified]
- Time: 80-120 min cold, 15-30 min with warm ccache (`P2996-CACHE.md`); Dockerfile comment says about 2 h. [claimed; timeouts of 120 and 240 min in `build-publish.yml:557,297` are consistent]
- Cache: content-addressed GHCR image `p2996-<hash16>` holding only the install prefix (`FROM scratch`, about 2.8 GB raw, 0.7 GB compressed), key = hash of commit + builder image + platform + the Dockerfile stage text. A probe on hit finishes in under 30 s and passes `dev.contexts.p2996-export=docker-image://...@digest` to the main build. Only the registry tag is used as the BuildKit cache for this stage. [verified: text; hit rate not measured]
- Cadence: Renovate PR once per day before 6am, because each bump is a cold compile. [verified: renovate.json]
- Hosted-runner limits to confirm before reuse: standard runners have 4 vCPU/16 GB; a single-target Release build of clang+libc++ is likely well above 2 h cold there. UNVERIFIED for 2026 runner sizes.
- The Mac p2996 build uses sccache; legacy Linux used ccache. Switching is untested; legacy issue #82 deferred it.
- Open pin: `f17c8d6c` (legacy bake, the private prototype spec) vs `562409c7` (newest). Decide once, then let Renovate track the branch HEAD.

## 7. Claims that look wrong or unverified

1. "`mise oci build` can produce this image": it ignores apt sources, is experimental, cannot cross-build, and `brew:` entries fail. It worked for the private prototype only because LLVM came from conda and apt was limited to Ubuntu's own archive. [claimed, partly supported by the private prototype's working run]
2. "Ubuntu latest": the private prototype was on 24.04; legacy used 26.04. gcc-16 apt for 26.04 was a March 2026 pre-release snapshot (`16-20260322-1ubuntu1`), so conda gxx 16.2.0 remained the only 16.2 route at the time. [claimed, unverified]
3. "Every input hash-pinned": `conda:clangxx = latest`, `conda:cmake = latest`, `ninja = latest`, `valgrind = latest` rely on the lock file, and lock files from macOS lack linux-x64 checksums. The private prototype pinned the base by digest but apt packages by snapshot date; snapshot.ubuntu.com returned 503s under load. [claimed]
4. "cmake 4.5": the private prototype pinned 4.4.5; whether 4.5 exists as a release was not verified here.
5. GCC 17 from kayari.org (legacy amd64 only) is a personal build site; not suitable as a pinned source without mirroring. [verified: Dockerfile uses a dated .deb with sha256]
6. Both prior designs treat the image as the thing to run in a container job, but only the private prototype proved it. The legacy devcontainer image was never a job container.
7. Timing numbers in 3.2 and 6 come from comments and docs, not observed runs.

## 8. Worth harvesting

From the private prototype (private; ideas only):
- The digest-in-repo plus `inputs-<hash>` skip-if-built flow, and the container-job gotchas in 2.2.
- The apt.llvm.org and gcc-16 source facts in 2.2 and 2.3.
- The p2996 image spec in 2.4.

From `ray-manaloto/dotfiles-legacy`:
- `.devcontainer/Dockerfile` lines ~188-217 (apt.llvm.org source with fingerprint check) and ~424-531 (p2996 stage).
- `.devcontainer/P2996-CACHE.md`, `docker-bake.hcl`, `renovate.json` (custom managers, grouping, per-bot packageRules), `.github/workflows/build-publish.yml` (prep-probe pattern), `.github/workflows/gcc-sha-repair.yml`.
- `.claude/rules/local-devcontainer-first.md`.

From the runner prototype: mise copied from `jdxcode/mise:<ver>` with sccache and uv baked in, as a runner-image pattern, not as a toolchain image.
