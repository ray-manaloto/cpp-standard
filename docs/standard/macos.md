# macOS C++ environment: certification playbook

This playbook says what a Mac (the host or a Tart VM) needs for modern
low-level C++ work: three compilers, their standard libraries and runtimes,
and the tools for analysis, debugging, profiling and metrics. Each item has
a requirement, the reason for it, a probe to copy and paste, the expected
output, and a PASS/FAIL rule. A person or an agent walks the checks in order
and writes the report at the end. A FAIL line is the list of what is missing
or wrong.

The decisions behind it are in
[`decisions-log.md`](../designs/level-1/decisions-log.md) (D30, D33, D38,
D88 and D136). The design is
[`environment-standard.md`](../designs/environment-standard.md) §1.

## How to use it

1. Run the checks in section order. A later section can use a variable or a
   file that an earlier one set.
2. Write one report line per check: `<id> PASS|FAIL|N/A <one-line evidence>`.
3. A check marked **(host)** runs only on bare metal. A check marked
   **(VM)** runs only in a Tart guest. Everything else runs on both.
4. Do not install or change anything while certifying. A FAIL names the fix;
   the fix is a separate step.

Set these first. Each later probe uses them.

```sh
export P2996="$HOME/.local/share/p2996/current"   # the p2996 install prefix
export LLVM23="$(mise where github:llvm/llvm-project 2>/dev/null)"  # the LLVM 23 tarball (D38)
export PROBE="$(mktemp -d)"; cd "$PROBE"
```

## Usable today (this host, 2026-11-14)

You can start a C++26 static reflection project on this Mac now. These
results came from running the probes below on macOS 27.2.1 with Xcode 27.2.

| Area | State | Workaround until fixed |
|---|---|---|
| clang-p2996 `562409c7`: reflection, `import std` through CMake, ASan, TSan, libc++ hardening `extensive`, assertions | PASS | none needed |
| GCC 16.2.0 (Homebrew): `-freflection`, `import std` through CMake | PASS | none needed |
| GCC 16.2.0: TSan, LSan | not on macOS (G4): not built for aarch64 Darwin | use p2996 or clang for TSan |
| GCC 16.2.0: sysroot is the Command Line Tools `MacOSX26.sdk` | FAIL (G3) | builds work; the D33 source build fixes it |
| GCC with Homebrew C++ libraries (Boost and others) | FAIL: crashes at run time | build C++ dependencies with vcpkg, one triplet per compiler (K1) |
| clang 23.1.5 (Homebrew): `import std` through CMake | FAIL (C4) | `-DCMAKE_CXX_STDLIB_MODULES_JSON=/opt/homebrew/opt/llvm/lib/c++/libc++.modules.json` |
| clang 23: reflection | no (upstream clang has no P2996) | use p2996 or GCC |
| GCC 16.2.0: `-g` with `-fsanitize=address` or `undefined` | FAIL (G6): the link runs Homebrew LLVM's `dsymutil`, which dies with SIGILL | put `/usr/bin` before `/opt/homebrew/opt/llvm/bin` for GCC builds, or build without `-g` |
| `lldb-p2996`, `lldb-dap-p2996` | FAIL: both start after the DB3 fix; `lldb-p2996` crashes loading any program (DB5 blocker); `lldb-dap-p2996` loading a program is untested | debug with Apple `lldb` (`xcrun lldb`) |
| `llvm-mca-p2996` | PASS (R4) only with ELF assembly; macOS assembly hits an assertion on `.subsections_via_symbols` | feed it ELF assembly (`--target=aarch64-linux-gnu`), or use clang 23's `llvm-mca` |
| p2996 LLVM utilities (FileCheck and others) | FAIL (P6): `LLVM_INSTALL_UTILS` was off | none needed until the rebuild |
| include-what-you-use for p2996 | FAIL (P8): not built | run Homebrew IWYU on files without `^^` |
| In-tree code-signed debugserver | FAIL (DB5): the build used the system one, and lldb-p2996 crashes before it attaches (DB5 blocker) | debug with Apple `lldb` (`xcrun lldb`); `LLDB_DEBUGSERVER_PATH` set to Xcode's debugserver helps only once lldb-p2996 loads programs |
| p2996 with `-fuse-ld=lld` | FAIL (P10): LLVM 21's `lld` cannot read the macOS 27 SDK's `.tbd` files | use Apple `ld`, the default |
| XRay | not on macOS (T7): the runtime archives exist but do not work on Darwin, in p2996 and clang 23 alike | `xctrace` Time Profiler |
| Developer mode, Xcode first launch | FAIL (A3, A6) | `sudo DevToolsSecurity -enable`; `sudo xcodebuild -runFirstLaunch`; `sudo xcodebuild -license accept` |
| p2996 coverage | PASS with the matching tools | use `llvm-cov-p2996 gcov`, never another LLVM's |
| `g++` / `gcc` on `PATH` | Apple clang: `gcc` is `/usr/bin/gcc`, and `g++` is a mise shim with no active version, which falls through to `/usr/bin/g++` | call `g++-16` by name |
| `ccache` on `PATH` | mise shim with no version set; it exits with an error | use sccache (D9); ccache does not cache C++20 modules |
| Tart | not installed | V checks wait for the install |

## The end state

