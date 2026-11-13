# Tooling and build analysis (day-1 tool survey)

Date: 2026-11-13. Scope: which static-analysis, coverage, fuzzing, benchmark, SARIF and build tools the
cpp-standard project adopts on day 1, how each installs through mise, and whether it survives C++20 named
modules, `import std` and C++26 reflection (GCC 16.2, clang 23, Bloomberg clang-p2996).

Evidence convention: "Doc" means a primary document saved under
`<research-cache>/docs/tooling/` (file name given). "UNVERIFIED" means I did not
confirm it from a primary source in this session; the full list is in section 5.

## 1. Headline findings

1. Modules and co-compile analysis do not mix. `CMAKE_CXX_CLANG_TIDY`, `CMAKE_CXX_INCLUDE_WHAT_YOU_USE` and
   `CMAKE_CXX_CPPCHECK` run through `cmake -E __run_co_compile` per compile command (Doc:
   cmake-CMAKE_LANG_CLANG_TIDY.md, cmake-CMAKE_LANG_INCLUDE_WHAT_YOU_USE.md, cmake-CMAKE_LANG_CPPCHECK.md).
   Under modules, `compile_commands.json` entries reference `@*.modmap` files that exist only after a build
   (Doc: cmake-cxxmodules.7.md), and clang tools need clang-built BMIs passed with `-fprebuilt-module-path`
   (Doc: clang-usersmanual.md; Clang "Standard C++ Modules" page).
   Plan: run analysis as a separate mise task after the clang build, never as a CMake co-compile hook.
2. GCC BMIs (`.gcm`) are unreadable by clang tools, and plain clang has no P2996. The reflection targets
   (GCC 16, clang-p2996) therefore cannot be analysed by clang-tidy, IWYU or clangd at all. Analyse the
   non-reflection layer with clang 23, and rely on compilers, sanitizers and coverage for the reflection layer.
3. mise registry lacks most of these tools (Doc: <scratch>/mise-reg.txt), but the `conda:`,
   `pipx:`, `github:` and `aqua:` backends cover nearly all. conda-forge ships include-what-you-use 0.27 for
   linux-64 and osx-arm64, which solves the Linux "no apt source" problem.
4. SARIF is first-class: GCC, clang and cppcheck emit it, CMake 4.5 exports configure diagnostics as SARIF,
   and `github/codeql-action/upload-sarif@v4` ingests it (Doc: gh-upload-sarif.md, gh-sarif-support.md,
   gcc-diagnostic-formatting.md, cmake-CMAKE_EXPORT_SARIF.md).
5. Glaze (the downstream consumer) already has workflows we can copy rather than write: clang-tidy,
   llvm-cov coverage, sanitizers, quickfuzz, p2996 reflection, benchmarks (Doc: glaze-*.txt).

## 2. Summary table

Columns: tool | purpose | latest | mise route | macOS/Linux | modules / reflection OK? | CMake hook | gate signal | verdict.

