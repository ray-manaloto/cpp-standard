# External examples and facts for hash-pinned C++ toolchain images

Date of research: 2026-11-13. Scope: Linux C++ toolchain images built on GitHub-hosted runners, published to GHCR, used as local devcontainers and as the GHA job `container:`, hash-pinned, updated by Renovate or Dependabot, mise-first.

Offline copies of the docs pages cited here are under `<research-cache>/docs/external/`. Shallow clones (read only, never built or run) are under `<research-cache>/repos/`.

Evidence labels: facts marked (verified) were read from a primary page or cloned source in this session. Anything marked UNVERIFIED is in the list at the end.

## 1. Short answers

1. Ubuntu 26.04 LTS "resolute" is released (2026-04-23). The official `ubuntu` Docker image supports `ubuntu:26.04@sha256:<index digest>`, a multi-arch index digest. apt.llvm.org has a `llvm-toolchain-resolute-23` suite carrying 23.1.6 snapshot-of-branch packages.
2. For reproducible clang, the strongest option is LLVM's own release tarballs pinned by sha256 through mise's `github:` backend with `mise.lock`, or conda-forge clang 23.1.5 through mise's `conda:` backend. apt.llvm.org is a moving target and cannot pin an exact build. There is no aqua LLVM package and no dedicated mise "llvm" backend. The generic `github:`, `http:` and `conda:` backends cover it.
3. clang-p2996 has public prebuilt images (`vsavkov/clang-p2996`, separate `amd64` and `arm64` tags) and two CI caching patterns (a Docker Hub image pull in glaze, a content-hash cache in cpp_reflection_ad).
4. No single public C++ repo was found that combines all of: multi-arch push-by-digest build, Renovate with digest pins, devcontainer.json `image` pinned by digest, and `container: ...@sha256`. The closest pieces are ranked in section 5. Combine them.
5. Renovate covers mise.toml and mise.lock, Dockerfile FROM digests, devcontainer.json, GHA action SHAs, and apt package versions (in a Dockerfile only). It has no vcpkg manager. Dependabot covers docker, github-actions, devcontainers (features and lockfile only), vcpkg builtin-baseline and conda (no lockfile updates). Dependabot has no mise or apt ecosystem.

## 2. Q1: Ubuntu 26.04 LTS

- Release: 26.04 LTS "resolute", released 2026-04-23 (verified earlier in session from Ubuntu release pages; see UNVERIFIED for the exact page).
- Docker image: the official `ubuntu` repository publishes a multi-arch index for `26.04`. Pin as `FROM ubuntu:26.04@sha256:<index digest>`. Use the index digest, not a per-platform manifest digest, so one pin serves amd64 and arm64. Renovate's dockerfile manager updates tag and digest together (section 7).
- apt.llvm.org: suite `llvm-toolchain-resolute-23` exists with 23.1.6~ versions. The versions are "snapshot of the release branch" builds, so the same suite changes in place. That is the moving-build problem in the brief.
- conda-forge gxx 16.2.0 and glibc: conda-forge compiler packages target a conda sysroot glibc floor well below the glibc of Ubuntu 26.04, so the binaries run. UNVERIFIED as a measured test; no image was built.
- Valgrind: the version available in 26.04 was checked during the session. The exact version is not restated here because the number was not recorded. See UNVERIFIED.

## 3. Q2: reproducible clang

| Approach | Exact pin | Multi-arch | Renovate can bump it | Verdict |
|---|---|---|---|---|
| apt.llvm.org suite | No (moving build per suite) | yes | Only via the deb datasource on a Dockerfile `=version`; old versions disappear | Float, then record version and revision in the image label and build log |
| Ubuntu snapshot archive (snapshot.ubuntu.com) | Yes, for Ubuntu archive packages only | yes | partly | Does not cover apt.llvm.org |
| LLVM GitHub release tarballs via mise `github:llvm/llvm-project` with `asset_pattern` | Yes, `mise.lock` stores a checksum per platform | X64 and ARM64 Linux assets exist | Renovate mise manager | Recommended primary |
| mise `http:` backend with explicit URL and sha256 | Yes | per-platform URLs | custom manager needed | Fallback if the asset name pattern is awkward |
| conda-forge `clangxx` and `libcxx` via mise `conda:` backend | Yes (lockfile) | yes | Renovate mise manager (conda datasource supported) | Good, version lags upstream (clang 23.1.5 seen) |
| Floating plus recording | No | yes | n/a | Only acceptable for the nightly "latest" image |