| Component | Source | Built from source? | Why |
|---|---|---|---|
| Xcode 27.2 + Command Line Tools 27.2 | Apple | no | The macOS SDK, Apple `ld`, Apple `lldb` and `debugserver`, and Instruments (`xctrace`, CPU Counters). The full Xcode is needed for the profiling tools (D136). (`leaks`, `heap`, `vmmap` and `malloc_history` also ship with macOS in `/usr/bin`.) |
| LLVM / clang 23 + libc++ | the LLVM release tarball `LLVM-<ver>-macOS-ARM64.tar.xz` via mise `github:llvm/llvm-project` | no | The daily compiler. It replaces Homebrew LLVM (D38). The tarball has libc++ with `libc++.modules.json`, every macOS sanitizer runtime, clangd, clang-tidy, lldb, llvm-mca and `ld64.lld`. It has no config file, so we add one (C2). |
| GCC 16.2.0 + libstdc++ | `gcc-16.2.0.tar.xz` + Iain Sandoe's Darwin patch, with Homebrew's `gcc.rb` as the template | **yes** | No package gives an exact, checksummed GCC for macOS 27 (D33). The build sets the sysroot to the current SDK. |
| clang-p2996 + libc++ | `bloomberg/clang-p2996` at a pinned commit | **yes** | No prebuilt binary exists. It is the reflection reference compiler (D30). |
| include-what-you-use for p2996 | IWYU `clang_21` branch, built out of tree against p2996 | **yes** | p2996 is based on LLVM 21. Homebrew's IWYU uses clang 23 and cannot parse `^^` (D136). |
| CMake 4.5, Ninja, sccache, vcpkg, gcovr, Doxygen, hyperfine | mise | no | Build, cache, dependencies, coverage report, docs, timing. |
| Tart | `brew install openai/tools/tart` | no | VM host (host only). |

### The p2996 build configuration

From the LLVM sources at `562409c7` (`llvm/CMakeLists.txt`,
`runtimes/CMakeLists.txt`, `compiler-rt/cmake/config-ix.cmake`) and LLVM's
official macOS release script:

| Setting | Value | Why |
|---|---|---|
| `LLVM_ENABLE_PROJECTS` | `clang;clang-tools-extra;lld;lldb;mlir;polly` | Everything a C++ developer uses. Polly (loop optimiser) and MLIR are kept on request. **flang, BOLT and LLVM libc are dropped**: flang is not C++; BOLT reads only ELF (`bolt/README.md:12`), so it cannot optimise a Mach-O binary; LLVM's macOS release leaves out flang and BOLT. |
| `LLVM_ENABLE_RUNTIMES` | `libunwind;libcxxabi;libcxx;compiler-rt` | libc++ with `import std`, and the sanitizer, profile and fuzzer runtimes (the XRay runtime is built too, but does not work on Darwin, T7). (`openmp` is optional; `offload` does not build on Apple.) |
| `LLVM_ENABLE_ASSERTIONS` | `ON` | The reflection frontend is experimental; an assertion reports a compiler bug instead of producing wrong code. Fixed at build time. |
| `LIBCXX_HARDENING_MODE` | `extensive` | The default for every project. A project can change it (H1). No ABI effect (`libcxx/docs/Hardening.rst:40`). |
| `LLVM_INSTALL_UTILS` | `ON` | Installs FileCheck, `not`, `count`, `yaml2obj` for lit-style tests and for reducing compiler bugs. |
| `LLDB_ENABLE_PYTHON` | `ON`, linked to mise's Python 3.15, with an rpath to it | lldb scripting, data formatters and lldb-dap (DB3). |
| `LLDB_USE_SYSTEM_DEBUGSERVER` | `OFF`, debugserver code-signed with `lldb_codesign` | debugserver matches lldb exactly (DB5). |
| LTO / PGO of the toolchain | off | LLVM's own macOS arm64 release turns both off; with them on, the build passes 6 hours. A full LTO/PGO build can move to a CI job later. |

### What macOS cannot have

From `compiler-rt/cmake/config-ix.cmake` at `562409c7` and each tool's
upstream docs. List these as Linux-only; do not report them as missing.

| Tool | Why not on macOS | Mac substitute |
|---|---|---|
| MemorySanitizer, DataFlowSanitizer, HWASan, MemProf, NSan, GWP-ASan, Scudo, SafeStack | compiler-rt does not build them for Darwin | ASan + UBSan; `MallocScribble`, `MallocGuardEdges`; `leaks` |
| BOLT | reads ELF only | PGO (`-fprofile-generate` / `-fprofile-use`) |
| Linux `perf` | Linux kernel interface | `xctrace` Time Profiler and CPU Counters (R2) |
| Valgrind (memcheck, callgrind, cachegrind) | no current arm64 Darwin port | ASan; `xctrace` Allocations and Leaks; `heap`, `vmmap` |
| gdb | no arm64 Darwin target | lldb |
| GCC TSan and LSan | disabled for aarch64 Darwin by the Darwin patch | TSan from p2996 or clang 23 |
| `<stacktrace>` with GCC | libbacktrace does not read Mach-O | guard with `__cpp_lib_stacktrace` (L2) |
| uftrace, bpftrace | Linux tracing | `dtrace` (needs SIP changes); `xctrace` Time Profiler |
| XRay (function tracing) | the Darwin runtime is a stub: the driver links its archives without `-force_load`, so the linker drops them; the Apple build skips the AArch64 patching code (`XRAY_SOURCE_ARCHS` says `aarch64`, Apple says `arm64`); and `xray_init.cpp` leaves the instrumentation map empty on Apple. llvm/llvm-project PR #196848 (open) fixes all three (T7) | `xctrace` Time Profiler |

## A. Apple base

**A1. macOS version.** Why: the SDK and every toolchain pin follow the OS
major. Probe: `sw_vers -productVersion`. Expected: `27.2` or a later 27.x.
PASS if the major is 27.

**A2. Full Xcode selected.** Why: Instruments, `xctrace` and the signed
`debugserver` come only with Xcode (D136). Probe:

```sh
xcode-select -p; xcodebuild -version
```

