# mise-first Linux C++ toolchain images: research report

Date: 2026-11-13. mise version checked: 2026.11.7 (source commit a290bd0, shallow clone).
Offline copies: clone at `<research-cache>/repos/mise`, docs at `<research-cache>/docs/mise/` (23 files, all non-empty).

## 1. Summary and recommendation

Goal: one Linux C++ toolchain image that (a) GitHub-hosted runners build, (b) runs as a devcontainer on Apple Silicon and Linux PCs, (c) is the container for GitHub Actions Linux jobs. Base is Ubuntu 26.04. Every input is pinned by hash and bumped by Renovate or Dependabot.

Findings in plain terms:

- `mise oci build` exists and is the most mise-native route. It is experimental. It makes one image layer per tool and runs on the build host, so you build once per architecture and merge with `mise oci push --update-index`.
- Re-check of the earlier finding ("oci build ignores apt"): this was half wrong. At 2026.11.7 `oci build` DOES install `[bootstrap.packages]` entries written as `apt:` (and `apk:`). It does NOT apply `[bootstrap.apt.sources]`. So apt.llvm.org cannot be added through mise for an image. The apt step only sees the sources already in the base image.
- No official mise devcontainer feature exists. `mise generate devcontainer` writes a starter file that uses a third-party feature.
- `mise.lock` pins tool downloads (including conda packages) by checksum per platform. It does not pin apt packages.
- Renovate understands `mise.toml` tools and `mise.lock`. It does not understand `[bootstrap.*]` or `[oci] from`. Dependabot has no mise support.

Recommendation (least custom code):

1. Base stage: a tiny Dockerfile, `FROM ubuntu:26.04@sha256:...`, that adds the apt.llvm.org source and key (key fingerprint checked) and nothing else. Push it as `base` by digest. Renovate's dockerfile manager bumps the digest.
2. Toolchain image: `mise oci build --from <base>@sha256:...` with `mise.toml` holding `[tools]` (conda gxx 16.2.0, cmake 4.5, ninja, sccache, vcpkg, gcovr, and mise-pinned others), and `[bootstrap.packages]` `apt:` entries for clang/libc++ (pinned versions) and valgrind. `mise.lock` created with `mise lock --platform linux-x64,linux-arm64`.
3. clang-p2996: build in a separate workflow at a pinned commit, publish a release tarball plus checksum, consume via the mise `github:` or `http:` backend (checksum lands in `mise.lock`). Fallback: `[[oci.copy]]`.
4. Build matrix `ubuntu-26.04` and `ubuntu-26.04-arm`, then `mise oci push --update-index` (max-parallel 1) to make one multi-arch tag.
5. Use that image digest in `.devcontainer/devcontainer.json` `image` and in workflow `container.image`. Renovate's devcontainer, github-actions and dockerfile managers handle digests.
6. Fallback if `mise oci` proves too immature: a plain Dockerfile that runs `mise install --locked` in a `RUN` step (cookbook pattern, uses `mise install --system`), still pinned by digest.

Biggest risk: conda prefix relocation (see section 7, item 1). Test early: build on a runner, run `g++ --version` and compile a hello world inside the image.

## 2. Feature table