| Tool | Purpose | Latest (as found) | mise route | macOS arm64 / Linux | Modules / reflection | CMake hook | Gate signal | Verdict |
|---|---|---|---|---|---|---|---|---|
| clang-tidy | lint, bug patterns | 23 (with LLVM) | `conda:clang-tools` or `pipx:clang-tidy` (wheel); Homebrew llvm keg; apt.llvm.org | both | Modules: only after BMIs are built, clang config only. Reflection: no (no P2996 in plain clang) | `CMAKE_CXX_CLANG_TIDY` (co-compile; avoid with modules); `run-clang-tidy -p build` | exit code, `--warnings-as-errors`, `--export-fixes` YAML | adopt (non-module + clang-module TUs only) |
| clang-format | formatting | 23 | `pipx:clang-format`, `conda:clang-format`, or hk builtin | both | works on module syntax (parser only, no BMI needed); UNVERIFIED for P2996 `^^`/`[: :]` tokens | none needed | `--dry-run -Werror` | adopt |
| include-what-you-use | include hygiene | 0.27 (conda-forge) | `conda:include-what-you-use` | both via conda | Not module aware: ignores `import`; mixed TUs risky | `CMAKE_CXX_INCLUDE_WHAT_YOU_USE` | exit code non-zero when `-Xiwyu --error` | later (non-module TUs only) |
| cppcheck | second-opinion analyser | 2.22.0 | `conda:cppcheck` (aqua/github alternative UNVERIFIED) | both | 2.22.0 tree has no module sources; named-module parsing UNVERIFIED, likely absent | `CMAKE_CXX_CPPCHECK` | `--error-exitcode`, `--output-format=sarif` | later (try on headers/non-module only) |
| ClangBuildAnalyzer | -ftime-trace aggregation | 1.6.x UNVERIFIED | `github:aras-p/ClangBuildAnalyzer` | both | reads clang `-ftime-trace` JSON; module behavior UNVERIFIED | none (add `-ftime-trace` flag) | none (report only) | later |
| Esri link-what-you-include | audits target graph vs #includes | see Doc esri-lwyu-README.md | github release / source; mise route UNVERIFIED | UNVERIFIED | modules unsupported (include based) | script over compile_commands | exit code | skip for now |
| cmake_instrumentation | build timing/data | CMake 4.5.0 (2026-11-12), data v1.2 | cmake via mise (aqua/github) | both | compiler-agnostic | `cmake_instrumentation()` + preset/api query | JSON data, no gate | adopt (report only) |
| CMAKE_EXPORT_SARIF | configure diagnostics as SARIF | CMake 4.5 | same | both | n/a | `CMAKE_EXPORT_SARIF=ON` | SARIF file for upload | adopt |
| Compiler SARIF | warnings as SARIF | GCC 16 `-fdiagnostics-add-output=sarif:file=`; clang `-fdiagnostics-format=sarif` (unstable) | compilers | both | works with modules | `CMAKE_CXX_FLAGS` in a preset | upload to code scanning | adopt GCC; clang later |
| GitHub code scanning upload | PR annotations | `upload-sarif@v4` | action | CI | n/a | n/a | alerts, 10 MB gz limit | adopt |
| Preset features (schema 10-13) | CMake presets | schema 13 | cmake 4.5 | both | n/a | hand-written `CMakePresets.json` | n/a | adopt |
| libFuzzer | in-process fuzzing | with clang | compiler | both (macOS needs Homebrew LLVM, Apple clang lacks it) | works; clang only | `-fsanitize=fuzzer` | crash = failure | adopt |
| AFL++ | coverage-guided fuzzing | UNVERIFIED | not in mise registry; conda/apt/brew UNVERIFIED | Linux-first | n/a | afl-clang-fast wrapper | crash | later |
| FuzzTest | property tests + fuzz | Doc fuzztest-quickstart-cmake.md | vcpkg port UNVERIFIED; CMake FetchContent | Linux + clang only | n/a | `fuzztest_setup_fuzzing_flags()` | crash | skip day 1 |
| google/benchmark | microbenchmarks | vcpkg port `benchmark` | vcpkg | both | works with `import std` UNVERIFIED | `find_package(benchmark)` | none (trend only) | adopt |
| nanobench | single-header bench | vcpkg `nanobench` | vcpkg | both | header, include-based | `find_package` | none | later |
| gcovr | gcov report/gate | 8.x UNVERIFIED | `pipx:gcovr` or `conda:gcovr` | both | GCC modules + gcov UNVERIFIED | none | `--fail-under-line 100` | adopt (GCC) |
| llvm-cov | clang coverage | with LLVM 23 | Homebrew llvm / apt.llvm.org / conda | both | works with modules (instrumented per TU) | `-fprofile-instr-generate -fcoverage-mapping` | `llvm-cov report` plus script gate; `export` JSON/lcov | adopt |
| clang static analyzer / scan-build | path-sensitive analysis | with LLVM | LLVM | both | modules: UNVERIFIED | `scan-build cmake --build` | exit code / SARIF | later |
| CodeChecker | analyser aggregator | UNVERIFIED | `pipx:codechecker` | both | inherits clang-tidy limits | uses compile_commands | exit code | later |
| Hardening flags | `_GLIBCXX_ASSERTIONS`, `_LIBCPP_HARDENING_MODE` | n/a | n/a | both | compatible | compile definitions in preset | runtime abort | adopt |
| hk built-in C++ linters | pre-commit/CI hook runner | see Doc hk-builtins.md | `aqua:jdx/hk` / mise native | both | per linter | none | exit code | adopt (clang-format, cmake-format, shellcheck etc.) |
| compile_commands.json | tool input | CMake | built in | both | modmap caveat | `CMAKE_EXPORT_COMPILE_COMMANDS=ON` | n/a | adopt |
| CTest JUnit | test report | CTest `--output-junit` | cmake | both | n/a | `ctest --output-junit` | test result | adopt |
| mold / lld | fast linkers | mold 2.x UNVERIFIED | `aqua:rui314/mold` / `conda:mold`; `conda:lld` | mold: Linux only (macOS support dropped upstream, UNVERIFIED); lld both | n/a | `-fuse-ld=` | n/a | adopt lld; mold Linux only |
| Valgrind | memcheck | UNVERIFIED | `conda:valgrind` (linux only) | Linux only (no macOS arm64) | n/a | CTest memcheck | exit code | adopt (Linux) |
| sccache | compiler cache | see project | `aqua:mozilla/sccache` | both | modules caching UNVERIFIED | `CMAKE_CXX_COMPILER_LAUNCHER` | n/a | adopt |