Expected: `/Applications/Xcode.app/Contents/Developer` and `Xcode 27.2`.
PASS if the path is inside `Xcode.app` and the version is 27.x. FAIL if the
path is `/Library/Developer/CommandLineTools`.

**A3. Xcode licence accepted and first launch done.** Probe:
`xcodebuild -checkFirstLaunchStatus; echo $?`. Expected: `0`. Fix:
`sudo xcodebuild -runFirstLaunch` and `sudo xcodebuild -license accept`.
Today: FAIL (exit status `69`).

**A4. Command Line Tools installed.** Why: Homebrew and some build scripts
look there. Probe: `pkgutil --pkg-info=com.apple.pkg.CLTools_Executables |
grep version`. Expected: `version: 27.2...`. PASS if the major is 27.

**A5. The active SDK.** Why: every compiler must compile against the same
SDK as the OS. Probe: `xcrun --show-sdk-path; xcrun --show-sdk-version`.
Expected: a path ending `MacOSX.sdk` inside Xcode, and `27.2`. PASS if the
SDK major matches A1.

**A6. Developer mode for debugging.** Why: lldb needs it to attach without a
prompt. Probe: `DevToolsSecurity -status`. Expected: `Developer mode is
currently enabled.` Fix: `sudo DevToolsSecurity -enable`. Today: FAIL
(`disabled`).

## B. Build tools

**B1. Versions.** Probe:

```sh
for t in mise cmake ninja sccache vcpkg gcovr doxygen hyperfine; do
  printf '%-10s ' "$t"; "$t" --version 2>&1 | head -1
done
```

Expected: CMake `4.5.x`; every other tool prints a version. PASS if all
eight print a version and CMake is 4.5 or later. Why CMake 4.5: it removed
`CMAKE_CXX_MODULE_STD`; `import std` is used whenever module scanning is on,
and `CMAKE_CXX_STDLIB_MODULES_JSON` overrides where it looks.

**B2. No stray shims.** Why: a `g++` that is really Apple clang, or a broken
`ccache`, silently changes the build. Probe:

```sh
g++ --version 2>&1 | head -1; ccache --version 2>&1 | head -1
```

PASS if `g++` is GCC 16 (or absent) and `ccache` is absent or works. Today:
FAIL (`g++` is a mise shim with no active version that falls through to
Apple clang; `ccache` is a mise shim with no version set, so it errors).

**B3. sccache is the launcher.** Why: ccache does not cache C++20 modules
(D9). Probe: `sccache --show-stats | head -3`. PASS if it prints statistics.

## C. LLVM / clang 23 (release tarball)

**C1. Installed from the tarball.** Probe:

```sh
"$LLVM23/bin/clang++" --version | head -1
```

Expected: `clang version 23.x.y` (not `Homebrew clang`). PASS if the path is
the mise install and the version is 23. Today: FAIL (Homebrew 23.1.5).

**C2. Config file finds the SDK and the tarball's libc++.** Why: the tarball
has no config file and no `xcselect`, so without one clang finds no SDK and
links the system libc++ instead of its own. Expected files next to
`clang++`: `arm64-apple-darwin.cfg` holding `-isysroot <xcrun SDK path>`,
and `arm64-apple-darwin-clang++.cfg` holding `@arm64-apple-darwin.cfg` plus,
link-only (`$` prefix), `-L<prefix>/lib`, `-rpath <prefix>/lib` and
`-lunwind`. (This is the layout the p2996 install already uses.) Probe:

```sh
"$LLVM23/bin/clang++" -### -x c++ /dev/null 2>&1 | grep -m1 'Configuration file'
```

PASS if it names `arm64-apple-darwin-clang++.cfg`.

**C3. Links its own libc++.** Probe:

```sh
printf '#include <print>\nint main(){std::println("ok");}\n' > p.cpp
"$LLVM23/bin/clang++" -std=c++26 p.cpp -o p && ./p && otool -L p | grep c++
```

Expected: `ok`, and `libc++.1.dylib` from the tarball's `lib`, not
`/usr/lib`. PASS if both.

