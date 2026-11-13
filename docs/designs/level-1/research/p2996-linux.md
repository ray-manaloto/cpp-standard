# clang-p2996 on Ubuntu 26.04 amd64 + arm64 images (research, 2026-11-13)

## Recommendation

1. Pin `bloomberg/clang-p2996` commit `562409c7942690d59ea470762515f88f24b16e23` (branch `p2996`, 2026-11-03). `f17c8d6c` is the older one (2026-09-24, one commit behind: `compare` says 562409c7 is "ahead", behind_by 0). Drop f17c8d6c.
2. Build it ourselves in a dedicated workflow on GitHub-hosted runners, one native leg per arch (`ubuntu-26.04` and `ubuntu-26.04-arm`), no QEMU. Do not depend on `vsavkov/clang-p2996` (third party, Ubuntu 24.04, last push 2025-12-02, far behind the pin).
3. Publish the install prefix as a content-addressed OCI artifact: GHCR `...-p2996:<commit12>-<inputhash16>` (FROM scratch, ~0.7 GB compressed), one manifest list for both arches. The key hashes commit + build recipe + builder image digest + arch. A probe step (`docker manifest inspect`) skips the build on a hit. This is the legacy design (80-120 min cold -> under 30 s on hit) and also what CppReflectionAD does with actions/cache.
4. The toolchain image `COPY --from=` the p2996 artifact into `/opt/p2996`, installs nothing on PATH by default (suffix or `/opt/p2996/bin` opt-in), so default clang is not replaced.
5. Renovate: a custom regex manager (or `git-refs` datasource, `depName=https://github.com/bloomberg/clang-p2996`, `currentValue=p2996`, `currentDigest=<sha>`) on a single `P2996_COMMIT` line; schedule it weekly or monthly (every bump is a cold ~1-2 h x 2 arch build); automerge off. Branch HEAD moves a few times a month (f17c8d6c 09-24 -> 562409c7 11-03).
6. mise: only worth it for consumers outside the image (see section 5). In the image, the GHCR artifact is the pin.