Citations (all saved offline):
- mise lockfile and per-platform checksums: https://mise.jdx.dev/dev-tools/mise-lock.html (`mise-dev-tools-mise-lock.md`). Use `mise lock --platform linux-x64,linux-arm64` and `mise install --locked`.
- mise `github:` backend (asset_pattern, checksum, attestations): https://mise.jdx.dev/dev-tools/backends/github.html (`mise-dev-tools-backends-github.md`).
- mise `http:` backend: https://mise.jdx.dev/dev-tools/backends/http.html (`mise-dev-tools-backends-http.md`).
- mise `conda:` backend: https://mise.jdx.dev/dev-tools/backends/conda.html (`mise-dev-tools-backends-conda.md`).
- mise C++ cookbook: `mise-cookbook-cpp.md`.
- Answer to "is there a mise backend for LLVM release tarballs": not a dedicated one. The `github:` backend with `asset_pattern` is the intended route. An aqua registry LLVM package was looked for and not found (404 on the registry path).

## 4. Q3: clang-p2996 on Linux

- Public images: `vsavkov/clang-p2996` on Docker Hub, with `:amd64` and `:arm64` tags rather than one multi-arch tag. Glaze CI uses `P2996_IMAGE: vsavkov/clang-p2996:amd64`, `P2996_LIB_PATH: /opt/p2996/clang/lib/x86_64-unknown-linux-gnu`, and compiles with `-std=c++26 -freflection -fexpansion-statements -stdlib=libc++ -Wl,-rpath,...`. Source: https://github.com/stephenberry/glaze, `.github/workflows/p2996-reflection.yml` (verified in clone).
- cpp_reflection_ad (https://github.com/CppReflectionAD/cpp_reflection_ad) builds the compiler itself and caches it. Workflows `toolchain-cache-clang.yml`, `clang_prebuilt_cache.yml`, `toolchain-archive.yml`, `toolchain-test.yml`, script `.github/scripts/build-clang-toolchain.sh`, and `tools/toolchain/clang.py`. Cache key shape: `clang-${{ runner.os }}-${{ runner.arch }}-${CLANG_SHA:0:12}-${BUILD_INPUT_HASH:0:12}` so a clang commit or a build-script change invalidates it (verified).
- Build time: not measured in this session. Compiling an LLVM/clang fork from source on a 4-core hosted runner is generally an hour-scale job, which is why both projects avoid building on every run. UNVERIFIED as a number.
- Multi-arch: vsavkov publishes separate arch tags. Apple Silicon devcontainers need the `:arm64` tag or your own build on `ubuntu-24.04-arm`. Compiler Explorer also builds p2996 branches; its build recipes were not inspected, see UNVERIFIED.
- Design lesson: treat clang-p2996 as a separate, content-addressed layer (GHCR image or cache keyed by the fork commit plus build-input hash), not as part of the main toolchain image rebuild.

## 5. Q4: ranked example repos

None of these is a complete match. Rank is by usefulness to this design.

| Rank | Repo | What it shows | What to copy |
|---|---|---|---|
| 1 | https://github.com/bemanproject/infra-containers | C++ project. Toolchain images (`ghcr.io/bemanproject/infra-containers-gcc`, `-clang`) built in CI, plus `Dockerfile.fromsource` and `.github/workflows/fromsource_ci.yml` | Layout of per-compiler Dockerfiles and the from-source CI job |
| 2 | https://github.com/bemanproject/exemplar | Consumes the images as GHA matrix `container:` entries (`ghcr.io/bemanproject/infra-containers-gcc:latest`, `-clang:latest`), has vcpkg.json | Matrix of compilers as containers. Replace `:latest` with `@sha256:` |
| 3 | https://github.com/CppReflectionAD/cpp_reflection_ad | Hash-keyed cache of a self-built clang, archive and test workflows | Cache key design and the build/archive/test split |
| 4 | https://github.com/stephenberry/glaze | Uses a prebuilt p2996 clang image in CI | The invocation flags and rpath handling |
| 5 | https://github.com/wrocpp/cpp26-reflection-examples | `containers/base/Dockerfile` for a C++26 reflection base image | Dockerfile structure |
| 6 | https://github.com/devcontainers/ci | Action to build, cache (`cacheFrom`/`cacheTo` with a `:buildcache` tag) and push a devcontainer image, and run commands in it | Build-and-push step. Caveat: `eventFilterForPush` controls when it pushes |
| 7 | https://github.com/jdx/mise | `mise generate devcontainer`, `ghcr.io/jdx/mise` images (scratch and `-debian`, amd64 and arm64, from release 2026.9.11), experimental `mise oci build` | Pin the mise image by digest in the Dockerfile; use `mise install --system` so a mounted home does not hide tools |
| 8 | Renovate discussion https://github.com/renovatebot/renovate/discussions/28767 | Known pitfall with digest pinning in devcontainer.json features | See section 7 |

The other candidates from earlier searches (crunchloop/devcontainer, ff-fab/cosalette, nightona, selkies, devpod, dotfiles p2996 cache) were reviewed only at search-result depth and are not ranked. They are not C++ toolchain image builders in the sense of the brief.

Gap: no public repo was found with all four of these together: push-by-digest multi-arch, digest-pinned `image` in devcontainer.json, `container: ...@sha256` in GHA, and Renovate bumping all of them. This design will be the first composition. The pieces are individually documented below.

### Devcontainer features for mise

- `ghcr.io/devcontainers-extra/features/mise:1` (https://github.com/devcontainers-extra/features/tree/main/src/mise). This is the feature that `mise generate devcontainer` emits (verified in mise source `src/cli/generate/devcontainer.rs`). Option: `version`, default `latest`.
- `ghcr.io/atty303/devcontainer-features/mise:1`: options for version, installPath, activate, trust, install (runs `mise install`).
- `ghcr.io/jmlow/devcontainer-features/mise:0`.
- Recommendation: do not use a feature at all for the prebuilt image. Install mise in the Dockerfile from the digest-pinned `ghcr.io/jdx/mise` image, so there is one fewer unpinnable reference. Features in devcontainer.json are pinnable only in the form `registry/name@sha256:digest` (no tag plus digest), and Renovate's `docker:pinDigests` produced the wrong form (discussion 28767).

### Multi-arch build pattern (from memory of the workflows read, standard docker/build-push-action usage)

1. Matrix of native runners: `ubuntu-latest` (amd64) and `ubuntu-24.04-arm` (arm64). No QEMU.
2. Each leg: `docker/build-push-action` with `outputs: type=image,name=ghcr.io/<org>/<img>,push-by-digest=true,name-canonical=true,push=true`, upload the digest as an artifact.
3. Merge job: `docker buildx imagetools create -t ghcr.io/<org>/<img>:<tag> <digest list>`, then record the resulting index digest.
4. Set `provenance: false` (or `BUILDX_NO_DEFAULT_ATTESTATIONS`) if attestation manifests confuse the index you pin.
5. Triggers: `push` on paths, `schedule` weekly or nightly, `workflow_dispatch`.
6. Consumers pin `ghcr.io/<org>/<img>@sha256:<index digest>`; a Renovate rule bumps it when the scheduled build publishes a new tag.

This is a pattern, not a quote from one file. UNVERIFIED as a copy-paste-ready workflow from a named repo.

## 6. Q6: last30days result

Run with the `last30days:last30days` skill on "devcontainer prebuilt image ghcr renovate C++ toolchain". Python 3.13 failed TLS through the fnox proxy (Missing Authority Key Identifier), as predicted in the brief; TLS verification was not disabled. The run completed in degraded mode with GitHub and X only. Reddit returned 403. It produced no repo that beat the ranked list above, and no new C++ example with Renovate plus digest pins. Treat last30days as having contributed little here.

## 7. Q5: Renovate vs Dependabot coverage

| Item | Renovate | Dependabot |
|---|---|---|
| mise.toml | Yes, `mise` manager; supports tools via its datasources, with `mise.lock` and `lockFileMaintenance`. `pinDigests` is false by default for it. Self-hosted needs `allowedUnsafeExecutions: ["mise"]` | No mise ecosystem |
| mise.lock | Yes (as above) | No |
| Dockerfile FROM digests | Yes, `dockerfile` manager, tag and digest, `docker:pinDigests` preset | Yes, `docker` ecosystem (digest bumps supported) |
| devcontainer.json | Yes, `devcontainer` manager: `image` (docker datasource, digest pinning works) and `features` (node, python, etc. versions) | `devcontainers` ecosystem: features and their lockfile only, not the `image` field |
| GHA action SHAs | Yes, `github-actions` manager, `helpers:pinGitHubActionDigests` | Yes, `github-actions` |
| GHA `container:` and `services:` images | Yes, the github-actions manager extracts them as docker deps | Docker ecosystem does not scan workflow files for `container:` (UNVERIFIED) |
| apt packages | Only versions pinned in a Dockerfile `apt-get install pkg=ver`, through the deb datasource (via custom config) | No apt ecosystem |
| conda packages | conda datasource, reachable via the mise manager or a custom manager | `conda` ecosystem exists but does not update lockfiles |
| vcpkg builtin-baseline | No vcpkg manager (Renovate manager directory listing; readme 404; issue search empty). A regex custom manager is possible | Yes, `vcpkg` ecosystem updates `builtin-baseline` |

Sources, offline: `renovate-manager-mise.md`, `renovate-manager-devcontainer.md`, `renovate-manager-dockerfile.md`, `renovate-manager-github-actions.md`, `renovate-mise-index.ts`, `dependabot-supported-package-managers.md`. Online: https://docs.renovatebot.com/modules/manager/devcontainer/ and https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories.

Pitfalls:
- Do not apply `docker:pinDigests` blindly to the devcontainer manager. Features cannot take `name:tag@sha256`. Use a package rule that sets `pinDigests: false` for `matchDepTypes: ["feature"]` (the discussion's workaround disabled the whole manager; a depType rule is narrower, UNVERIFIED that depType matching works for this).
- Version and digest updates arrive as two PRs unless grouped. Group docker updates with a `packageRules` `groupName`.
- Renovate cannot bump an apt.llvm.org build that has been replaced; plan on rebuilding the image on schedule instead.
- Renovate regex fallback for a devcontainer `image` is documented in https://wildwolf.name/configure-renovate-update-devcontainer-images/, but the built-in devcontainer manager (2024 onward) makes it unnecessary.

## 8. Recommended composition (for the design, not a verified pattern)

- Base: `FROM ubuntu:26.04@sha256:<index>`, plus `COPY --from=ghcr.io/jdx/mise:<ver>-debian@sha256:<index> /usr/local/bin/mise ...` or the scratch tag. Renovate dockerfile manager bumps both.
- Tools: `mise.toml` plus `mise.lock` generated for `linux-x64,linux-arm64`; clang through `github:llvm/llvm-project` with `asset_pattern`; `mise install --locked --system` at build time.
- Build: native two-runner matrix, push by digest, merge job creating the index, on `push` and `schedule`.
- Consume: `.devcontainer/devcontainer.json` with `"image": "ghcr.io/<org>/<img>:<tag>@sha256:<index>"`; GHA `container: image: ghcr.io/<org>/<img>@sha256:<index>`. Renovate bumps both from the same package.
- Keep clang-p2996 as its own image or cache layer keyed by fork commit and build-input hash.

## 9. UNVERIFIED

- Exact digest values for `ubuntu:26.04`; none were recorded in this report. Fetch with `docker buildx imagetools inspect ubuntu:26.04` at build time.
- The exact Valgrind version in Ubuntu 26.04.
- That conda-forge gxx 16.2.0 runs on the 26.04 glibc (expected, never executed).
- clang-p2996 build time in minutes, and Compiler Explorer's p2996 build recipe.
- A named public repo that has a push-by-digest multi-arch workflow, digest-pinned devcontainer image and `container:` digest in one place.
- Whether Dependabot's docker ecosystem scans `container:` in workflow files.
- Whether Renovate `matchDepTypes: ["feature"]` with `pinDigests: false` behaves as intended for the devcontainer manager.
- Whether `mise oci build` is stable enough to replace a Dockerfile (docs mark it experimental).
- The multi-arch pattern in section 5 was assembled from standard docker/build-push-action practice and the workflows skimmed; it was not copied from a single verified file.
- Rows in the ranked table for repos 2 and 5 were read at file-listing depth only.

## 10. Tools used and failed

Used: `gh` CLI (repo and code search), Exa web search (ran, including this final round), Firecrawl (scrape and search for docs), Skill `last30days:last30days`, shallow git clones, curl for doc pages, local reading of the jdx/mise clone's docs.

Failed or degraded:
- `gh search code --path` unknown flag; `gh api search/code` returned 404.
- aqua LLVM registry path 404 (so none assumed).
- Renovate vcpkg readme 404 (stub deleted).
- mise docs URLs `docker.md` and `cookbook/cpp-cmake.md` 404 on the website; content taken from the local clone.
- last30days: Python 3.13 TLS failure through the fnox proxy (not bypassed), Reddit 403, a Digg flag error, so GitHub and X only.
- Context7 was not used for Renovate or devcontainer docs; the Renovate pages were fetched directly instead.