**C4. `import std` through CMake.** Why: `-print-file-name=libc++.modules.json`
must resolve, or CMake stops with "Could not find `libc++.modules.json`".
Use the CMake project in [Appendix: CMake probe](#appendix-cmake-probe) with
`-DCMAKE_CXX_COMPILER="$LLVM23/bin/clang++"`. Expected: `import std ok`.
Today (Homebrew): FAIL, because Homebrew installs the file at `lib/c++/`.

**C5. Runtimes.** Probe: `ls "$("$LLVM23/bin/clang++" -print-resource-dir)/lib/darwin"`.
Expected, at least: `asan_osx_dynamic`, `ubsan_osx_dynamic`,
`tsan_osx_dynamic`, `lsan_osx_dynamic`, `rtsan_osx_dynamic`,
`tysan_osx_dynamic`, `fuzzer_osx`, `profile_osx`, `xray_osx`. PASS if all
nine.

**C6. Sanitizers run.** Use `san.cpp` from
[Appendix: sanitizer probe](#appendix-sanitizer-probe). Probe:

```sh
for s in address thread undefined; do
  "$LLVM23/bin/clang++" -g -fsanitize=$s san.cpp -o s_$s && ./s_$s 2>&1 | grep -m1 -E 'ERROR|WARNING|runtime error'
done
```

Expected: `heap-buffer-overflow`, `data race`, and a UBSan `runtime error`.
PASS if all three fire.

**C7. Tools.** Probe: `ls "$LLVM23/bin" | grep -E '^(clangd|clang-tidy|clang-format|llvm-mca|llvm-cov|llvm-profdata|ld64.lld|lldb|scan-build)$'`.
PASS if all nine are listed.

**C8. Both linkers.** Why: Apple `ld` is the default; `ld64.lld` is a preset
for link-time comparisons (D136). Probe:

```sh
"$LLVM23/bin/clang++" -std=c++26 p.cpp -o pa && ./pa
"$LLVM23/bin/clang++" -std=c++26 -fuse-ld=lld p.cpp -o pl && ./pl
```

Expected: `ok` twice. Verified with Homebrew clang 23.1.5.

## G. GCC 16.2 (source build)

**G1. Version and origin.** Probe: `g++-16 --version | head -1; g++-16 -v 2>&1 | grep -o -- "--with-pkgversion='[^']*'"`.
Expected: `16.2.0`, built by cpp-standard (D33). Today: Homebrew GCC 16.2.0,
which is the right version but not the pinned build.

**G2. Reflection and `import std`.** Probe: compile `refl.cpp` from
[Appendix: reflection probe](#appendix-reflection-probe) with
`g++-16 -std=c++26 -freflection`, then the CMake probe with
`-DCMAKE_CXX_COMPILER=g++-16`. Expected: `members=2` and `import std ok`.

**G3. Sysroot matches the SDK.** Why: GCC was configured with a fixed
`--with-sysroot`; an old SDK hides new APIs and can mismatch the OS headers.
Probe: `g++-16 -v 2>&1 | grep -o -- '--with-sysroot=[^ ]*'`. PASS if the path
exists and its SDK major equals A1. Today: FAIL
(`/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk`).

**G4. Sanitizers.** Expected: ASan and UBSan fire (C6 loop with `g++-16`);
`-fsanitize=thread` fails to link (`___tsan_func_entry` undefined). That is
the expected result, not a FAIL: the Darwin patch disables TSan and LSan on
aarch64. Run ASan with `ASAN_OPTIONS=detect_leaks=0`.

**G5. Never link libc++ C++ libraries.** Why: GCC uses libstdc++; a C++
library built by clang against libc++ (Homebrew Boost, for example) has a
different ABI and crashes at run time. Rule: all C++ dependencies come from
vcpkg with the GCC triplet (K1). C-only libraries are fine.

**G6. Debug info links.** Why: with `-g`, GCC's link step runs the first
`dsymutil` on `PATH` (`g++-16 -print-prog-name=dsymutil` prints the bare
name). Probe:

```sh
command -v dsymutil
g++-16 -std=c++26 -g -fsanitize=address san.cpp -o g_a && echo link-ok
```

Expected: `/usr/bin/dsymutil` (or Xcode's) and `link-ok`. Today: FAIL, the
first `dsymutil` is Homebrew LLVM's, and the link stops with
`dsymutil terminated with signal 4 [Illegal instruction: 4]`. With
`/usr/bin` first on `PATH` the same command links.

## P. clang-p2996 (source build)

**P1. Commit and build flags.** Probe: `"$P2996/bin/clang++-p2996" --version`.
Expected: the pinned commit (today `562409c7942690d59ea470762515f88f24b16e23`)
and `Build config: +assertions`. PASS if both.

**P2. Config files.** As C2, for p2996. Probe:
`"$P2996/bin/clang++-p2996" --version | grep 'Configuration file'`. PASS if it
names `arm64-apple-darwin-clang++.cfg` and that file's `-isysroot` SDK
exists and matches A5.

**P3. Hardening default.** Probe:
`grep _LIBCPP_HARDENING_MODE_DEFAULT "$P2996/include/c++/v1/__config_site"`.
Expected: `16` (`_LIBCPP_HARDENING_MODE_EXTENSIVE` is `1 << 4` in
`__config`). PASS if `16`.

**P4. Reflection, `import std`, sanitizers.** `refl.cpp` with
`-std=c++26 -freflection-latest` prints `members=2`; the CMake probe prints
`import std ok`; the C6 loop with `clang++-p2996` fires all three. PASS if
all.

**P5. Projects present.** Probe:

```sh
ls "$P2996/bin" | grep -cE '^(clangd|clang-tidy|clang-format|clang-include-cleaner|clang-query|clang-doc|scan-build|ld64.lld|llvm-mca|llvm-cov|llvm-profdata|llvm-xray|lldb|lldb-dap|mlir-opt)-p2996$'
"$P2996/bin/clang++-p2996" -O2 -mllvm -polly -c -x c++ /dev/null -o /dev/null && echo polly-ok
```

Expected: `15` and `polly-ok`. Not expected after the D136 rebuild: `flang`,
`llvm-bolt`, `perf2bolt` (today they are present; harmless, but they make the
build longer).

**P6. LLVM utilities.** Probe: `ls "$P2996/bin" | grep -E '^(FileCheck|not|count|yaml2obj)'`.
PASS if all four (with or without the `-p2996` suffix). Today: FAIL
(`LLVM_INSTALL_UTILS` was off).

**P7. Tools parse reflection.** Probe:

```sh
"$P2996/bin/clang-tidy-p2996" refl.cpp -- -std=c++26 -freflection-latest 2>&1 | grep -c 'error:'
```

Expected: `0` (verified). Same for `clang-format-p2996 --dry-run` and
`clang-include-cleaner-p2996`.

**P8. include-what-you-use.** Probe:
`include-what-you-use-p2996 --version` (or the name the build installs).
Expected: `include-what-you-use 0.25` and `clang version 21.0.0git` with the
p2996 commit. Build: IWYU branch `clang_21`, CMake with
`-DCMAKE_PREFIX_PATH=$P2996`. If it fails to compile against p2996, pin the
IWYU commit nearest the date p2996 branched from LLVM main. Today: FAIL (not
built). IWYU does not model reflection; run it on files without `^^`.

**P9. Coverage tools match the compiler.** Why: a `.gcda` from p2996 must be
read by p2996's own `llvm-cov`. Probe:

```sh
"$P2996/bin/clang++-p2996" --coverage -std=c++26 p.cpp -o pc && ./pc >/dev/null &&
"$P2996/bin/llvm-cov-p2996" gcov -n pc-p.gcda | head -2
```

Expected: `File 'p.cpp'` and `Lines executed:100.00%`. PASS if so (D88).

**P10. p2996 with `ld64.lld`.** Probe:
`"$P2996/bin/clang++-p2996" -std=c++26 -fuse-ld=lld p.cpp -o pl && ./pl`.
Expected: `ok`. Today: FAIL, `could not load TAPI file .../libSystem.tbd:
malformed file ... unknown architecture`. The macOS 27 SDK lists a target
`arm64e.x1-macos` that LLVM 21's TAPI reader does not know. Use Apple `ld`
(the default) with p2996; the check passes again when p2996 moves to an LLVM
base whose `lld` reads that SDK (LLVM 23's does, C8).

## D. Debuggers

Three debuggers are certified: Apple lldb, LLVM 23 lldb, lldb-p2996 (D136).

**DB1. Apple lldb.** Probe: `xcrun lldb --version; xcrun lldb -b -o 'script print(1+1)'`.
Expected: `lldb-2103...` (today `lldb-2103.0.34.407`) and `2`. PASS if
both.

**DB2. LLVM 23 lldb.** Probe: `"$LLVM23/bin/lldb" --version`. Expected:
`lldb version 23.x`. The tarball lldb is built without Python, so `script`
fails: expected, not a FAIL. Its `debugserver` is ad-hoc signed; if attach
fails, set `LLDB_DEBUGSERVER_PATH` to Xcode's (DB5 probe).

LLVM 23 has the 32-bit offset bug described under the DB5 blocker, and also
llvm/llvm-project #202773 and #203055 (both in `release/23.x`), so its lldb
should load programs without crashing but may read wrong symbols for system
libraries. Load probe:
`"$LLVM23/bin/lldb" -b -o 'target create /bin/ls'; echo $?`. PASS if it
prints `Current executable set to '/bin/ls'` and exits 0; FAIL on any other
exit code. A PASS does not rule out the wrong-symbol reads. Not yet run: the
LLVM 23 tarball is not installed on this Mac today.

**DB3. lldb-p2996 starts and runs Python.** Probe:

```sh
"$P2996/bin/lldb-p2996" -b -o 'script print(40+2)'
otool -l "$P2996/lib/liblldb.dylib" | grep -A2 LC_RPATH | grep path
ls "$HOME/.local/share/mise/installs/python/3.15/lib/libpython3.15.dylib"
```

Expected: `42`, an `LC_RPATH` entry `.../mise/installs/python/3.15/lib`, and
that directory holds `libpython3.15.dylib`. PASS if all three. Today: PASS
on this Mac after fix 2 below was applied to the installed copy
(2026-11-14). A fresh p2996 build still fails with
`dyld: Library not loaded: @rpath/libpython3.15.dylib` until the build
carries fix 1, because its only rpath is `@loader_path/../lib`.

Why: mise's Python is a python-build-standalone build, so
`libpython3.15.dylib` names itself `@rpath/libpython3.15.dylib`. `liblldb`
records that name when it links, and the p2996 build sets
`CMAKE_INSTALL_RPATH` to `@loader_path/../lib` only, so dyld never looks in
mise's Python.

Fix, in order of preference:

1. Rebuild with
   `-DCMAKE_INSTALL_RPATH="@loader_path/../lib;$HOME/.local/share/mise/installs/python/3.15/lib"`
   and `-DPython3_EXECUTABLE="$(mise which python3.15)"`, so the rpath is part
   of the build inputs. If the build script forces `CMAKE_INSTALL_RPATH` in a
   cache file, change it there; a forced cache value wins over `-D`.
2. On an existing install:

   ```sh
   install_name_tool -add_rpath "$HOME/.local/share/mise/installs/python/3.15/lib" "$P2996/lib/liblldb.dylib"
   codesign -f -s - "$P2996/lib/liblldb.dylib"
   ```

   Xcode 27's `install_name_tool` re-signs an ad-hoc signed file itself
   (verified: `codesign -v` passes after the edit); the explicit `codesign`
   keeps the step safe with older tools, where a broken signature makes
   macOS kill the process.

Use the `installs/python/3.15` path, not `$(mise where python@3.15)`: `mise
where` prints the hashed install folder, which changes when mise reinstalls
Python, while `installs/python/3.15` is a link that follows 3.15.x patch
updates. `PYTHONHOME` is not needed: Python finds its standard library from
the real location of `libpython3.15.dylib`. Do not rely on
`DYLD_LIBRARY_PATH` as a workaround: it works when you start `lldb-p2996`
directly, but SIP removes `DYLD_*` variables when a protected program such
as `/bin/sh` starts, so a value set before a script or wrapper runs never
reaches lldb (verified: `DYLD_LIBRARY_PATH=... /bin/sh -c lldb-p2996` fails,
while a script that exports it itself works). The rpath fix needs neither.

Keep Python 3.15 installed: a mise prune that removes it, or a move to 3.16,
breaks lldb-p2996 again. Re-run DB3 after any Python change.

**DB4. lldb-dap.** Probe: `"$P2996/bin/lldb-dap-p2996" --help | head -1`.
PASS if it prints usage (`OVERVIEW: LLDB DAP`). Today: PASS on this Mac
after the DB3 fix; a fresh build fails with the same missing
`libpython3.15.dylib` as DB3 until it carries DB3 fix 1.

**DB5. In-tree debugserver, code-signed.** Why: `LLDB_USE_SYSTEM_DEBUGSERVER=OFF`
makes the debugserver match lldb-p2996 exactly; macOS refuses to let an
unsigned debugserver attach to a process. lldb looks for it in
`LLDB_DEBUGSERVER_PATH` first, then in its support directory
(`ProcessGDBRemote.cpp`). Probe:

```sh
DS="$(find "$P2996" -name debugserver -type f | head -1)"; echo "$DS"
codesign -dvv "$DS" 2>&1 | grep -E 'Authority|Signature'
"$P2996/bin/clang++-p2996" -std=c++26 -g p.cpp -o pd
"$P2996/bin/lldb-p2996" -b -o 'b main' -o run -o 'frame variable' -o kill pd 2>&1 | grep -m1 'stop reason'
```

Expected: a path inside `$P2996`, `Authority=lldb_codesign`, and
`stop reason = breakpoint 1.1`. Today: FAIL for two reasons: there is no
in-tree debugserver (the build used the system one), and lldb-p2996 crashes
before it gets that far (DB5 blocker, after the steps).

Steps (from `lldb/docs/resources/build.rst`, "Code Signing on macOS"):

1. Create the signing certificate once per Mac or VM, as an admin:
   `sudo lldb/scripts/macos-setup-codesign.sh` from the p2996 source tree.
   It creates a self-signed `lldb_codesign` identity in
   `/Library/Keychains/System.keychain` and trusts it for code signing. It
   needs an admin password; in a VM, run it while building the golden image.
2. Check it: `security find-certificate -c lldb_codesign /Library/Keychains/System.keychain`
   prints the certificate.
3. Configure p2996 with `-DLLDB_USE_SYSTEM_DEBUGSERVER=OFF` (the build signs
   debugserver with `lldb_codesign` by default; `LLDB_CODESIGN_IDENTITY`
   overrides the name).
4. Rebuild and install; run the DB5 probe.
5. If the certificate cannot be made (no admin), fall back:
   `export LLDB_DEBUGSERVER_PATH=/Applications/Xcode.app/Contents/SharedFrameworks/LLDB.framework/Versions/A/Resources/debugserver`
   and record DB5 as FAIL with that workaround.

**DB5 blocker: lldb-p2996 crashes loading any program on macOS 27.** Report
it on the DB5 line until it passes. Probe:
`"$P2996/bin/lldb-p2996" -b -o 'target create /bin/ls'; echo $?`. Expected:
exit 0. Today: exit 132 (128 + signal 4, `SIGILL`). The crash report in
`~/Library/Logs/DiagnosticReports/` says `EXC_BAD_ACCESS`
(`KERN_PROTECTION_FAILURE`), "Thread stack size exceeded due to excessive
recursion", with `ParseTrieEntries` calling itself, and names the signal as
`SIGILL`; so the exit code is this stack overflow, not a separate fault.
Apple `lldb` loads the same program.

Why: lldb reads each system library's symbol table, string table and export
trie out of the dyld shared cache it has mapped. It adds the distance from
the library's `__TEXT` to the cache's `__LINKEDIT` to each 32-bit offset field
in the library's load commands (`ObjectFileMachO::ParseSymtab`). On macOS 27
that distance is more than 4 GiB for many libraries (`libcorecrypto`:
`0x1619b2000`), so the sum wraps. lldb then parses unrelated bytes as an
export trie; when those bytes happen to point back at themselves, the parser
recurses until it crashes. Verified on this Mac:

- lldb-p2996 read `libcorecrypto`'s trie 4 GiB below the real one. The real
  trie is well formed: 1,140 exports, depth 12, no node reached twice.
- Of the 15 libraries `/bin/ls` loads, loaded one at a time, every library
  whose symbol table parse crashes lldb has a wrapping offset, and none
  without one crashes it. `libcopyfile` wraps without crashing, so lldb
  reads the wrong symbols for it silently.

Upstream `main` has the same code. llvm/llvm-project #202773 and #203055
reject a cyclic trie, which stops the crash, but lldb still reads the wrong
bytes; they also do not apply to the p2996 fork, which predates the upstream
move of the trie parser into `MachOTrie.cpp`.

Fix (untested until a p2996 build carries it): patch `ObjectFileMachO.cpp`
to keep the adjusted offsets in 64-bit variables instead of the 32-bit load
command fields. Until a build with that patch passes the probe above, debug
with Apple `lldb`. After a rebuild, run the probe above, then the DB5 probe.

## L. Library features (headers)

**L1. Required C++26 headers compile.** Probe: for each compiler,
`<expected> <flat_map> <format> <mdspan> <print> <ranges>` compile with
`-std=c++26 -fsyntax-only`. PASS if no compiler reports a missing header.

**L2. Known gaps are guarded, not failed.** These are absent today and are
expected to be absent; code must guard them with the feature-test macro
after `#include <version>`:

| Feature | clang 23 libc++ | p2996 libc++ | GCC 16 libstdc++ |
|---|---|---|---|
| `<generator>` (`__cpp_lib_generator`) | not implemented | not implemented | `202207L` |
| `<stacktrace>` (`__cpp_lib_stacktrace`) | not implemented | not implemented | header present, macro undefined (no Mach-O backtrace) |

Probe: `printf '#include <version>\n__cpp_lib_generator __cpp_lib_stacktrace\n' > v.cpp`
then `<compiler> -std=c++26 -E -P v.cpp | tail -1`. PASS if the output matches
the table. A change is good news: update the table.

**L3. Detecting reflection.** The compilers report it differently, so a guard
must test both:

```cpp
#if defined(__cpp_impl_reflection) || __has_feature(reflection)
#include <meta>
#endif
```

GCC 16 with `-freflection` defines `__cpp_impl_reflection` and
`__cpp_lib_reflection` (`202603L`). p2996 with `-freflection-latest` defines
neither, even after `#include <meta>`, and reports `__has_feature(reflection)`.
`__has_include(<meta>)` is true on p2996 even without the flag, so it is not a
test. GCC 16 defines `__has_feature` but reports `__has_feature(reflection)`
as false, so the `__cpp_impl_reflection` half of the guard is the one that
matches on GCC.

## H. Hardening presets

**H1. Per-project levels.** The toolchain sets only the default. A project
picks its level with one definition for the whole project, before any header
(`Hardening.rst:47-73`):

| Preset layer | libc++ (clang 23, p2996) | libstdc++ (GCC 16) |
|---|---|---|
| debug, sanitizers | `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE` | `-D_GLIBCXX_ASSERTIONS` |
| release | `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST` | `-D_GLIBCXX_ASSERTIONS` (or none, measured) |
| off (benchmarks only) | `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_NONE` | none |

The compiled part of libc++ (`libc++.dylib`) keeps the toolchain's level.
Hardening does not change the ABI.

**H2. The level took effect.** Probe:

```sh
printf '#include <vector>\nint main(){std::vector<int> v(1); return v[5];}\n' > h.cpp
"$P2996/bin/clang++-p2996" -std=c++26 h.cpp -o h && ./h; echo "exit=$?"
```

Expected: `exit=133` (SIGTRAP; the extensive mode traps without a message).
PASS if so. With `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_NONE` the
same program does not trap.

## K. Dependencies (vcpkg)

**K1. Three arm64-osx triplets.** Why: each compiler and standard library
pair has its own ABI (G5), so each gets its own triplet (and, from Level 2, its own binary-cache key). The names drop the Linux `-libcxx` suffix because clang on the Mac has only libc++.
A project has, in its overlay triplets directory: `arm64-osx-clang23`,
`arm64-osx-gcc16`, `arm64-osx-p2996`. Each sets `VCPKG_TARGET_ARCHITECTURE
arm64`, `VCPKG_CMAKE_SYSTEM_NAME Darwin`, and `VCPKG_CHAINLOAD_TOOLCHAIN_FILE`
to a toolchain file that names that compiler. Probe (in a project):
`ls triplets/arm64-osx-*.cmake`. PASS if all three exist and each chainloads
a different compiler.

**K2. vcpkg works.** Probe: `vcpkg version | head -1`. PASS if it prints a
version.

## E. Editor and code navigation

**E1. Compile database.** Projects configure with
`CMAKE_EXPORT_COMPILE_COMMANDS=ON`. PASS if `build/compile_commands.json`
exists after configure.

**E2. The matching clangd.** Why: clangd parses with its own frontend, so
only `clangd-p2996` understands `^^` and `[: :]`. Rule: a reflection project
points its editor at `$P2996/bin/clangd-p2996`; other projects use
`$LLVM23/bin/clangd`. Probe (the flags file stands in for the compile
database):

```sh
printf -- '-std=c++26\n-freflection-latest\n' > compile_flags.txt
"$P2996/bin/clangd-p2996" --check=refl.cpp 2>&1 | tail -1
```

Expected: a line ending `All checks completed, 0 errors`. Without the flags
it reports errors, because clangd then parses as C++17 without reflection.

## T. Static and dynamic analysis

**T1. clang-tidy and clang-format.** Use `$LLVM23` builds for projects
without reflection and the `-p2996` builds for reflection projects (P7).
On reflection code clang-tidy only reports: the tier-1 gate runs it on
plain-clang targets only (D19).

**T2. Clang Static Analyzer.** Probe: `"$P2996/bin/scan-build-p2996" --help | head -1`.
PASS if it prints usage.

**T3. IWYU.** P8 for p2996; for clang 23 projects, an IWYU built against
LLVM 23 (Homebrew's `include-what-you-use` is one today).

**T4. Sanitizers.** C6, G4 and P4. Also present and expected to link:
`-fsanitize=realtime` (RTSan), `-fsanitize=type` (TySan),
`-fsanitize=fuzzer` (libFuzzer). Probe:
`for f in realtime type fuzzer; do "$P2996/bin/clang++-p2996" -std=c++26 -fsanitize=$f p.cpp -o t_$f && echo $f-ok; done`.
PASS if all three print `-ok` (verified).

**T5. Apple memory tools.** Probe: `for t in leaks heap vmmap malloc_history; do xcrun -f $t; done`.
PASS if all four resolve (Xcode's copies; macOS also ships them in
`/usr/bin`). Use: `leaks --atExit -- ./prog`.

**T6. cppcheck, ClangBuildAnalyzer, clang-uml, mrdocs.** Tier-2 tools (D19).
Probe: `command -v cppcheck ClangBuildAnalyzer clang-uml mrdocs`. Today:
none installed; FAIL only once D19 moves them to tier 1.

**T7. XRay.** Probe:

```sh
"$P2996/bin/clang++-p2996" -std=c++26 -fxray-instrument -fxray-instruction-threshold=1 p.cpp -o px &&
XRAY_OPTIONS="patch_premain=true xray_mode=xray-basic" ./px; ls xray-log.*
```

Report N/A on macOS: the program runs but writes no log, with p2996 and
with clang 23 alike, because the Darwin XRay runtime does not work (see
"What macOS cannot have"). Use the `xctrace` Time Profiler instead (R1).
When llvm/llvm-project PR #196848 lands in a compiler we use, this check
becomes PASS if it writes an `xray-log.*` file.

## R. Profiling and metrics

**R1. Instruments templates.** Probe: `xcrun xctrace list templates | grep -E 'Time Profiler|CPU Counters|Allocations|Leaks|CPU Profiler'`.
PASS if all five are listed.

**R2. CPU performance counters (host).** Why: the PMU counters (cycles,
instructions, cache and branch misses) come from the hardware; a Tart guest
is not known to expose them, so counter numbers come from the host (D136).
Probe: `xcrun xctrace record --template 'CPU Counters' --launch -- ./p`.
PASS if it writes a `.trace` with counter data. In a VM, record the result as
N/A.

**R3. Sampling.** Probe: `./p & sample $! 1 >/dev/null; echo $?`. PASS on 0.

**R4. llvm-mca.** Use a small kernel:
`printf 'int dot(const int*a,const int*b,int n){int s=0;for(int i=0;i<n;++i)s+=a[i]*b[i];return s;}\n' > k.cpp`.
Probe:

```sh
"$LLVM23/bin/clang++" -O2 -S k.cpp -o k.s && "$LLVM23/bin/llvm-mca" -mcpu=apple-m1 k.s | grep -m1 Iterations
"$P2996/bin/clang++-p2996" -O2 -S --target=aarch64-linux-gnu -mcpu=apple-m1 k.cpp -o k-elf.s &&
"$P2996/bin/llvm-mca-p2996" -mtriple=aarch64 -mcpu=apple-m1 k-elf.s | grep -m1 Iterations
```

Expected: `Iterations:        100` twice. PASS if both. On macOS assembly,
`llvm-mca-p2996` stops with `UNREACHABLE executed at .../MCStreamer.cpp`
(`emitSubsectionsViaSymbols only supported on Mach-O targets`): the
assertions build catches what a release build ignores. Homebrew's release
`llvm-mca` 23 reads the same file. Feed p2996's `llvm-mca` ELF assembly, as
above; the instruction timings are the same for the same `-mcpu`.

**R5. Optimisation remarks and build timing.** `-fsave-optimization-record`
with `llvm-opt-report`, and `-ftime-trace` (read by ClangBuildAnalyzer).
Probe: `"$P2996/bin/clang++-p2996" -std=c++26 -ftime-trace -c p.cpp -o p.o && ls p.json`.
PASS if `p.json` is listed (verified).

**R6. Benchmark timing.** `hyperfine --version` prints a version (B1).

## V. Tart VM

**V1. Tart (host).** Probe: `tart --version`. Expected: `2.41.1` or later,
installed with `brew install openai/tools/tart` (the old `cirruslabs` tap
moved). Today: FAIL, not installed.

**V2. Base image pinned by digest (host).** The base image is
`ghcr.io/cirruslabs/macos-golden-gate-xcode:27.2`, the image closest to this
host (macOS 27.2 with Xcode). It replaces D24's `-vanilla` image (D136).
Digest on 2026-11-14:
`sha256:d7641b1d985fd53fbac071c663bf249007b9b387e16b7d576144588acb1d93f9`.
Probe: `tart list | grep golden-gate-xcode`. PASS if the local image was
pulled by that digest.

**V3. Inside the guest (VM).** Run every section above inside the guest.
Expected differences: R2 N/A; DB5 needs the certificate step done while the
golden image was built.

## Report

```text
macOS certification  <hostname or VM name>  <date>
macOS <A1>  Xcode <A2>  SDK <A5>
<id>  PASS|FAIL|N/A  <evidence>
...
Summary: <n> PASS, <n> FAIL, <n> N/A
Missing or wrong: <each FAIL id and its fix>
```

## Appendix: probe sources

### Appendix: reflection probe

```cpp
// refl.cpp
#include <meta>
#include <print>
struct S { int a; double b; };
int main() {
  constexpr auto n = std::meta::nonstatic_data_members_of(
      ^^S, std::meta::access_context::unchecked()).size();
  std::println("members={}", n);
}
```

### Appendix: CMake probe

```cmake
# CMakeLists.txt, next to m.cpp: import std; int main(){ std::println("import std ok"); }
cmake_minimum_required(VERSION 4.5)
project(probe LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_executable(m m.cpp)
```

Run: `cmake -S . -B b -G Ninja -DCMAKE_CXX_COMPILER=<compiler> && cmake --build b && ./b/m`.

### Appendix: sanitizer probe

```cpp
// san.cpp: a data race, a heap overflow, and signed overflow.
#include <climits>
#include <thread>
int g;
int main(int argc, char**) {
  std::thread t([] { g++; }); g++; t.join();
  int* p = new int[2]; int r = p[argc + 1]; delete[] p;
  int big = INT_MAX; big += argc;
  return r + big;
}
```

## Sources

- LLVM at the p2996 commit: `llvm/CMakeLists.txt` (`LLVM_INSTALL_UTILS`),
  `libcxx/CMakeLists.txt:59-64` and `libcxx/docs/Hardening.rst`,
  `compiler-rt/cmake/config-ix.cmake` (sanitizers per OS), `bolt/README.md:12`,
  `lldb/docs/resources/build.rst` (code signing), `lldb/scripts/macos-setup-codesign.sh`,
  `lldb/source/Plugins/Process/gdb-remote/ProcessGDBRemote.cpp` (debugserver lookup).
- LLVM release: `LLVM-23.1.5-macOS-ARM64.tar.xz` contents (D38), and the
  release build script's macOS arm64 settings (no LTO, no PGO).
- GCC: Homebrew `gcc.rb` and `Patches/gcc/gcc-16.2.0.diff` (D33).
- IWYU: `include-what-you-use` `README.md`, branch `clang_21`.
- Tart: `openai/tools/tart` 2.41.1; GHCR manifests for
  `cirruslabs/macos-golden-gate-xcode:27.2`.
- Host probes: run on 2026-11-14 on macOS 27.2.1 (26B131), Xcode 27.2
  (27B52).