Build recipe (consistent across sources): Release; `LLVM_ENABLE_PROJECTS="clang;lld"`; `LLVM_ENABLE_RUNTIMES="libcxx;libcxxabi;libunwind"` (add `compiler-rt` only if sanitizers/MSan-libc++ are required: UNVERIFIED cost); one `LLVM_TARGETS_TO_BUILD` (X86 or AArch64 by TARGETARCH; CppReflectionAD's/our legacy arm64 failure came from a hard-coded X86, #703); `LLVM_CCACHE_BUILD=ON`; tests/examples/benchmarks off; `CLANG_DEFAULT_CXX_STDLIB=libc++`; `-DLLVM_FORCE_VC_REPOSITORY=https://github.com/bloomberg/clang-p2996` (upstream CI sets it). Use `-freflection-latest` (enables P2996 + P1036/P3096/P3394/P3491, per the `purpose`-branch README). Glaze uses `-std=c++26 -freflection -fexpansion-statements -stdlib=libc++` plus `-Wl,-rpath,/opt/p2996/clang/lib/x86_64-unknown-linux-gnu` (arm64 triple dir will be `aarch64-unknown-linux-gnu`): the rpath/runtime dir must be fixed in the artifact.

## Evidence

### 1. bloomberg/clang-p2996
- Default branch is `purpose` (README/doc branch, head `2245df6e`, 2025-06-29, "Post-Sofia update", no common ancestor with `p2996`). The development branch is `p2996`, head `562409c7942690d59ea470762515f88f24b16e23`, 2026-11-03 "Return each instance in attributes_of, similar to annotations (#364)". Repo pushed 2026-11-03. Other branches: define_enum, fixIceOnRedefEnum, fixes, issue338, p3385-port, reflect_enumerator. `gh api repos/bloomberg/clang-p2996/branches`. Tags and releases: none returned.
- Pin conflict: f17c8d6c7bfef5e02ccadcf33517fd2a53b51b6e = 2026-09-24 "Reflect using-declarator targets and enforce [expr.reflect]/7.2 (#353)"; both on branch `p2996`; 562409c7 is a descendant (compare status ahead, ahead_by 1 reported by the API for the pair, behind 0). Use 562409c7.
- Based on LLVM 21.0.0 (`cmake/Modules/LLVMVersion.cmake` on p2996: MAJOR 21, MINOR 0, PATCH 0), i.e. a 21-dev snapshot, not 22/23. Ubuntu 26.04's own LLVM is newer: the fork must stay in a separate prefix.
- Build docs: the fork has no p2996-specific build page beyond the stock LLVM README; its own CI `.github/workflows/reflection.yml` (ubuntu-latest, push to p2996/ci) installs build-essential cmake ninja clang lld python3 zlib1g-dev, then `cmake -G Ninja -S llvm -B build-llvm -DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_ASSERTIONS=ON -DLLVM_UNREACHABLE_OPTIMIZE=ON -DLLVM_ENABLE_RUNTIMES="libcxx;libcxxabi;libunwind" -DLLVM_ENABLE_PROJECTS="clang"` and `ninja cxx -j16`, with `continue-on-error: true` on the build step. Many other upstream LLVM workflows are inherited and are not p2996-relevant.

### 2. Existing prebuilt sources
- Docker Hub `vsavkov/clang-p2996`: tags `amd64` (2025-12-02, 576 MB) and `arm64` (2025-12-02, 565 MB); 3473 pulls; no multi-arch manifest tag; Ubuntu 24.04; compiler at `/opt/p2996/clang`; commit inside unknown (UNVERIFIED, predates both pins). Fine as a fallback, not a pin.
- Glaze `.github/workflows/p2996-reflection.yml` pulls that image (`vsavkov/clang-p2996:amd64`) on `ubuntu-latest`; no build, no caching, amd64 only.
- CppReflectionAD/cpp_reflection_ad: `toolchain-cache-clang.yml` + `.github/scripts/build-clang-toolchain.sh`: submodule `clang-p2996`, cache key `clang-<os>-<arch>-<sha12>-<buildinputhash12>` via `actions/cache/restore|save@v6`, built on `ubuntu-24.04` / `ubuntu-24.04-arm` / `macos-15` by choice, installs a stripped trimmed prefix to `/opt/toolchain-clang`. Release clang, RelWithDebInfo runtimes. Measured cold workflow runs (Actions API `runs`, created->updated): 2026-10-09 61.5 min and 66 min; 2026-09-23 66.7 min and 60.8 min; 2026-09-09 76.4 min. These are wall-clock of the cache workflow, success each, on hosted ubuntu-24.04 (arch of each run not recorded in the query: UNVERIFIED which leg).
- Compiler Explorer: `compiler-explorer/compiler-workflows` `build-daily-clang_bb_p2996.yml` builds `bb-p2996-trunk` daily (skipped if no commit in 7 days) on a self-hosted large x64 runner, so CE binaries are not a hosted-runner reference and are not published as tarballs we can pin by commit (UNVERIFIED whether the s3 tarballs are stable URLs).
- Other Dockerfiles/nix: yusufemresamur/docker-clang-p2996 (debian trixie, `LLVM_ENABLE_PROJECTS="clang;clang-tools-extra"` runtimes libcxx/libcxxabi/libunwind, `CLANG_COMMIT` arg), cadkin/nix-clang-p2996 (2025-02), erics118/clang-p2996-nix (2026-08), mgerhold/clang-p2996-docker-image. conda-forge: no p2996 package found (conda registry search returned nothing). No GitHub release tarballs in the upstream or the repos seen.

### 3. Build cost on hosted runners
- Measured: CppReflectionAD 61-76 min per cold build (above). Legacy local: 80-120 min cold, 15-30 min with warm ccache (`P2996-CACHE.md`, via `prior-image-work.md`; claimed, not re-measured). The single-target Release clang+lld+libc++ stack is therefore ~1-2 h on the 4-vCPU standard public-repo runners; well inside the 6 h job limit (GitHub-hosted job limit 6 h per GitHub docs, not re-fetched: UNVERIFIED for 2026).
- Disk: standard Linux runners ~14 GB free on `/` plus larger `/mnt`; a Release LLVM build tree for clang+lld+libcxx single target can exceed that unless ccache is trimmed and tests are off. Free disk by removing preinstalled toolchains or building in `/mnt` (UNVERIFIED sizes; not measured here). Installed prefix ~2.8 GB raw, ~0.7 GB compressed (legacy).
- arm64: `ubuntu-24.04-arm` exists (CppReflectionAD) and `ubuntu-26.04-arm` (legacy build-publish.yml); free for public repos, paid-minutes for private. Actions minutes were exhausted at the time of research, which makes a cold double build costly now.
- Caching: actions/cache evicts after 7 days of no access and has a repo size cap (UNVERIFIED current figures), so it is a weak home for a once-a-month artifact; GHCR content-hashed image is durable. A release asset also works but is not addressable by content hash for a Dockerfile `COPY --from`.
- ccache/sccache: legacy used `LLVM_CCACHE_BUILD=ON` with a registry/BuildKit cache; cold build of a new commit benefits only partly.

### 4. Prior local work
- `ray-manaloto/dotfiles/python/toolchains/p2996` (README read): macOS arm64 build driven by mise tasks and a uv Python package; source is always newest commit of `refs/heads/p2996` unless `--commit`; `<id>` = commit + 12 hex digest of the CMake file-API input set; sccache via launchers with PCH off; patches (`sdk-rdf-comparator.patch`, `sdk-float-math.patch`, `asan-macos27-dyld.patch`) are macOS 27 SDK-specific and not needed on Linux; "hours" build, no measured times in the README head I read (UNVERIFIED remaining sections).
- `prior-image-work.md`: legacy cache design, timeouts 120/240 min in `build-publish.yml`, Renovate once daily (too frequent), X86 hard-code arm64 failure after 52 min.

### 5. mise route
- Feasible for non-image consumers: publish `p2996-<commit12>-linux-{amd64,arm64}.tar.zst` as release assets of our own repo and use `github:ray-manaloto/<repo>[version=...,asset_pattern=...]`, or `http:` with per-platform `url`/`checksum` and `bin_path`. mise.lock records per-platform checksums for these backends (`mise lock`); I did not run it, so the exact lock format and `http:` platform-table keys are UNVERIFIED. mise registry only has `clang` (conda/asdf), nothing for p2996 (`mise registry | grep p2996`: none; mise 2026.11.7 local).
- Caveat: the tarball is built against Ubuntu 26.04 glibc/libstdc++ (libc++ own runtime, rpath `lib/<triple>`); it only works on a compatible base, so the image route stays primary.

## UNVERIFIED
- GitHub runner limits (6 h, 14 GB disk, vCPU counts, arm64 availability, cache quotas) and `ubuntu-26.04` / `ubuntu-26.04-arm` labels for 2026: taken from other repos' workflows, not GitHub docs.
- Whether the libc++ in the fork builds cleanly with Ubuntu 26.04's GCC 15/16 or its clang as host compiler.
- compiler-rt cost and whether MSan/HWASan need it.
- Exact commit inside vsavkov images; CE tarball URLs; mise `http:` lock details.
- Measured arm64 cold time (no per-arch run data pulled).

## Tools used
`gh api` (bloomberg/clang-p2996 branches, commits, compare, contents; stephenberry/glaze; CppReflectionAD; compiler-explorer/compiler-workflows; yusufemresamur), `curl` Docker Hub API, GitHub repo search, anaconda.org search (returned nothing), local `mise registry`, Read/grep of the local dotfiles README and prior-image-work.md. Not run: Exa, Context7, Firecrawl, Last30Days (time cap). No fetch of GitHub's runner docs.