| Feature | What it does | Maturity | Source |
|---|---|---|---|
| `mise oci build/run/push` | Build OCI image from `mise.toml`, one layer per tool, own registry client (no docker needed) | Experimental (`MISE_EXPERIMENTAL=1`). Added recently; see src below | docs `dev-tools-mise-oci.md`, `cli-oci-build.md`, `cli-oci-push.md`; https://mise.jdx.dev/ |
| `[oci]` options | from, tag, workdir, user, mount_point, `[oci.env]`, `[[oci.copy]]` | Experimental | same |
| Multi-arch | Build per arch on matching host, `push --update-index` merges | Experimental, documented with `ubuntu-24.04` and `ubuntu-24.04-arm` | `dev-tools-mise-oci.md` |
| Base pin | `--from REGISTRY/IMAGE@sha256:...` | Experimental | same |
| apt packages in image | `[bootstrap.packages]` `apt:` applied in `oci build`, needs root (PR #14447) | Experimental, new | `crates/mise-oci/src/packages.rs` |
| `[bootstrap.apt.sources]` | Adds `ppa` or `uris/suites/components/key/fingerprint` to `/etc/apt/sources.list.d/mise-<name>.sources` | New (PRs #14306, #14348, Oct 2026); host use only (`mise bootstrap packages apply`), NOT used by `oci build` | `bootstrap-packages-apt.md` |
| `mise.lock` | Per-platform URL + checksum for tools; conda dependency packages; `lock --bump`; `install --locked`; `locked_require_checksum` | Stable | `dev-tools-mise-lock.md`, `dev-tools-mise-lock-reference.md` |
| conda backend | Solves and installs conda-forge packages via rattler, no conda needed; linux-64, linux-aarch64, osx-arm64 | Documented; gxx 16.2.0 exists for all three | `dev-tools-backends-conda.md`, `src/backend/conda.rs` |
| `mise generate devcontainer` | Starter devcontainer.json: image `mcr.microsoft.com/devcontainers/base:ubuntu`, feature `ghcr.io/devcontainers-extra/features/mise:1`, ext `hverlin.mise-vscode`, `postCreateCommand: mise install` | Stable, starter only; the feature is third party (last commit 2026-05-20) | `cli-generate-devcontainer.md`, `src/cli/generate/devcontainer.rs` |
| `mise generate github-action` | Generates a CI workflow that runs a task | Stable | `cli-generate-github-action.md` |
| `mise install --system` | Installs to `/usr/local/share/mise/installs`, good for devcontainers where `~` is mounted | Stable | `dev-tools-system-installs.md`, `mise-cookbook-docker.md` |
| Official images | `ghcr.io/jdx/mise` (scratch) and `-debian` (Debian 13), amd64+arm64, digest-pinnable, since 2026.9.11 | Stable | https://github.com/jdx/mise |
| mise-action | GitHub Action for mise; adds `--locked` when `mise.lock` exists (v5.2.8) | Stable | https://github.com/jdx/mise-action |
| packslip | jdx signed-release installer, image `ghcr.io/jdx/packslip` | Newer, separate | https://github.com/jdx/packslip |

Ubuntu 26.04 viability: runner images 26.04 and 26.04-arm are GA (actions/runner-images #14747); `ubuntu-latest` moves to 26.04 in Nov 2026 (#14748). Known 26.04 runner issues: #15004, #15028, #15233. `ubuntu:26.04` is on Docker Hub, multi-arch, updated 2026-11-12. apt.llvm.org has `resolute` and `llvm-toolchain-resolute-22`. mise docs show `--from ubuntu:24.04`; issue #14291 used `ubuntu:26.04`.

## 3. Code map (mise 2026.11.7, `<research-cache>/repos/mise`)

- `src/cli/oci/{mod,build,push,run,common}.rs`: CLI. `common.rs` ~75-110 `perform_build` passes files and packages from config; line 165 rejects `[bootstrap.macos.*]` defaults.
- `src/oci/builder.rs` (2497 lines): line 20 `use crate::oci::packages`; 141-178 `system_packages` / `with_system_packages`; 355-368 call `packages::build_system_packages_layer`; 395-430 tool relocation (`ToolRelocation::new`, host install path to in-image path); 585-589 `dev.mise.system.packages` annotation; line 42 `TOOL_LAYER_RELOCATION_VERSION = "2"`; 1589 `tool_layer_relocation_key`.
- `src/oci/mod.rs`: re-exports `mise_oci::*`.
- `crates/mise-oci/src/packages.rs` (1273 lines): 63 `build_system_packages_layer`; 130 `validate_host_requirements`; 160 `require_root`; 182-220 `collect_package_requests` (uses only `requests`, rejects mixed apk/apt); 222 `unpack_base_layers`; 356 `prepare_apt_install`; 409-450 `apt_install_into_rootfs` (`update` then `install -y --no-install-recommends`); 452 `prepare_apt_rootfs`; ~488 `APT_CLEAR_HOST_HOOKS`; 499-540 `apt_root_args` (`Dir=`, `sourcelist`, `sourceparts`, `--root`, `--force-not-root`); 576 `clean_apt_transients`. `ManagerPackages.options` is never read here, which is why apt sources are ignored.
- `crates/mise-oci/src/layer.rs`: 39-63 `ToolRelocation`; ~964 shebang rewrite. Only shebangs, pyvenv/python and rust homes are rewritten.
- `crates/mise-system/src/lib.rs:323`: `ManagerPackages` (manager, requests, options, disabled).
- `crates/mise-system-packages/src/{apt_sources,apt}.rs`: apt sources implementation (host path).
- `crates/mise-config/src/bootstrap.rs` (~69-71, 467-470), `bootstrap/decl.rs`: config parsing.
- `src/system/mod.rs:11`: `remove_by!("2027.10.0", "apt-legacy-keyring-cleanup")`.
- `src/backend/conda.rs` (1861 lines): ~370 `install_package` (rattler link, prefix replacement); 634 `create_bin_launcher_dir`; 812 launcher docs; 971-980 `render_unix_launcher` (`export CONDA_PREFIX={prefix}` absolute host path).
- `src/cli/generate/devcontainer.rs`: ~92-95 default image; ~99 postCreateCommand; 120 feature; 129 extension.
- Lockfile code: `lockfile.rs` / `lock_file.rs` exist under `src/`; exact lines not captured (UNVERIFIED detail).

## 4. Issues, PRs, discussions (jdx/mise unless noted)

- #14447: `oci build` apt packages need root.
- #14306, #14348: `[bootstrap.apt.sources]` and inline keys (merged 2026-10-12).
- #14291: reporter used `ubuntu:26.04` base with oci.
- No open issue found for "oci build ignores bootstrap.apt.sources". Worth filing upstream (UNVERIFIED that none exists beyond my search).
- actions/runner-images #14747 (26.04 GA), #14748 (ubuntu-latest move), #15004, #15028, #15233 (26.04 issues).
- last30days run (minimal, GitHub-only evidence): Renovate PRs bumping `ghcr.io/jdx/mise` tags in devcontainer image repos: TommyE123/docker-autoheal #179, davydehaas98/homelab #1477, bde-dev/devcontainer-images #34 and #26, immich-app/devtools #2009. Signal: people consume the official mise image and let Renovate bump it.
- Other jdx repos: mise-action v5.2.8, packslip v1.11.4, hk, pitchfork, fnox, aube-action, renovate-config, workflows.

## 5. Renovate and Dependabot coverage

Renovate (latest 44.237.2):
- `mise` manager: reads `mise.toml` `[tools]` and `tasks.*.tools`; `mise.lock` (lockedVersion, update, lockFileMaintenance via `mise lock --bump`). Lockfile refresh needs `mise` in the self-hosted `allowedUnsafeExecutions`.
- conda backend entries use the conda datasource. Remote `include = ["oci::..."]` is treated as a docker image.
- NOT covered: `[bootstrap.*]` apt version pins, `[oci] from`. Neither appears in the manager readme or `extract.ts` (grep only).
- dockerfile manager: FROM digests, `COPY --from`, `RUN --mount`, pinned `apt install pkg=version`. Good for the thin base stage.
- devcontainer manager: `image` and `features` digests. github-actions manager: SHA pins with `# vX` comment, `container:` images via docker datasource.
- jdx's config (jdx/renovate-config): `config:recommended`, `docker:pinDigests`, `helpers:pinGitHubActionDigests`, `lockFileMaintenance`, `minimumReleaseAge` 7 days.
- Gap fix: a Renovate `customManagers` regex for `[oci] from` and apt pins in `mise.toml`, or move the base into a Dockerfile (covered natively).

Dependabot:
- No `mise` ecosystem. The ecosystems page lists docker, docker-compose, devcontainers, github-actions (checked by text count on the docs page, not by reading the config schema). So Dependabot can cover Dockerfile base digest, devcontainer.json, and workflow actions, but not `mise.toml`/`mise.lock`. A `conda` mention also appears on the page but I did not read its context (UNVERIFIED).
- Recommendation: use Renovate for everything; Dependabot adds nothing for mise inputs.

## 6. Gaps and least-custom fallback

| Gap | Fallback |
|---|---|
| `oci build` ignores `[bootstrap.apt.sources]` (apt.llvm.org) | Thin Dockerfile base with the source and key, pinned by digest, passed via `--from` |
| apt pins not in `mise.lock` | Pin `apt:pkg = "version"` and pin the base digest; accept apt-level drift only inside the pinned base snapshot, or use snapshot.ubuntu.com style dated sources in the base (UNVERIFIED availability for 26.04) |
| No official devcontainer feature | Use the built image directly as `image`, no feature needed. The image already holds mise |
| clang-p2996 not a mise tool | Separate build workflow, release tarball + checksum, `github:`/`http:` backend |
| Renovate misses `[oci] from` and bootstrap | customManagers regex, or keep base in Dockerfile |
| Experimental `oci` | Dockerfile with `RUN mise install --locked` as the same-shape fallback |
| Layer digests may differ between machines | Set `SOURCE_DATE_EPOCH`; pin consumers by digest of the pushed image, not by rebuild equality |

## 7. UNVERIFIED

1. Conda tools in an OCI image. Launchers hard-code `CONDA_PREFIX=<host prefix>` and conda prefix replacement happens at install on the host. OCI relocation does not rewrite these. Likely works only if host `MISE_DATA_DIR` equals the image mount point (for example `/mise`). Not tested.
2. gxx 16.2.0 running correctly on Ubuntu 26.04 glibc with the conda sysroot: not tested.
3. Renovate not handling `[bootstrap.*]` and `[oci] from`: from readme and a grep of `extract.ts` only.
4. Dependabot details: from the docs page text only, config not read.
5. Whether `ubuntu:26.04` base plus apt.llvm.org `resolute` packages for LLVM 22 (and libc++) installs cleanly: existence confirmed, install not run.
6. Devcontainer behavior on VS Code/CLion with a mise-built image (user, workdir, PATH from `[oci.env]`): not tested.
7. Exact `lockfile.rs` line numbers.
8. mise's own renovate.json was not found (404 and no local file).
9. Whether a GitHub-hosted runner `container:` job works with this image (needs a user with write to the workspace, `node` for JS actions): not tested.
10. Apple Silicon local run needs the arm64 variant built on `ubuntu-26.04-arm`: not tested.

## 8. Tools used and failed

Ran: Bash (git clone, curl, gh, grep), Skill last30days, fnox proxy for the last30days run, Python 3.13.7.
Failed or partial:
- last30days: minimal run only (`--auto-resolve`, no host planning, runbook steps 0.45-0.75 skipped). Only GitHub returned results; Reddit, X, HN, YouTube, TikTok, Instagram, Bluesky, Web returned nothing or errored. LLM scoring failed with SSL "Missing Authority Key Identifier" (the known Python 3.13 via fnox proxy issue); I did not disable TLS.
- `gh` contents call for mise `renovate.json`: 404.
- Renovate `regex/index.md`: 404.
- Not run: codebase-memory indexing, Context7, Exa, Firecrawl (reading source and docs directly was sufficient).
- No config, plugin or settings files were changed; no commits.