## 3. Per-tool notes

### 3.1 clang-tidy

- Does: bug-pattern and style checks. Run as `run-clang-tidy -p <build>`; CMake can also co-run it with
  `CMAKE_CXX_CLANG_TIDY` (Doc: cmake-CMAKE_LANG_CLANG_TIDY.md).
- Install: `conda:clang-tools` or `pipx:clang-tidy` (mise registry dump: <scratch>/mise-reg.txt).
  Homebrew `llvm` keg or apt.llvm.org match the compiler version, which avoids header skew.
- Modules: `compile_commands.json` lists `@*.modmap` response files that only exist after building (Doc:
  cmake-cxxmodules.7.md). clang-tidy then needs `-fprebuilt-module-path=<bmi dir>` (Doc: clang-usersmanual.md).
  CMake's own co-compile hook runs with GCC flags in the GCC presets, which clang-tidy cannot parse; use it
  only in the clang-23 preset, or better run a dedicated mise task after the build.
- Glaze runs clang-tidy in CI (Doc: glaze-.github_workflows_clang-tidy.yml.txt); copy its check selection.
- Gate: nonzero exit with `WarningsAsErrors`; `--export-fixes` writes YAML (not SARIF; convert with a
  community converter, UNVERIFIED).
- Verdict: adopt on clang-23 non-reflection targets.

### 3.2 clang-format

- Does: formatting. Needs no BMIs; it only parses. Glaze's `.clang-format` is a reusable base (Doc:
  glaze-.clang-format.txt).
- hk ships a built-in step (Doc: hk-builtins.md) and a mise integration (Doc: hk-mise_integration.md), so no
  glue is needed.
- Reflection syntax (`^^x`, `[: e :]`) handling in the current clang-format is UNVERIFIED.
- Verdict: adopt.

### 3.3 include-what-you-use

- Does: suggests include add/remove. CMake hook `CMAKE_CXX_INCLUDE_WHAT_YOU_USE` (Doc:
  cmake-CMAKE_LANG_INCLUDE_WHAT_YOU_USE.md); upstream README in iwyu-README.md.
- Install: `conda:include-what-you-use` (0.27 for linux-64 and osx-arm64). Whether conda's build matches the
  Homebrew/apt clang 23 headers is UNVERIFIED; IWYU must be built against the same LLVM major as the clang
  whose resource dir it uses.
- Modules: IWYU parses with clang and does not understand `import`; third-party summaries state it ignores
  imports and may suggest removing includes in mixed TUs (bigcpp.com tooling page; secondary source). I did not
  find an upstream issue number in this session.
- Alternative that needs no extra tool: clang-tidy `misc-include-cleaner`, which glaze uses.
- Verdict: later; start with `misc-include-cleaner`.

### 3.4 cppcheck

- Does: independent analyser. `--output-format=sarif` exists in tags 2.17, 2.18 and 2.22 (checked in source).
  CMake hook `CMAKE_CXX_CPPCHECK` (Doc: cmake-CMAKE_LANG_CPPCHECK.md); manual in cppcheck-manual.md.
- Install: `conda:cppcheck`.
- Modules: the 2.22.0 source tree contains no module-handling code (only unrelated "modulo" checker docs), so
  `export module` / `import` parsing is probably absent. No cppcheck ticket was found in two search attempts.
  UNVERIFIED.
- Verdict: later; try on header-only/non-module code, expect noise.

### 3.5 ClangBuildAnalyzer and -ftime-trace

