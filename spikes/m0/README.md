# M0 spike results

One line per check in environment-standard.md section 10. The spike code
is deleted after M0; this file is kept.

## (i) The packslip and cache leg (2026-11-13)

| Check | Result | Evidence |
|---|---|---|
| Test release published as draft, upload, sign (`jdx/packslip` v1.11.4, `attest: false`), publish; tag `m0i-linux-arm64-v0.0.1-r.13.1`, titled with its artifact tag | PASS | [run 43480269574](https://github.com/ray-manaloto/cpp-standard/actions/runs/43480269574), job `publish` |
| `packslip install` with the exact `builder.yml@refs/heads/main` identity installs it | PASS | same run, step "Install it with the exact main identity" |
| A bundle signed on a branch verifies for its own identity and is refused for the `main` identity ("identity mismatch") | PASS | [run 43480472915](https://github.com/ray-manaloto/cpp-standard/actions/runs/43480472915), job `branch-sign` |
| A cache saved on the PR ref is not readable from the merge-group ref | PASS | [run 43483507903](https://github.com/ray-manaloto/cpp-standard/actions/runs/43483507903), job `mq-fetch` (PR #9) |
| The PR run's artifact downloads in the merge group by `run-id` | PASS | same run, job `mq-fetch` |
| `mise bootstrap packages status --missing` fails before bootstrap and exits 0 after it | PASS | every `mise-checks` job, for example run 43483507903 |
| Regenerating the lock on the Mac host and in an `ubuntu:26.04` container (the job now runs `ubuntu:26.10`), both mise 2026.11.8, gives identical files | FAIL with the default `minimum_release_age`; PASS with a fixed cutoff date | FAIL: run 43483507903, job `mise-checks`; PASS: [run 43484976602](https://github.com/ray-manaloto/cpp-standard/actions/runs/43484976602), job `mise-checks` (PR #12) |
| The test release and its tag are deleted | PASS | `gh release delete --cleanup-tag`, 2026-11-13 |

Findings for the M0-Linux exit review on 2026-11-16:

- **The lock is not reproducible as configured.** Only two lines differ:
  `exclude-newer` in `.mise/locks/**/uv.lock` and the sidecar digest in
  `mise.lock` that follows from it. mise's `minimum_release_age` defaults
  to `24h`, and `mise lock` passes "now minus 24h" to `uv lock
  --exclude-newer` (mise v2026.11.8 `src/backend/pipx/lock.rs:715`,
  `settings.toml:2333`). Options: a fixed cutoff date or `0s` in the
  settings (a reproducible lock, but no 24h hold-back on new releases), or
  compare the locks with that line ignored. The spike now uses a fixed
  date, later than every pinned release, and the lock regenerates
  identically; the date has to move forward with the pins.
- **uv must be a pinned tool.** Without uv on PATH, `mise lock` warns "uv
  >= 0.12.10 is unavailable" and silently leaves out the PyPI sidecars and
  the `uv` line in `mise.lock`. `.mise/conf.d/tools.toml` must pin uv.
- **The merge queue fires `merge_group` runs only when a required check
  exists.** With none, PR #8 merged with no merge-group run. D101 made the
  `ci.yml` job names required from setup step 7.
- The branch refusal was shown with `packslip verify`, which runs the same
  identity check as `packslip install`.

## (f) mise bootstrap and Renovate read `.mise/conf.d/` (2026-11-13)

| Check | Result | Evidence |
|---|---|---|
| A test Renovate run (44.239.1, mise manager, `mise.managerFilePatterns` adding `.mise/conf.d/*.toml`) opens a PR for a `conf.d` pin | PASS | [PR #17](https://github.com/ray-manaloto/cpp-standard/pull/17): `spikes/m0/f/.mise/conf.d/old.toml`, node 20.0.0 to 26.13.1; extraction found 1 file, 1 dependency |
| Control: the same configuration without the pattern, extract-only dry run (`RENOVATE_DRY_RUN=extract`) | finds nothing | its stats line: `"managers": {}, "total": {"fileCount": 0, "depCount": 0}` (local log, not kept) |
| apt.llvm.org `llvm-toolchain-resolute-23` (key fingerprint 6084 F3CF 814B 57C1 CF12 EFD5 15CF 4D18 AF4F 7421) installs `clang-23`, `clang-tools-23`, `llvm-23`, `libc++-23-dev`, `libc++abi-23-dev`, `libclang-rt-23-dev` on `ubuntu:26.10` | PASS | [run 43517812562](https://github.com/ray-manaloto/cpp-standard/actions/runs/43517812562), job `clang` (clang 23.1.6) |
| Exact `apt-toolchain-host.toml` versions on `ubuntu:26.10` (`apt-cache policy`, 2026-11-13) | recorded | `binutils` 2.47-6ubuntu1, `make` 4.4.1-3 |
| `mise config ls` loads every fragment exactly as the schema writes it | PASS by owner decision (2026-11-13), re-checked in M1a | the schema's fragments do not exist until M1a |
| `mise bootstrap packages status --missing` exits 0 in the built base | PASS by owner decision (2026-11-13), re-checked in M1a | shown in a plain `ubuntu:26.10` container in (i); the base image comes in M1a |

Findings for the M0-Linux exit review on 2026-11-16:

- **Renovate skips `.mise/conf.d/` by default.** Its mise manager matches
  only `.config/mise/conf.d/*.toml` (renovatebot/renovate
  `lib/modules/manager/mise/config-files.ts`). M1b's Renovate config needs
  `mise.managerFilePatterns: ['/(^|/)\\.mise/conf\\.d/[^/]+\\.toml$/']`.
- **The run was not an Actions job, by design.** The repository's
  workflow permissions API reports
  `"can_approve_pull_request_reviews":false` (2026-11-13), so
  `GITHUB_TOKEN` cannot open PRs, as §6 requires ("GITHUB_TOKEN never
  opens PRs"). The file plan has no Renovate workflow, so the daily
  Renovate is expected to run outside Actions; its identity and token are
  not settled in the design. Open point for M1b.
- **Owner decision (2026-11-13):** the two legs that wait on M1a (the
  schema's fragments and the built base) pass on the spike evidence, (i)'s
  clean `status --missing` with `conf.d` fragments in its `mise-checks`
  job, and M1a's first base build re-checks both.

## (h) and (c) clang-p2996 with compiler-rt (2026-11-13)

| Check | Result | Evidence |
|---|---|---|
| (h) A cold build of p2996 commit 562409c7 with compiler-rt on `ubuntu-26.04-arm` (4 CPUs, `ubuntu:26.10` container) fits the free disk with at least 10 GB spare and finishes inside 6 hours | PASS: 58.6 min (fetch 37 s, configure 9 s, build and install 3471 s); peak disk use 40,079 to 47,844 MiB (`df -B1M`) on a 145 GiB disk with 106 GiB free at the start; build tree 2,963 MiB, install 2,323 MiB (`du -sm`); packed `p2996-linux-arm64.tar.zst` 714,742,767 bytes (682 MiB) against the 10 GB `actions/cache` quota; the only toolchain built in M0-Linux (amd64 comes with M2) | [run 43509894509](https://github.com/ray-manaloto/cpp-standard/actions/runs/43509894509), job `p2996`, artifact `m0h-logs` |
| (c) Reflection with `-freflection-latest` and libc++ | PASS | same run, step "Smoke tests (M0 (c))" |
| (c) ASan reports a heap-buffer-overflow | PASS | same step |
| (c) UBSan reports a signed overflow | PASS | same step |
| (c) `--coverage` writes `.gcda` and the toolchain's `llvm-cov gcov` reads it | PASS | same step |
| (c) TSan reports a data race (`spikes/m0/g/tsan.cpp`, `-fsanitize=thread`) | PASS | local run with the run 43509894509 toolchain in `ubuntu:26.10`; not in the CI smoke step |

Findings for the M0-Linux exit review on 2026-11-16:

- **Two fixes were needed, both in the spike.** Run 1 (43491958697) built
  the toolchain but compiler-rt's arch probe found no supported targets,
  so ASan, UBSan and coverage failed to link; the likely cause is the
  probe linking against the new clang's libc++ before it exists, and
  `COMPILER_RT_DEFAULT_TARGET_ONLY=ON` fixed it. Run 2 (43501180948)
  then failed on `linux/scc.h`, which Ubuntu 26.10's kernel headers no
  longer ship; `spikes/m0/h/patches/` vendors the upstream fix
  (llvm/llvm-project 3dc4fd6), which p2996 562409c7 predates.
  The patch is needed until Bloomberg rebases. A source-built GCC on
  26.10 likely needs the same libsanitizer fix (not tested).
- **p2996 does not define `__cpp_impl_reflection`**; it reports
  reflection through `__has_feature(reflection)`. Code that tests the
  standard macro alone silently skips reflection on p2996.

## (b) and (j) gcov-mode coverage of a named module (2026-11-13)

One stand-in module (`spikes/m0/bj/src/encoder.cppm`): run-time branches,
compile-time-only helpers (a `consteval` function, a `static consteval`
member, a `constexpr` function used only in `static_assert`), and, with
reflection, a run-time function built from splices. `REFLECTION_FLAG`
makes a compiler without reflection stop with `#error`. Each run needs
100% line coverage through gcovr 7.2 with no markers and the module's row
in the report, then the uncovered-line fixture must make gcovr exit 2.

| Check | Result | Evidence |
|---|---|---|
| (b) A named module test reports 100% under gcov on GCC 16 | PASS: 15/15 lines; fixture fails at 88.2% | [run 43517812562](https://github.com/ray-manaloto/cpp-standard/actions/runs/43517812562), job `gcc` (GCC 16.2.0) |
| (j) GCC 16 with `-freflection`, `gcov-16` | PASS on the stand-in: 16/16; fixture fails at 88.9% | same run, job `gcc` |
| (j) clang 23 with libc++, `llvm-cov-23 gcov` | PASS on the stand-in: 13/13; fixture fails at 86.7% | same run, job `clang` (clang 23.1.6) |
| (j) p2996 with `-freflection-latest`, its own `llvm-cov gcov` | PASS on the stand-in: 17/17; fixture fails at 89.5% | [run 43520985746](https://github.com/ray-manaloto/cpp-standard/actions/runs/43520985746), job `p2996` (toolchain from run 43509894509) |
| Compile-time-only code is not counted | PASS on all four | the helpers add no lines to the reports |

Findings for the M0-Linux exit review on 2026-11-16:

- **The D88 fallback is not needed on the stand-in:** p2996's own
  `llvm-cov gcov` gives a 100% gate for its reflection code.
- **The base image needs `libclang-rt-23-dev`.** clang `--coverage`
  links `libclang_rt.profile.a`, which that package holds; the design's
  apt list (environment-standard.md around line 641) does not name it.
- **The stand-in proves the mechanism, not the real encoder and core
  modules** that the (j) pass line names; those do not exist until M1a,
  where they meet the same gate. Whether the stand-in result closes (j)
  is an exit-review decision. The clang leg does not use `import std`.

## (g) clang-format on `^^` and `[: :]` (2026-11-13)

| Check | Result | Evidence |
|---|---|---|
| clang-format 23.1.5 (LLVM style) keeps `^^T` unchanged | PASS | local run; files in `spikes/m0/g/` |
| clang-format keeps `[: e :]` unchanged | FAIL: it writes `[:e:]`, `typename[:r:]`, `w.template[:m:]`, `[:^^ns::x:]`; a splice starting with `::` keeps its first space (`[: ::x:]`); a second pass changes nothing | local run; files in `spikes/m0/g/` |
| p2996 builds both spellings to programs with the same result | PASS: `typename [: r :]`/`typename[:r:]`, `p.[: mx :]`/`p.[:mx:]`, `obj.[: m :]`/`obj.[:m:]` in a template, `[: ^^ns::x :]`/`[:^^ns::x:]`, `typename [: ^^box :]<int>`/`typename[:^^box:]<int>`, and `w.template [: m :]<3>()`/`w.template[:m:]<3>()` on a member template | local run with the run 43509894509 toolchain; `spikes/m0/g/` |

Findings for the M0-Linux exit review on 2026-11-16:

- **Owner decision (2026-11-13): the fallback.** Splices go between
  `// clang-format off` and `// clang-format on`, to be recorded in
  `docs/standard/build.md`, which M1a creates (environment-standard.md
  file plan). [#21](https://github.com/ray-manaloto/cpp-standard/issues/21)
  tracks upstream (llvm/llvm-project#192040) to drop the markers later.
- A `.template` splice through a dependent type
  (`obj.template [: m :]<3>()` with `obj` of type `T`) fails on p2996 562409c7 in
  both spellings ("member reference base type 'const T' is not a
  structure or union"); not a formatting difference.
