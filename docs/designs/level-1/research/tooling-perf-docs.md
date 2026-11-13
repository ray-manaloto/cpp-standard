# Tooling research: performance/profiling and docs/diagrams (cpp-standard)

Date: 2026-11-13. Host used for local checks: Apple Silicon Mac, macOS 27.2.1, Homebrew LLVM/clang 23.1.5, Homebrew GCC 16.2.0, mise 2026.11.7, SIP enabled, no sudo.
Offline copies of key sources: `<research-cache>/docs/perf-docs/`. Shallow clones (not built): `<research-cache>/repos/{mrdocs,clang-uml}` (mrdocs `2d29928`, clang-uml `ff9ffdb`).

Legend: V = verified by me this session (command run or source read); S = from a cited web/GitHub source; U = unverified (also listed at the end).

---

## 0. Headline findings

1. mise has no short-name registry entries for valgrind, heaptrack, bpftrace, uftrace, perf, hotspot, tracy, samply, bloaty, doxygen, graphviz, plantuml, mrdocs, clang-uml (V). Use `github:` / `aqua:` / `conda:` / `npm:` / `pipx:` backends where a release asset exists, otherwise apt (Linux container) or brew (macOS). Table in A.7.
2. Valgrind does not run on Apple Silicon or macOS 27. Upstream: macOS supported only up to 13 (amd64). Current release 3.28.0 (S).
3. Headless `xcrun xctrace record` works on this Mac without sudo for a self-built binary, with both the "CPU Counters" and "Time Profiler" templates; `xctrace export --toc` and `--xpath` return XML (V).
4. LeakSanitizer works on macOS 27 arm64 with Homebrew clang 23 (V). GCC 16.2 `-fsanitize=address` compiles, but a run with `detect_leaks=1` hung over 100 s (V observation, not diagnosed). Use clang for macOS sanitizers.
5. BOLT is Linux ELF only (S: LLVM issue #72205). Homebrew LLVM 23.1.5 has no `llvm-bolt` (V).
6. ClangIR: Homebrew clang 23.1.5 lists `-fclangir`/`-emit-cir` but fails with "clang IR support not available, rebuild clang with -DCLANG_ENABLE_CIR=ON" (V). MLIR tools ship but ordinary C++ builds produce no MLIR.
7. mrdocs has no C++20 module handling in source and has an open module bug (#1142). clang-uml handles named modules, but its LLVM must match the compiler that built the BMIs; Homebrew clang-uml 0.6.3 depends on `llvm@22` (V), not clang 23.
8. Neither mrdocs nor clang-uml parses P2996 `^^` syntax with stock LLVM. The Bloomberg `p2996` branch is LLVM 21.0 based (V).
9. For CI regression tracking on shared runners, gate on deterministic instruction counts (callgrind/cachegrind `Ir`, CodSpeed instrumentation) or same-job interleaved A/B, not absolute wall time.

---

## Part A: performance and profiling

### A.1 Mac vs Linux equivalents

| Need | Linux (x86_64, containers, GHA) | Apple Silicon (macOS 27) | Gap / note |
|---|---|---|---|
| Sampling CPU profiler | perf, hotspot (GUI), samply | xctrace Time Profiler (V), `sample` (V present), samply (S) | Good parity. samply is the one cross-platform tool. |
| HW counters | `perf stat` | xctrace "CPU Counters" template (V recorded headless); kperf/kpc via lemire/counters or mperf (S; root, private API) | macOS counters: Instruments or private API only. |
| memcheck | Valgrind memcheck | clang ASan/UBSan + LSan (V), `leaks --atExit` (V), MallocStackLogging + `malloc_history`, Guard Malloc | No memcheck-style uninitialised-read detector on Mac (MSan on macOS U). |
| Helgrind / DRD | Valgrind | clang TSan | |
| Cachegrind / Callgrind | Valgrind | none | Biggest gap; use Linux container/CI. |
| Heap profiling | massif, DHAT, heaptrack | xctrace Allocations, `leaks`, `heap`, `vmmap`, `footprint`, `malloc_history` (V present) | heaptrack Linux only (no macOS asset found). |
| Dynamic tracing | bpftrace, uftrace | dtrace (V: non-root says "DTrace requires additional privileges"; SIP on) | See A.4. |
| Instrumented zones/frames | Tracy | Tracy (macOS client zip exists) | Source instrumentation. |
| Static throughput | llvm-mca, OSACA, uiCA | llvm-mca (`-mcpu=apple-m4`/`apple-m5` accepted, V) | uiCA Intel x86 only. |
| Post-link layout | llvm-bolt (ELF) | none | |
| PGO | clang + llvm-profdata | same (V present) | OS independent. |
| Binary size | bloaty, llvm-size | llvm-size (V present) | |

### A.2 Linux profilers

| Tool | Purpose | Latest | mise route | macOS arm64 | Linux | CI-usable | CMake/CTest | Verdict |
|---|---|---|---|---|---|---|---|---|
| perf | sampling + HW counters | kernel-tied (`linux-tools-*`) | none; apt | no | yes | partly (A.3) | none; wrap in a script | adopt (Linux dev + opt-in CI) |
| Valgrind | memcheck, callgrind, cachegrind, massif, DHAT, helgrind | 3.28.0 (3.27.0 2026-04-20) | none (`conda:valgrind` no versions, V); apt | no | yes (x86_64, arm64) | yes, no special perms | `ctest -T memcheck` with `MEMORYCHECK_COMMAND` (U for 4.5 specifics) | adopt (memcheck + callgrind in Linux CI) |
| heaptrack | fast heap profiler | GitHub tag v1.3.0 (2021); `github:KDE/heaptrack` lists 1.2.0 | `github:KDE/heaptrack` (assets unusable, U); apt | no | yes | yes (LD_PRELOAD) | none | later |
| bpftrace | eBPF scripts | v0.27.1 (2026-10-24) | `github:bpftrace/bpftrace` (V resolves; raw `bpftrace-x86_64`/`-aarch64`) | no | yes | needs root/CAP_BPF and BTF; poor in containers/GHA | none | later |
| uftrace | function-call tracer | v0.20 (2026-08-30) | none (V: `github:` no versions); apt/build | no | yes | yes if built with instrumentation flags | none | later |
| Tracy | zone/frame/alloc profiler | 0.15.0 (2026-11-05) | `github:wolfpld/tracy` (V); vcpkg `tracy` 0.15.0 (V) | yes | yes | client yes; headless `tracy-capture` (S) | upstream CMake target, `TRACY_ENABLE` (S) | adopt, later phase, opt-in flag |
| hotspot | GUI for perf.data | v1.6.0 (2026-02-27) | `github:KDAB/hotspot` (V; release assets are libs/debuginfo only) | no | GUI | no | none | skip for CI |

### A.3 perf in containers and on GitHub runners

- Docker's default seccomp profile blocks `perf_event_open` (S: Docker seccomp docs, saved docker-seccomp-perf.txt). Needs `--cap-add=PERFMON` (kernel >= 5.8) or `SYS_ADMIN` plus a relaxed seccomp profile. `kernel.perf_event_paranoid` is a host-global sysctl and cannot be set from an unprivileged container. Exact behaviour on the Ubuntu 26.04 kernel is U.
- perf version must match the host kernel; container installs often warn (U).
- GHA hosted Linux: runner-images #4974 "perf_event_open may not work, returning EPERM" (S, closed); workaround `sudo sysctl -w kernel.perf_event_paranoid=-1`. On hosted ARM runners hardware events record silently with no samples while `cpu-clock` works (S: runner-images #11689). Whether x64 hosted VMs expose HW counters: U. Plan for `cpu-clock` only.
- Runner labels (S, runner-images README): `ubuntu-26.04`, `ubuntu-26.04-arm`, `ubuntu-24.04`/`ubuntu-latest`, `macos-26` (= `macos-latest`, arm64), `xcode-27` preview. macOS 14 images retired 2026-11-02. macOS 27 on GHA exists only as the preview image.
- Recommendation: perf locally in a privileged dev container and in an opt-in CI job; gating CI uses callgrind counts.

### A.4 Valgrind and Apple-side details

Valgrind 3.28.0 (S: valgrind.org news): macOS up to 13 amd64 only; `ms_print --peak-only` is new for CI. `--error-exitcode=N` fails tests. GCC 16/clang 23 DWARF 5 and AVX-512/APX instruction coverage: U, test with project binaries. Do not combine with sanitizers or static linking.

Apple, verified on this Mac:
- `xctrace` 27.2 (27B52). Templates include Activity Monitor, Allocations, App Launch, CPU Counters, CPU Profiler, Leaks, Logging, Network, Power Profiler, Processor Trace, Swift Concurrency, System Trace, Time Profiler (V `xctrace list templates`). `xcrun xctrace record --template 'Time Profiler' --time-limit 3s --launch -- ./bin` and the CPU Counters template worked without sudo (V). `xctrace export --toc` and `--xpath` on `time-profile` worked (V). CPU Counters defaults to guided mode; stable raw counter export is U. Man page: xctrace-man.txt. Hosted macOS runner PMU access: U.
- `leaks --atExit -- ./bin` found "1 leak for 1280 total leaked bytes" (V). `sample`, `malloc_history`, `vmmap`, `heap`, `footprint`, `spindump` present (V).
- clang 23 ASan+LSan on macOS arm64: leak reported (V). Old advice that LSan fails on arm64 macOS (S: LLVM discourse) no longer matches macOS 27 here.
- dtrace exists; non-root run prints SIP warning and "requires additional privileges" (V). Root behaviour U. Not part of the project flow.
- samply 0.13.1 (V: `github:` and `aqua:` list 0.12.0, 0.13.1; assets for aarch64-apple-darwin and linux). Works on macOS/Linux/Windows; Linux needs `perf_event_paranoid` lowered; macOS cannot profile signed system binaries (S: README). Verdict adopt.
- Apple counters from code: lemire/counters (kpc on macOS) and mperf (S: root, private kperf/kperfdata; 2 fixed + 8 configurable counters). Local micro-benchmark use only.

### A.5 Codegen analysis

| Tool | Purpose | Latest / source | mise route | OS | CI | Verdict |
|---|---|---|---|---|---|---|
| llvm-mca | static pipeline model | LLVM 23.1.5 (V) | ships with LLVM | both | yes, deterministic | adopt |
| OSACA | throughput/critical path | PyPI 0.7.1 (V) | `pipx:osaca` (V) | both | yes | later |
| uiCA | accurate x86 throughput | last commit 2024-01-14; Intel SNB..RKL | none | x86 | n/a | skip |
| BOLT | post-link layout | in LLVM; bolt packages on apt.llvm.org U | none | Linux ELF | needs perf/LBR | later (Linux release builds) |
| PGO (clang) | `-fprofile-generate`, `llvm-profdata`, `-fprofile-use` | clang 23 | LLVM | both | yes | adopt, later phase |
| PGO (GCC) | gcda profiles | GCC 16.2 | n/a | both | yes | later |
| -Rpass + opt-viewer | optimisation remarks | `opt-viewer.py`, `opt-diff.py`, `opt-stats.py` in `/opt/homebrew/opt/llvm/share/opt-viewer` (V) | n/a | both (PyYAML, Pygments) | yes | adopt |
| -ftime-trace | compile-time flamegraph | clang | n/a | both | yes | adopt |
| bloaty | size by section/symbol | v1.1 (2020) (V gh) | `github:google/bloaty` (no verified binary, U); `aqua:` errors (V) | both | yes | later; start with `llvm-size`/`llvm-nm --size-sort` |
| llvm-objdump counts | instruction mix per function | LLVM | n/a | both | yes | adopt (small script) |
| perf annotate | per-instruction samples | perf | n/a | Linux | local | adopt (Linux) |

llvm-mca (V, LLVM 23.1.5): `llc -mcpu=help` lists `apple-m1`..`apple-m5`, `apple-a7`..`apple-a19`, and `znver1`..`znver6`. `clang++ -O2 -S t.cpp` then `llvm-mca -mcpu=apple-m4 -iterations=100 t.s` ran. It printed Dispatch Width 6 for both apple-m4 and znver5, which looks approximate; the guide says results depend on the quality of LLVM scheduling models (S: llvm-mca-guide.txt). Cross target works (`--target=x86_64-linux-gnu -S`, then `-mcpu=znver5`). Use `# LLVM-MCA-BEGIN/END` markers. No CMake integration; wrap in a mise task.

BOLT: Linux ELF only (bolt-macos-issue-72205.md). Needs LBR or no-LBR mode; hosted VMs without PMU likely cannot produce LBR profiles (U).

ClangIR/MLIR realism (V): CIR disabled in Homebrew clang 23.1.5. apt.llvm.org build U. MLIR metrics from ordinary C++ builds are not possible. Realistic per-function measures: instruction count and size via `llvm-objdump`, llvm-mca IPC/port pressure, `-Rpass`/`-Rpass-missed` and `-fsave-optimization-record`, IR instruction counts from `-emit-llvm`, `-ftime-trace`, `llvm-size`/bloaty, and on Linux perf annotate.

### A.6 Benchmark regression tracking in CI

| Tool | Latest | C++ support | Runs where | Noise handling | mise | Verdict |
|---|---|---|---|---|---|---|
| github-action-benchmark | v1.22.2 (2026-09-15) | `googlecpp`, `catch2`, custom (S: gab-readme.md) | any runner; gh-pages charts; `alert-threshold`, `fail-threshold` | thresholds only | GitHub Action | adopt first |
| Bencher | v0.6.16 (2026-10-31) | Catch2, Google Benchmark adapters, BMF JSON (S) | cloud or self-hosted | statistical thresholds | `github:bencherdev/bencher` (V); `aqua:` errors | later |
| CodSpeed | codspeed-cpp v2.4.0 (2026-06-04); runner v5.6.3 | Google Benchmark only (S) | instrumentation on `ubuntu-latest`; walltime on macro runners such as `codspeed-macro-x64-ryzen-9950x-ubuntu-24-04`, `codspeed-macro-arm64-graviton-ubuntu-22-04` (S) | simulated CPU (deterministic) or dedicated hosts | not checked | later; SaaS, pricing U |
| hyperfine | registry `aqua:sharkdp/hyperfine` (V) | CLI timing | local/CI | warmups, stats | yes | adopt for ad-hoc A/B |

Rules for noisy shared runners: never gate on absolute wall time on `ubuntu-latest`/`macos-latest`; gate on callgrind `Ir` or same-job interleaved baseline-vs-PR runs with many repetitions (Google Benchmark `--benchmark_repetitions` + `compare.py`); keep wall-time trends for a dedicated machine. vcpkg ports (V): benchmark 1.9.5, nanobench 4.6.0, catch2 3.16.1, tracy 0.15.0, gperftools 2.18.1.

### A.7 mise routes checked (V, 2026-11-13)

| Wanted | Result |
|---|---|
| valgrind, heaptrack, bpftrace, uftrace, perf, hotspot, tracy, bloaty, doxygen, graphviz, plantuml, mrdocs, clang-uml, bencher | not in `mise registry` |
| hyperfine, ccache, sccache, cmake, ninja, mdbook, d2, mermaid-ascii | in registry (cmake 4.5.0, ninja 1.13.2) |
| `github:mstange/samply`, `aqua:mstange/samply` | 0.12.0, 0.13.1 |
| `github:wolfpld/tracy` | 0.14.1, 0.15.0 |
| `github:bpftrace/bpftrace` | 0.27.0, 0.27.1 |
| `github:KDAB/hotspot` | 1.5.1, 1.6.0 |
| `github:KDE/heaptrack` | 1.2.0 |
| `github:bencherdev/bencher` | 0.6.15, 0.6.16 |
| `github:google/bloaty` | 1.0, 1.1 |
| `github:doxygen/doxygen` / `conda:doxygen` | Release_1_17_0, Release_1_18_0 / 1.17.0, 1.18.0 |
| `conda:graphviz` | 14.1.1, 14.1.2 (brew 16.1.1) |
| `conda:plantuml` | 1.2026.9, 1.2026.10 |
| `conda:lcov`, `pipx:gcovr`, `pipx:osaca` | 2.5; 8.8; 0.7.1 |
| `npm:@mermaid-js/mermaid-cli` | 12.0.0, 12.2.0 |
| `github:include-what-you-use/include-what-you-use` | 0.27 |
| `github:cppalliance/mrdocs` | 2026.9.4, 2026.9.29 |
| `github:bkryza/clang-uml` | 0.6.2, 0.6.3 |
| `conda:` valgrind, heaptrack, bpftrace, perf, uftrace, bloaty; `github:namhyung/uftrace` | no versions |
| `aqua:` bloaty, doxygen, plantuml, bencher, mermaid-cli | error (no package) |

"Resolves a version" is not "installs a working macOS arm64 binary"; installs were not attempted. Linux-only tools go in the Linux container image via apt, with a mise task that skips when `command -v` fails.

---

## Part B: documentation and diagrams from code

### B.1 Summary table

| Tool | Purpose | Latest | mise route | macOS/Linux | Modules / import std / reflection OK? | CI-usable | Verdict |
|---|---|---|---|---|---|---|---|
| Doxygen | API reference, Graphviz graphs | 1.18.0 (2026-08-13) | `github:doxygen/doxygen`, `conda:doxygen` (V) | both | Modules supported since 1.9.8 with fixes in 1.13/1.16; open #11322, #12293 (S). import std: not mentioned (U). Reflection: no (U). | yes | adopt (baseline) |
| mrdocs | clang-based reference (html, adoc, xml, json) | 2026.9.29 | `github:cppalliance/mrdocs` (asset pick U) | Darwin/Linux tarballs; glibc >= 2.31, macOS >= 14 (S) | Modules: no code, open #1142 (V). Reflection: no. | yes | later |
| clang-uml | UML class/sequence/package/include | 0.6.3 (2026-07-06); LLVM 12-23 on master | `github:bkryza/clang-uml` (assets rpm/deb/exe/source, U); brew 0.6.3 on llvm@22 (V) | both | Modules: yes (V). import std: none found (V). Reflection: no. | yes, if LLVM matches compiler | adopt (build against LLVM 23) |
| Doxide | Markdown/MkDocs docs | v0.10.0 (2026-10-12) | none | both | unknown (U) | yes | skip |
| Standardese | libclang docs | 0.5.2 (2026-05-20) | none | both | no claim (U) | possible | skip |
| hdoc | clang docs, hosted | 1.4.1 (2024-08-07) | none | both | no (U) | n/a | skip (stale) |
| CMake `--graphviz` | target dependency graph | CMake 4.5.0 (V) | cmake via mise | both | N/A | yes | adopt |
| Mermaid / PlantUML | diagrams in docs | mermaid-cli 12.2.0, PlantUML 1.2026.10 | npm / conda (V) | both | N/A | yes (Chromium for mmdc) | adopt Mermaid; PlantUML if needed |

### B.2 mrdocs (cppalliance/mrdocs @ 2d29928, 2026-11-10)

- Install: release tarballs for Darwin/Linux/win64; Linux glibc >= 2.31, macOS >= 14; `bootstrap.py` builds its own LLVM (`docs/modules/ROOT/pages/install.adoc`; saved as mrdocs-install.adoc).
- Generators: html, adoc (Antora), xml, json, noop, plus data-driven Handlebars examples (md, tex, jsonl).
- Modules (V): zero hits for `getOwningModule|ModuleDecl|isInNamedModule` in `src/` and `include/`. Only module-related code is `src/mrdocs/MrDocsCompilationDatabase.cpp:265-282`, which drops nonexistent CMake `*.obj.modmap` response files. File selection: `MrDocsCompilationDatabase.cpp:50-56` (clang driver extension table) and `:562-579` ("Skipping non-C++ file"). Default `file-patterns` at `src/mrdocs/ConfigOptions.json:137` list only .hpp, .h, .hh, .ipp, .inc, .cpp, .cc, .cxx, .c, .hxx, so `.cppm`/`.ixx` need explicit patterns.
- `MrDocsCompilationDatabase.cpp:324` defines `-std=c++26` as the latest flag; `:368-374` applies it only when the command line has no `-std`.
- "Reflection" in the source is a Boost.Describe-style self-reflection DOM bridge, not P2996 parsing (V grep).
- Issues (V gh): #1142 open "Cannot use with C++20 modules" (`.ixx` skipped as non-C++); #1249 closed as duplicate (a `.mpp` module file aborted mrdocs with clang assertion `isPRValue()` in `ExprClassification.cpp`); #526 open, "CMake targets using precompiled headers".
- Takes `compile_commands.json`. No first-party CMake helper found (U). Verdict: later; re-test when #1142 closes.

### B.3 clang-uml (bkryza/clang-uml @ ff9ffdb, 2026-10-06)

- `README.md:9` LLVM 12-23 badge; outputs PlantUML, MermaidJS, GraphML, JSON; types class, sequence, package, include. `README.md:47`: module packages in class diagrams not supported in MermaidJS.
- Module code: `src/common/visitor/translation_unit_visitor.h:162`; `src/class_diagram/visitor/translation_unit_visitor.cc:792`; `src/package_diagram/visitor/translation_unit_visitor.cc:318,411,833`. Config `package_type: module`, `using_module` (`docs/package_diagrams.md:157-184`); filters `modules`, `module_access` (`docs/diagram_filters.md:100,309`). Tests t00070-72, t30012-15.
- Constraint (`docs/troubleshooting.md` ~157-170): the LLVM clang-uml links must match the LLVM that produced the modules, else "malformed or corrupted AST file". Homebrew clang-uml 0.6.3 is on llvm@22 (V); the project uses clang 23. LLVM 23 support (#458) closed 2026-10-06, after the 0.6.3 tag, so build from master. GCC `gcm.cache` BMIs are not readable by clang; diagrams must come from the clang build's compile commands (GCC-only U).
- No `import std` anywhere in the clone (V grep). Needs a smoke experiment with a tiny named module.
- Needs at least one TU in `compile_commands.json` for header-only code. Verdict: adopt, with an LLVM 23 build step.

### B.4 Doxygen

- 1.18.0 (2026-08-13), prior 1.17.0 (V gh). Module support added in 1.9.8 ("document before the module declaration or use \module"); "Improve showing import relations" in 1.13.0; #11685 fixed in 1.16.0 (S: doxygen-changelog.txt; release attribution approximate). Open: #11322, #12293, #9116 (S).
- `import std` and `^^`/`[: :]`: not found/likely unsupported (U).
- Use `GENERATE_XML`, `HAVE_DOT`, call/include graphs; CMake `doxygen_add_docs` (U for 4.5). Add `*.cppm`/`*.ixx` to `FILE_PATTERNS` (U).

### B.5 Diagrams and hosting

- `cmake --graphviz=deps.dot` (options in `CMakeGraphVizOptions.cmake`; cmake-graphviz.txt) then `dot -Tsvg`.
- Mermaid renders natively on GitHub; `mmdc` needs headless Chromium, with `--no-sandbox` in containers (U).
- GitHub Pages via Actions: `actions/configure-pages`, `upload-pages-artifact`, `deploy-pages`, permissions `pages: write` and `id-token: write` (general knowledge; current major versions U). Run the same `mise run docs` locally and in CI.
- Day-1 stack: Doxygen 1.18 + Graphviz + clang-uml (LLVM-23 build) + CMake graphviz + Mermaid in Markdown. Watchlist: mrdocs.

---

## Not possible (stated plainly)

- Valgrind on Apple Silicon or macOS 27 (S). No callgrind/cachegrind equivalent on macOS.
- BOLT on Mach-O (S); no `llvm-bolt` in Homebrew LLVM 23.1.5 (V).
- ClangIR output with Homebrew clang 23.1.5 (V). MLIR metrics from normal C++ builds.
- uiCA on AMD or Apple CPUs; unmaintained since 2024-01.
- heaptrack on macOS (no support found).
- Parsing P2996 syntax in mrdocs, Doxygen, clang-uml with stock LLVM; the Bloomberg p2996 branch is LLVM 21.0, not 23 (V).
- Hardware perf events on GHA hosted ARM runners (S); x64 unconfirmed.
- Wall-time pass/fail gating on hosted runners.
- dtrace with SIP, non-root, on macOS 27 (V).

## UNVERIFIED

1. `mise use github:...` asset selection for mrdocs (Darwin tarball without arch), tracy, bpftrace, bloaty; nothing installed.
2. HW PMU on GHA x64 hosted VMs; PMU in Docker on Apple silicon.
3. Exact Docker capability set for perf on Ubuntu 26.04; perf/kernel matching in containers.
4. xctrace on hosted macOS runners; stable CPU Counters export schema.
5. Root dtrace behaviour on macOS 27 with SIP.
6. Accuracy of llvm-mca apple-m4/m5 and znver5 models.
7. heaptrack current version and any macOS port.
8. Valgrind 3.28 on GCC 16/clang 23 binaries (DWARF 5, AVX-512/APX).
9. apt.llvm.org `bolt-23` and CIR-enabled clang on Ubuntu 26.04.
10. GCC 16.2 LSan hang cause on macOS; MSan on macOS.
11. mrdocs on `.cppm` and `import std`; CMake helper.
12. Doxygen with `import std`, reflection, `.cppm` patterns; changelog release attribution.
13. clang-uml built against LLVM 23, `import std`, GCC `gcm.cache`.
14. OSACA Apple M-series support (README table read lists ZEN1-5, SKX, N1, V2, TX2; read may have missed rows).
15. CodSpeed internals and pricing.
16. mermaid-cli container flags; current Pages action versions.
17. CMake 4.5 specifics for `--graphviz`, `ctest -T memcheck`, `doxygen_add_docs`.
18. bloaty prebuilt binaries.

## Tools used and failed

Used: `mise` (registry, ls-remote), `gh` (releases, issues, API), `git clone --depth 1` (mrdocs, clang-uml), `curl`, Firecrawl `firecrawl_search`, local macOS tools (`xcrun xctrace`, `leaks`, `sample`, `dtrace`, Homebrew clang/llvm-mca/llc, `g++-16`, `brew info`), grep over the clones.
Not used: Exa, Context7 (Firecrawl, gh and primary sources were sufficient).
Failed or inconclusive: `sharkdp/clang-uml` clone (wrong owner; `bkryza/clang-uml` worked); `mise ls-remote aqua:` for bloaty, doxygen, plantuml, bencher, mermaid-cli; `conda:` valgrind/heaptrack/bpftrace/perf/uftrace/bloaty (no versions); `github:namhyung/uftrace` (no versions); clangir.txt fetch near-empty; no sudo, so root dtrace/profiling not tried; GCC 16 LSan run hung and was killed by pid; several `gh api | base64 -d` calls failed on path/format.

## Saved offline docs

`<research-cache>/docs/perf-docs/`: valgrind-current.txt, valgrind-news-head.txt, xctrace-man.txt, llvm-mca-guide.txt, bolt-readme.md, bolt-macos-issue-72205.md, samply-readme.md, lemire-counters-readme.md, gab-readme.md, codspeed-cpp.txt, tracy-NEWS-head.txt, docker-seccomp-perf.txt, cmake-graphviz.txt, doxygen-changelog.txt, clang-uml-troubleshooting.md, clang-uml-package-diagrams.md, mrdocs-install.adoc, mrdocs-issue-1142-modules.md, clangir.txt.