- Does: aggregates `-ftime-trace` JSON from clang into top-N slow headers/templates. Report only, no gate.
- Install: `github:aras-p/ClangBuildAnalyzer` (release assets not verified). Version UNVERIFIED.
- Clang-only: GCC has `-ftime-report` instead. Module BMI build time attribution UNVERIFIED.
- Verdict: later; add `-ftime-trace` to the clang-23 preset first (zero cost).

### 3.6 Esri link-what-you-include

- Does: audits whether a target's link graph matches the `#include`s in its sources (Doc:
  esri-lwyu-README.md). Not the same as CMake `LINK_WHAT_YOU_USE`, which is ELF-only and runs `ldd -u -r`
  (Doc: cmake-LINK_WHAT_YOU_USE.md, cmake-CMAKE_LINK_WHAT_YOU_USE.md).
- Include-based, so modules are out of scope; macOS support UNVERIFIED.
- Verdict: skip.

### 3.7 CMake instrumentation and SARIF export

- `cmake_instrumentation` (Doc: cmake-cmake_instrumentation.md, cmake-cmake-instrumentation.7.md): records
  timing/data per build step, data version 1.2 in 4.5. Compiler-agnostic. Adopt as report-only.
- `CMAKE_EXPORT_SARIF` (Doc: cmake-CMAKE_EXPORT_SARIF.md): covers CMake configure diagnostics only, not
  compiler warnings.
- CMake 4.5 `warnings` preset object and schema 13 are in Doc cmake-release-4.5.md and cmake-cmake-presets.7.md.
- `import std` is supported for C++20 and newer in CMake 4.x (Doc: cmake-release-4.*.md, cmake-cxxmodules.7.md).

### 3.8 Compiler SARIF and GitHub upload

- GCC: `-fdiagnostics-format=sarif-file` and `-fdiagnostics-add-output=sarif:file=...` (Doc:
  gcc-diagnostic-formatting.md). Clang: `-fdiagnostics-format=sarif`, marked unstable (Doc: clang-usersmanual.md).
- Upload: `github/codeql-action/upload-sarif@v4`, needs `security-events: write`, 10 MB gzip cap (Doc:
  gh-upload-sarif.md, gh-sarif-support.md).
- Verdict: adopt GCC SARIF first; it exists for the module + `import std` build because it is the compiler.

### 3.9 Preset features

Schema 13 (CMake 4.5) is already the project baseline. Features to use: `include` for layering, `$penv{}` and
`$env{}` macros, `condition`, `workflowPresets`, `warnings`, `errors`, `debug`. See Doc cmake-cmake-presets.7.md.
Hand-written layered presets, no generator.

### 3.10 Fuzzing

- libFuzzer: ships in clang; macOS requires Homebrew LLVM (Apple clang lacks the runtime). Glaze's harness
  pattern (libFuzzer plus fallback `main`) is in Doc glaze-fuzzing_CMakeLists.txt and
  glaze-.github_workflows_quickfuzz.yml.txt. Adopt.
- AFL++: not in the mise registry; conda, Homebrew and apt availability UNVERIFIED. Later.
- FuzzTest: Linux and clang only (Doc: fuzztest-quickstart-cmake.md). Skip day 1.

### 3.11 Benchmarks

- Glaze uses its own `bencher` library plus comparison libs (Doc: glaze-benchmarks_CMakeLists.txt.txt,
  glaze-.github_workflows_benchmark.yml.txt). Which vcpkg ports exist: checked via the vcpkg tree listing
  (<scratch>/vcpkg-ports.txt, 2919 ports); exact port names `benchmark` and `nanobench` should be reconfirmed
  before pinning. Recommendation: google/benchmark as default, nanobench optional.

### 3.12 Coverage: gcovr and llvm-cov

- GCC: `gcovr --fail-under-line 100`; llvm-cov for clang using `-fprofile-instr-generate -fcoverage-mapping`.
  Glaze has an llvm-cov based `code-coverage.cmake` and workflow (Doc: glaze-.github_workflows_code_coverage.yml.txt).
- Install: `pipx:gcovr` or `conda:gcovr`; llvm-cov comes with the LLVM install.
- gcov reading of GCC module units is UNVERIFIED; llvm-cov threshold gating needs a small script over
  `llvm-cov export -summary-only` JSON (UNVERIFIED that no ready action exists).
- Verdict: adopt both.

### 3.13 Static analyzer, scan-build, CodeChecker

- Path-sensitive checks come from the clang static analyzer; `scan-build` wraps the build, `CodeChecker`
  (`pipx:codechecker`) wraps compile_commands and gives a gate plus SARIF output. All are clang-based so they
  inherit the module limits of 3.1. UNVERIFIED on named modules. Verdict: later.

### 3.14 Hardening flags

`_GLIBCXX_ASSERTIONS` (libstdc++) and `_LIBCPP_HARDENING_MODE` (libc++) are compile definitions; set them in
the debug/test presets per standard library. Exact macro values for libc++ 23 are UNVERIFIED. Note they must
be set consistently for `import std` BMI builds, because the std BMI captures macros at build time (inference
from module semantics, UNVERIFIED).

### 3.15 hk, compile_commands, CTest, linkers, Valgrind, sccache

- hk built-in linters and mise integration: Doc hk-builtins.md, hk-mise_integration.md. Use hk for
  clang-format, cmake-format (`pipx:cmakelang`), shellcheck-type hooks.
- `CMAKE_EXPORT_COMPILE_COMMANDS` (Doc: cmake-CMAKE_EXPORT_COMPILE_COMMANDS.md): honoured by Ninja; modmap
  caveat above.
- CTest JUnit: `ctest --output-junit report.xml` (CMake built in).
- lld via `conda:lld`; mold on Linux only (macOS status UNVERIFIED).
- Valgrind: `conda:valgrind` is Linux-only; there is no macOS arm64 Valgrind. Sanitizers (ASan, UBSan, TSan)
  cover macOS (glaze workflow: glaze-.github_workflows_sanitizers.yml.txt).
- sccache: `aqua`/`github` backend; module build caching behaviour is UNVERIFIED (BMI-producing compiles use
  unusual outputs).

## 4. Day-1 tools we might have missed (one line each)

- ABI checking: `libabigail` (abidiff), conda, Linux only. Later.
- SBOM: `syft` or CMake/vcpkg SPDX output; vcpkg can emit an SBOM. Later.
- Reproducible builds: `-ffile-prefix-map`, `SOURCE_DATE_EPOCH`, `-Wdate-time`. Adopt (just flags).
- Dependency scanning: `osv-scanner` or `trivy` against vcpkg manifest; Dependabot has no vcpkg support
  (UNVERIFIED). Later.
- vcpkg license check: vcpkg records licenses in port copyright files; a script over `vcpkg_installed`. Later.
- `include-cleaner` through clang-tidy and `clangd` (clangd modules support is experimental:
  clangd issue 1293, llvm-project issue 181770). Editor only.
- `cmake-format`/`cmakelang` (`pipx:cmakelang`) for CMake lists. Adopt via hk.
- `actionlint` and `zizmor` for workflows. Adopt via hk/mise.
- Doxygen or Standardese for docs. Later.
- `ccache` is the alternative to sccache; not both.

## 5. UNVERIFIED list

1. cppcheck handling of `export module` / `import std` (only a source-tree absence check was done).
2. IWYU behaviour on modules (secondary source only; no upstream issue number found) and conda IWYU 0.27
   compatibility with Homebrew/apt clang 23.
3. clang-format on P2996 reflection tokens.
4. ClangBuildAnalyzer latest version, release assets and module behaviour.
5. Esri lwyi mise route and macOS support.
6. gcov on GCC module units; llvm-cov gate script approach.
7. scan-build and CodeChecker on named modules.
8. libc++ hardening macro values for 23; interaction with `import std` BMI.
9. mold on macOS; Valgrind version.
10. AFL++ install routes (conda, Homebrew, apt).
11. sccache caching of module/BMI compiles.
12. Latest versions for gcovr, mold, Valgrind, AFL++, ClangBuildAnalyzer (not looked up).
13. Exact vcpkg port names for benchmark libraries.
14. Whether Dependabot supports vcpkg.

## 6. Tools used and failed

Ran: Bash (gh api, git trees API, mise registry dump, pandoc conversion), Exa web search, Firecrawl developer
search. Docs saved under <research-cache>/docs/tooling/.

Failed or poor: `gh search issues` (too noisy, replaced by Exa/Firecrawl); `gh api .../contents/ports`
(capped at 1000 entries, replaced by git trees API); hk `Builtins.pkl` fetch (empty, replaced by `pkl/builtins`
directory listing); a malformed cppcheck GitHub search query; Exa searches for cppcheck and IWYU module issue
numbers returned only generic module pages (no tickets).
