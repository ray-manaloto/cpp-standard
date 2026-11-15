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
   the fix is a separate step. Run the task with mise's auto-install off:
   a plain `mise run` installs any missing tool of this repository's config
   before the task starts, so a check could PASS on a tool the Mac did not
   have. The task refuses to start unless `MISE_AUTO_INSTALL=0` is set. It
   cannot undo an install that a run without it made first; on a fresh Mac
   or VM, the proof that nothing was installed is a listing of
   `$MISE_DATA_DIR/installs` two levels deep from before and after the run
   ([research note](../designs/level-1/research/mise-auto-install.md)).
5. `MISE_AUTO_INSTALL=0 mise run certify:macos --allow-fail` runs every probe below and prints
   the report (the `macos-certify` skill explains it). The host reports
   are in `reports/`, next to this file: the first is
   `macos-host-2026-11-14.txt`, the latest `macos-host-2026-11-15.txt`.

Set these first. Each later probe uses them.

```sh
export P2996="$HOME/.local/share/p2996/current"   # the p2996 install prefix
export LLVM23="$(mise where github:llvm/llvm-project 2>/dev/null)"  # the LLVM 23 tarball (D38)
export PROBE="$(mktemp -d)"; cd "$PROBE"
```

## Usable today (this host, 2026-11-15)

You can start a C++26 static reflection project on this Mac now. These
results came from running the probes below on macOS 27.2.1 with Xcode 27.2.

| Area | State | Workaround until fixed |
|---|---|---|
| clang-p2996 `562409c7`: reflection, `import std` through CMake, ASan, TSan, libc++ hardening `extensive`, assertions | PASS | none needed |
| GCC 16.2.0, the D33 source build (`~/.local/share/gcc-d33/current`): `-freflection`, `import std` through CMake, Xcode SDK sysroot | PASS (G1, G2, G3) | none needed; it loads Homebrew's `gmp`, `mpfr`, `libmpc`, `isl` and `zstd`, so a `brew upgrade` that changes their library versions needs a rebuild (G1); programs it builds load `libstdc++` from the build's own hashed folder, so keep that folder or link with `-static-libstdc++ -static-libgcc` (G1) |
| GCC 16.2.0: TSan, LSan | not on macOS (G4): not built for aarch64 Darwin | use p2996 or clang for TSan |
| GCC with Homebrew C++ libraries (Boost and others) | FAIL: crashes at run time | build C++ dependencies with vcpkg, one triplet per compiler (K1) |
| clang 23.1.5, the LLVM release tarball (D38): config file, its own libc++, `import std`, sanitizers, both linkers, lldb | PASS (C1–C9, DB2) | none needed; `clang`, `clang++` and `lldb` are the tarball's only inside this repository (C9) |
| clang 23: reflection | no (upstream clang has no P2996) | use p2996 or GCC |
| GCC 16.2.0: `-g` with `-fsanitize=address` or `undefined` | PASS (G4, G6) through `.mise/apple-bin/dsymutil` (Apple's); Homebrew's and the tarball's `dsymutil` die with SIGILL | run builds through mise in this repository, or name `/usr/bin/dsymutil` in the CMake toolchain |
| `lldb-p2996`, `lldb-dap-p2996` | PASS since the rebuild with #159849 and the Python rpath (DB3, DB4, DB5 blocker): both load and debug programs, using the in-tree debugserver (DB5) | none needed |
| `llvm-mca-p2996` | PASS (R4) only with ELF assembly; macOS assembly hits an assertion on `.subsections_via_symbols` | feed it ELF assembly (`--target=aarch64-linux-gnu`), or use clang 23's `llvm-mca` |
| p2996 LLVM utilities (FileCheck and others) | PASS (P6) since `-d688c1d4bd0f`, built with `LLVM_INSTALL_UTILS` | none needed |
| include-what-you-use for p2996 | PASS (P8): IWYU 0.25 (`791e69e`) installed into the current p2996 build | pass `-Xiwyu --mapping_file=$P2996/include/c++/v1/libcxx.imp`; IWYU does not model reflection |
| In-tree code-signed debugserver | PASS (DB5) on `current` (`-d688c1d4bd0f`; first on `-9f4a6fe02298`, built with the `lldb_codesign` key limited to `/usr/bin/codesign`), with Developer mode enabled (A6) | none needed; `-37f3cecb1624` used Xcode's debugserver |
| p2996 with `-fuse-ld=lld` | FAIL, known upstream (P10; does not fail strict mode): LLVM 21's `lld` cannot read the macOS 27 SDK's `.tbd` files | use Apple `ld`, the default |
| XRay | not on macOS (T7): the runtime archives exist but do not work on Darwin, in p2996 and clang 23 alike | `xctrace` Time Profiler |
| Developer mode, Xcode first launch | PASS (A3, A6): first launch done with `sudo xcodebuild -runFirstLaunch`; Developer mode enabled | none needed; on a new Mac or VM run `sudo xcodebuild -runFirstLaunch` and `sudo DevToolsSecurity -enable` (DB5 step 5) |
| p2996 coverage | PASS with the matching tools | use `llvm-cov-p2996 gcov`, never another LLVM's |
| `g++` / `gcc` on `PATH` | Apple clang (`/usr/bin/g++`, `/usr/bin/gcc`); no stray mise shims (B2 PASS) | call `g++-16` by name |
| `ccache` on `PATH` | not installed (B2 PASS) | use sccache (D9); ccache does not cache C++20 modules |
| Tart 2.41.1 | PASS (V1), from mise | none needed; V2 and V3 wait for the image pull and a guest run |

## The end state

| Component | Source | Built from source? | Why |
|---|---|---|---|
| Xcode 27.2 + Command Line Tools 27.2 | Apple | no | The macOS SDK, Apple `ld`, Apple `lldb` and `debugserver`, and Instruments (`xctrace`, CPU Counters). The full Xcode is needed for the profiling tools (D136). (`leaks`, `heap`, `vmmap` and `malloc_history` also ship with macOS in `/usr/bin`.) |
| LLVM / clang 23 + libc++ | the LLVM release tarball `LLVM-<ver>-macOS-ARM64.tar.xz` via mise `github:llvm/llvm-project` | no | The daily compiler. It replaces Homebrew LLVM (D38). The tarball has libc++ with `libc++.modules.json`, every macOS sanitizer runtime, clangd, clang-tidy, lldb, llvm-mca and `ld64.lld`. It has no config file, so we add one (C2). |
| GCC 16.2.0 + libstdc++ | `gcc-16.2.0.tar.xz` + Iain Sandoe's Darwin patch, with Homebrew's `gcc.rb` as the template | **yes** | No package gives an exact, checksummed GCC for macOS 27 (D33). The build sets the sysroot to the current SDK. |
| clang-p2996 + libc++ | `bloomberg/clang-p2996` at a pinned commit | **yes** | No prebuilt binary exists. It is the reflection reference compiler (D30). |
| include-what-you-use for p2996 | IWYU `clang_21` branch, built out of tree against p2996 | **yes** | p2996 is based on LLVM 21. Homebrew's IWYU uses clang 23 and cannot parse `^^` (D136). |
| CMake 4.5, Ninja, sccache, vcpkg, gcovr, Doxygen, hyperfine | mise | no | Build, cache, dependencies, coverage report, docs, timing. |
| Tart | mise, `aqua:openai/tart` (pinned in `.mise/conf.d/vm.toml` and in the dotfiles global config) | no | VM host (host only). Never from Homebrew: every tool is mise-managed. |

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

**A2. Full Xcode selected.** Why: Instruments, `xctrace` and the
Apple-signed `debugserver` come only with Xcode (D136). Probe:

```sh
xcode-select -p; xcodebuild -version
```

Expected: `/Applications/Xcode.app/Contents/Developer` and `Xcode 27.2`.
PASS if the path is inside `Xcode.app` and the version is 27.x. FAIL if the
path is `/Library/Developer/CommandLineTools`.

**A3. Xcode licence accepted and first launch done.** Probe:
`xcodebuild -checkFirstLaunchStatus; echo $?`. Expected: `0`. Fix:
`sudo xcodebuild -runFirstLaunch` and `sudo xcodebuild -license accept`.
Today (2026-11-15): PASS, exit status `0`, after the owner ran
`sudo xcodebuild -runFirstLaunch`; before that, FAIL with exit status `69`.

**A4. Command Line Tools installed.** Why: Homebrew and some build scripts
look there. Probe: `pkgutil --pkg-info=com.apple.pkg.CLTools_Executables |
grep version`. Expected: `version: 27.2...`. PASS if the major is 27.

**A5. The active SDK.** Why: every compiler must compile against the same
SDK as the OS. Probe: `xcrun --show-sdk-path; xcrun --show-sdk-version`.
Expected: a path ending `MacOSX.sdk` inside Xcode, and `27.2`. PASS if the
SDK major matches A1.

**A6. Debugging attaches without a prompt.** Why: a debugger that asks for
a password cannot run unattended. Probe: `DevToolsSecurity -status`. PASS if
`enabled`. If `disabled`, record A6 after DB5: PASS if the DB5 breakpoint
line passes without a password prompt; otherwise FAIL, and the fix is
`sudo DevToolsSecurity -enable`. Today: PASS with `enabled` (2026-11-14):
lldb-p2996 stops at a breakpoint with the self-signed in-tree debugserver
(DB5) and no prompt. With `disabled`, Xcode's Apple-signed `debugserver`
attached without a prompt, but the self-signed one opened a "Developer
Tools Access" password dialog (reported by the build agent), although the
account is in the `_developer` group (`id -Gn`). So a Mac or VM that uses
the in-tree debugserver needs `sudo DevToolsSecurity -enable` (DB5 step 5).

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

PASS if no mise shim on `PATH` for `g++`, `c++`, `clang++` or `ccache` lacks an
active version (`mise which <name>` fails), `g++` is GCC 16, Apple's
`/usr/bin/g++` or absent, and `ccache` is absent or works. Apple's `g++` is
allowed because our builds call `g++-16` by name (DL-591 in dotfiles). Today
(2026-11-15): PASS, after the inactive mise tools `ccache`, `conda:gxx` and
`conda:clangxx` were uninstalled: their `g++`, `c++`, `clang++` and `ccache`
shims errored or fell through to Apple clang (FAIL on 2026-11-14). Fix, if
it comes back: `mise uninstall` the tool behind the shim, then `mise reshim`.

**B3. sccache is the launcher.** Why: ccache does not cache C++20 modules
(D9). Probe: `sccache --show-stats | head -3`. PASS if it prints statistics.

## C. LLVM / clang 23 (release tarball)

**C1. Installed from the tarball.** Probe:

```sh
"$LLVM23/bin/clang++" --version | head -1
```

Expected: `clang version 23.x.y` (not `Homebrew clang`). PASS if the path is
the mise install and the version is 23. Today (2026-11-15): PASS, 23.1.5
(`392dfff`) from the mise install.

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

PASS if it names `arm64-apple-darwin-clang++.cfg` and the `-isysroot` that
clang really passes (the `"-isysroot" "<path>"` pair in the same `-###`
output) is the SDK `xcrun --show-sdk-path` prints now. Reading `-###`, not
the config file, also catches a config that stops including
`@arm64-apple-darwin.cfg`. The install writes that path once; it follows Xcode updates in place (it is the
unversioned `MacOSX.sdk` link inside Xcode.app), but not an `xcode-select`
switch or a moved Xcode. Fix then: `mise install --force github:llvm/llvm-project`.

**C3. Links its own libc++.** Probe:

```sh
printf '#include <print>\nint main(){std::println("ok");}\n' > p.cpp
"$LLVM23/bin/clang++" -std=c++26 p.cpp -o p && ./p && otool -L p | grep c++
```

Expected: `ok`, and `libc++.1.dylib` from the tarball's `lib`, not
`/usr/lib`. PASS if both. `otool -L` prints `@rpath/libc++.1.dylib` (the
config file adds an rpath to the tarball's `lib`), so check the file dyld
really loads: `DYLD_PRINT_LIBRARIES=1 ./p 2>&1 | grep -m1 libc++.1`, and
compare real paths, because the mise install directory is reached through a
link.

**C4. `import std` through CMake.** Why: `-print-file-name=libc++.modules.json`
must resolve, or CMake stops with "Could not find `libc++.modules.json`".
Use the CMake project in [Appendix: CMake probe](#appendix-cmake-probe) with
`-DCMAKE_CXX_COMPILER="$LLVM23/bin/clang++"`. Expected: `import std ok`.
Today (2026-11-15): PASS on the tarball. Homebrew's clang fails it,
because Homebrew installs the file at `lib/c++/`.

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

Expected: `ok` twice. Today (2026-11-15): PASS on the tarball.

**C9. Plain names are the tarball's.** Why: D38 makes the tarball this
project's LLVM, but the global mise path puts Homebrew LLVM first.
`.mise/conf.d/llvm.toml` puts the tarball's `bin` ahead of it inside this
repository. Probe, from the repository root:
`for t in clang clang++ lldb; do command -v $t; done`. PASS if each resolves,
by real path, into the tarball's `bin`. Today (2026-11-15): PASS.

## G. GCC 16.2 (source build)

**G1. Version and origin.** Probe: `g++-16 --version | head -1; g++-16 -v 2>&1 | grep -o -- "--with-pkgversion='[^']*'"`.
Expected: `16.2.0`, built by cpp-standard (D33). The certify task uses
`~/.local/share/gcc-d33/current/bin/g++-16` when it exists, else the
`g++-16` on `PATH`. Today (2026-11-15): PASS on the D33 build
`16.2.0-9f99e2b94d93` (pkgversion `cpp-standard GCC 16.2.0 (D33
9f99e2b94d93)`), installed beside Homebrew GCC, which is untouched. Caveat:
its `cc1plus` links Homebrew's `gmp`, `mpfr`, `libmpc`, `isl` and `zstd`
dynamically (`otool -L`), so a `brew upgrade` that changes one of their
library versions (for example `libisl.23`) breaks the compiler until it is
rebuilt with a new inputs hash. Second caveat: a program it links loads
`libstdc++.6.dylib` through `@rpath`, and the rpaths it records are the
build's hashed folder (`~/.local/share/gcc-d33/16.2.0-9f99e2b94d93/lib` and
its `lib/gcc/aarch64-apple-darwin27/16`), not `current` (`otool -l`,
`LC_RPATH`, 2026-11-15). Removing that folder after a rebuild breaks every
program built with it. Keep old build folders while programs built with
them are in use, or link with `-static-libstdc++ -static-libgcc`: the
program then depends only on `/usr/lib/libSystem.B.dylib` (`otool -L`) and
runs (checked 2026-11-15).

**G2. Reflection and `import std`.** Probe: compile `refl.cpp` from
[Appendix: reflection probe](#appendix-reflection-probe) with
`g++-16 -std=c++26 -freflection`, then the CMake probe with
`-DCMAKE_CXX_COMPILER=g++-16`. Expected: `members=2` and `import std ok`.

**G3. Sysroot matches the SDK.** Why: GCC was configured with a fixed
`--with-sysroot`; an old SDK hides new APIs and can mismatch the OS headers.
Probe: `g++-16 -v 2>&1 | grep -o -- '--with-sysroot=[^ ]*'`. PASS if the path
exists and its SDK major equals A1. Today (2026-11-15): PASS on the D33 build
(Xcode's `MacOSX.sdk`, 27.2). Homebrew GCC fails it
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

Expected: Apple's `dsymutil` (`/usr/bin/dsymutil`, Xcode's, or a wrapper
that runs it) and `link-ok`. Homebrew LLVM's and the LLVM 23 tarball's
`dsymutil` (both 23.1.5) stop the link with
`dsymutil terminated with signal 4 [Illegal instruction: 4]`. Fix: inside
this repository, `.mise/conf.d/llvm.toml` puts `.mise/apple-bin/dsymutil`, a
wrapper that execs `/usr/bin/dsymutil`, first on `PATH`. Today (2026-11-15):
PASS through that wrapper. The fix holds only where mise sets `PATH`
(`mise run`, `mise x`, or a shell with mise activated in this repository).
An IDE started without mise, a bare `sh`, or a CMake run outside mise still
finds Homebrew's and fails; run builds through mise, or name
`/usr/bin/dsymutil` in the CMake toolchain.

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

Caveat, as for GCC (G1): the config file links `libc++` and `libunwind`
dynamically and adds `-rpath` to the build's hashed prefix (today
`562409c…-d688c1d4bd0f/lib`), not `current`. A program built with p2996
loads `@rpath/libc++.1.dylib` and `@rpath/libunwind.1.dylib` from there, with
no fallback to the system `libc++`, so deleting that prefix breaks it.
`-static-libstdc++` does not help (clang ignores it on macOS). Keep an old
prefix until nothing built with it is in use, or link the static archives:
`clang++-p2996 --no-default-config -isysroot "$(xcrun --show-sdk-path)"
-std=c++26 -nostdlib++ x.cpp "$P2996/lib/libc++.a" "$P2996/lib/libc++abi.a"
"$P2996/lib/libunwind.a"`. That program depends only on
`/usr/lib/libSystem.B.dylib` (`otool -L`), and a throw/catch test passes
(checked 2026-11-15; the dotfiles lead found the deleted-prefix failure,
`dyld: Library not loaded: @rpath/libunwind.1.dylib`).

**P5. Projects present.** Probe:

```sh
ls "$P2996/bin" | grep -cE '^(clangd|clang-tidy|clang-format|clang-include-cleaner|clang-query|clang-doc|scan-build|ld64.lld|llvm-mca|llvm-cov|llvm-profdata|llvm-xray|lldb|lldb-dap|mlir-opt)-p2996$'
"$P2996/bin/clang++-p2996" -O2 -mllvm -polly -c -x c++ /dev/null -o /dev/null && echo polly-ok
```

Expected: `15` and `polly-ok`. Not expected after the D136 rebuild: `flang`,
`llvm-bolt`, `perf2bolt` (today they are present; harmless, but they make the
build longer).

**P6. LLVM utilities.** Probe: `ls "$P2996/bin" | grep -E '^(FileCheck|not|count|yaml2obj)'`.
PASS if all four (with or without the `-p2996` suffix). Today (2026-11-15):
PASS on `-d688c1d4bd0f`, the first build with `LLVM_INSTALL_UTILS=ON`
(`-9f4a6fe02298` FAILed: the option was off).

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
IWYU commit nearest the date p2996 branched from LLVM main. Today
(2026-11-15): PASS, `include-what-you-use 0.25 (git:791e69e)` on p2996
`562409c`. `-d688c1d4bd0f` installs it itself (`bin/include-what-you-use`,
linked into `view/` as `include-what-you-use-p2996`); on `-9f4a6fe02298`
it was installed by hand. Pass libc++'s own mapping,
`-Xiwyu --mapping_file=$P2996/include/c++/v1/libcxx.imp`, or IWYU suggests
private headers such as `<__vector/vector.h>`. IWYU does not model
reflection; run it on files without `^^`.

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
base whose `lld` reads that SDK (LLVM 23's does, C8). **Known upstream:**
the report prints it as FAIL and lists it under "Known upstream", but it does
not fail strict mode or V3, because no change on this Mac can fix it. Only
that exact cause is exempt: lld cannot load `libSystem.tbd` with `unknown
architecture` at `arm64e.x1-macos`. Any other P10 failure (no p2996, another
linker or TAPI error) is an ordinary FAIL.

## D. Debuggers

Three debuggers are certified: Apple lldb, LLVM 23 lldb, lldb-p2996 (D136).

**DB1. Apple lldb.** Probe: `xcrun lldb --version; xcrun lldb -b -o 'script print(1+1)'`.
Expected: `lldb-2103...` (today `lldb-2103.0.34.407`) and `2`. PASS if
both.

**DB2. LLVM 23 lldb.** Probe: `"$LLVM23/bin/lldb" --version`. Expected:
`lldb version 23.x`. The tarball lldb is built without Python, so `script`
fails: expected, not a FAIL. Its `debugserver` is ad-hoc signed; if attach
fails, set `LLDB_DEBUGSERVER_PATH` to Xcode's (the path in DB5's earlier results).

LLVM 23 already has the upstream fix for the offset wrap described under the
DB5 blocker (llvm/llvm-project #159849, in LLVM 22 and later), so its lldb
should load programs on macOS 27. Load probe:
`"$LLVM23/bin/lldb" -b -o 'target create /bin/ls'; echo $?`. PASS if it
prints `Current executable set to '/bin/ls'` and exits 0; FAIL on any other
exit code. Today (2026-11-15): PASS, `lldb version 23.1.5` and
`target create` exit 0.

**DB3. lldb-p2996 starts and runs Python.** Probe:

```sh
"$P2996/bin/lldb-p2996" -b -o 'script print(40+2)'
otool -l "$P2996/lib/liblldb.dylib" | grep -A2 LC_RPATH | grep path
ls "$HOME/.local/share/mise/installs/python/3.15/lib/libpython3.15.dylib"
```

Expected: `42`, an `LC_RPATH` entry `.../mise/installs/python/3.15/lib`, and
that directory holds `libpython3.15.dylib`. PASS if all three. Today: PASS on
the p2996 build that carries fix 1 (2026-11-14): `42`, and the second
`LC_RPATH` is `.../mise/installs/python/3.15/lib`. A build without fix 1
fails with `dyld: Library not loaded: @rpath/libpython3.15.dylib`, because
its only rpath is `@loader_path/../lib`.

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
PASS if it prints usage (`OVERVIEW: LLDB DAP`). Today: PASS on the
build that carries DB3 fix 1; a build without it fails with the same missing
`libpython3.15.dylib` as DB3.

DB4 session probe: debug a program through `lldb-dap-p2996` with the client
in [Appendix: lldb-dap probe](#appendix-lldb-dap-probe). It launches the
program, sets a breakpoint, reads `v` and `s` from the locals, continues,
and checks the exit code. PASS if it ends with `PASS` and exits 0: the
breakpoint is `verified`, the stop reason is `breakpoint`, `v` has children
`1 2 3`, `s` is `"p2996"`, and the program exits 0. On any failure it prints
one `FAIL: <reason>` line and exits 1. This includes a reply that lacks a
field the probe needs, a wrong `lldb-dap` path, and 60 seconds without the
message the probe is waiting for. Today:
PASS (2026-11-14, run twice). With line 100, past the end of the file, it prints
`breakpoint verified: False` and `FAIL: program exited without stopping at
line 100`, and exits 1. An earlier hand-run session also showed `evaluate`
of `pt.x + v.size()` giving `10`.

**DB5. In-tree debugserver, code-signed.** Why: `LLDB_USE_SYSTEM_DEBUGSERVER=OFF`
makes the debugserver match lldb-p2996 exactly; macOS refuses to let an
unsigned debugserver attach to a process. lldb looks for it in
`LLDB_DEBUGSERVER_PATH` first, then in its support directory
(`ProcessGDBRemote.cpp`). Probe:

```sh
DS="$(find -L "$P2996" -name 'debugserver*' -type f 2>/dev/null | head -1)"; echo "$DS"
codesign -dvv "$DS" 2>&1 | grep -E 'Authority|Signature'
codesign --verify --strict -v "$DS"
"$P2996/bin/clang++-p2996" -std=c++26 -g p.cpp -o pd
"$P2996/bin/lldb-p2996" -b -o 'b main' -o run -o 'frame variable' -o kill pd 2>&1 | grep -m1 'stop reason'
```

Expected: a path inside `$P2996`, `Authority=lldb_codesign`, `valid on
disk` and `satisfies its Designated Requirement`, and
`stop reason = breakpoint 1.1`. `codesign -dvv` only reads the signature;
`codesign --verify --strict` checks that the file still matches it.
`current` points at a build's `view/` folder, where debugserver is linked
as `bin/debugserver-p2996`; hence `'debugserver*'`. To check a build before
it becomes `current`, set `P2996` to that build's `<prefix>/view`.

Today (2026-11-15): PASS on `current`, `-d688c1d4bd0f` (`previous` is
`-9f4a6fe02298`): `Authority=lldb_codesign`, `verify --strict` ok,
`breakpoint 1.1`, and `ps` lists the build's own debugserver.

Install order for a new p2996 build (the dotfiles p2996 `install` task):
first `install --keep-current`, which assembles and verifies the build but
leaves `current` where it is; then this probe with `P2996` set to the new
build's `<prefix>/view`; then a plain `install`, which makes it `current`.
A build whose debugserver fails DB5 then never becomes `current`. Keep the
old prefix until nothing built with it is in use (P4 caveat).

Earlier: PASS on `-9f4a6fe02298` (2026-11-14, rerun after the
build agent made it `current`; `previous` was then `-b6e46c1709ce`;
Developer mode enabled by the owner with `sudo DevToolsSecurity -enable`,
A6): `$P2996/bin/debugserver-p2996`, `Authority=lldb_codesign`,
`valid on disk`, `satisfies its Designated Requirement`, and
`stop reason = breakpoint 1.1`. `ps`, run inside the stopped session
(`platform shell /bin/ps -axo pid=,comm=`), lists the build's own
`bin/debugserver`, not Xcode's. The lldb-dap probe (DB4) also
passes on this build. To see which debugserver it starts, add
`subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,comm="])` to the probe
right after its `v =` line, while the program is stopped at the
breakpoint. On `current` it lists the same `bin/debugserver`; on
`-37f3cecb1624`, which had no debugserver of its own, it listed Xcode's.
No password dialog appeared, and no debugserver was left running.

Before the switch, `-9f4a6fe02298` (2026-11-14) also passed, built and
installed by the build agent after the owner limited the `lldb_codesign`
key to `/usr/bin/codesign` (step 2). The build agent reports that its
three signing steps (the `build.py` preflight, CMake's `llvm_codesign`,
the `install.py` re-sign) ran with no keychain dialog; step 2 records the
check of the CMake-signed copy. With `P2996` set to its `view/`:
`bin/debugserver-p2996`, `Authority=lldb_codesign`, `valid on disk`,
`satisfies its Designated Requirement`, `--version` exits 0,
the entitlement `com.apple.security.cs.debugger` kept, and
`stop reason = breakpoint 1.1`. `ps` in the stopped session lists the
build's own `bin/debugserver`. The lldb-dap probe with the `ps` line also
passes and lists the same debugserver. No debugserver was left running.
It has the same p2996 commit as `-b6e46c1709ce`; the build agent reports
that a build input changed, so the ID changed.

Earlier results:

- `-b6e46c1709ce` (now `previous`), reinstalled (2026-11-14): PASS, the
  same results as Today, including the lldb-dap probe with the `ps`
  line. Built before the key limit.
- `-b6e46c1709ce`, first install (2026-11-14): FAIL.
  `bin/debugserver` exists and shows `Authority=lldb_codesign`, but
  `codesign --verify --strict -v` prints `invalid signature (code or
  signature have been modified)`. The file changed after it was signed:
  `Signed Time` is 19:24:41 and its modification time is 19:31.
  `debugserver --version` exits 137 (SIGKILL), with no output, most
  likely because of the kernel's code-signing check (the system log did
  not record the reason). The session prints
  `error: failed to get reply to handshake packet within timeout of 6.0
  seconds`. Cause, from the build agent: `cmake --install` adds the
  install rpaths with `install_name_tool` after the build tree signs
  debugserver. The build agent's fixed install re-signs
  `bin/debugserver` last with
  `codesign --force --sign lldb_codesign
  --preserve-metadata=identifier,entitlements,flags,runtime`, and refuses
  the build unless `codesign --verify --strict` and `debugserver
  --version` pass.
- `-37f3cecb1624` (moved out of the p2996 prefix on 2026-11-14; it is in
  the macOS Trash, so it can be restored until the Trash is emptied; the
  build agent reports it first checked that no link resolved into it):
  FAIL on the first three lines. There was no debugserver under it
  because that p2996 build set `LLDB_USE_SYSTEM_DEBUGSERVER=ON` (its
  `CMakeCache.txt` had `LLDB_USE_SYSTEM_DEBUGSERVER:BOOL=ON`). Building one
  signed with `lldb_codesign` also needs that certificate, which this Mac
  now has (installed 2026-11-14). The breakpoint part passed: lldb-p2996
  stopped at the breakpoint using Xcode's debugserver
  (`/Applications/Xcode.app/Contents/SharedFrameworks/LLDB.framework/Resources/debugserver`,
  seen in `ps` during the run; the same file as
  `.../LLDB.framework/Versions/A/Resources/debugserver`). `find -L` is
  needed because `$P2996` is a link. The Xcode-debugserver fallback does
  not need that build: `current`'s `lldb-p2996` with
  `LLDB_DEBUGSERVER_PATH` set to Xcode's debugserver also stops at the
  breakpoint, and `ps` lists Xcode's debugserver (2026-11-14).

Steps (from `lldb/docs/resources/build.rst`, "Code Signing on macOS"):

1. Create the signing certificate once per Mac or VM, as an admin:
   `sudo env TMPDIR="$TMPDIR" bash lldb/scripts/macos-setup-codesign.sh`
   from the p2996 source tree (this form worked on 2026-11-14). Plain
   `sudo` fails: it empties `$TMPDIR`, so the script tries to write
   `/lldb_codesign.tmpl`. Running it without `sudo` should also work,
   since it calls `sudo` itself for the keychain steps, but that form is
   untested here.
   It creates a self-signed `lldb_codesign` identity in
   `/Library/Keychains/System.keychain` and trusts it for code signing. It
   needs an admin password; in a VM, run it while building the golden image.
   It imports the private key with `-A`, so the key's sign entry lists no
   application (`applications: <null>`); its partition list is
   `apple-tool:`.
2. Check it: `security find-certificate -c lldb_codesign /Library/Keychains/System.keychain`
   prints the certificate.

   Optional hardening, once this check finds the certificate (done on
   this Mac, 2026-11-14): limit the key to `/usr/bin/codesign`. The p2996
   recipe signs in three places. In the dotfiles repository,
   `python/toolchains/p2996/src/p2996/build.py` (the preflight) and
   `python/toolchains/p2996/src/p2996/install.py` (the re-sign after
   install) call `codesign`. lldb's CMake step signs debugserver through
   `llvm_codesign` in `llvm/cmake/modules/AddLLVM.cmake`, whose
   `CMAKE_CODESIGN` defaults to `xcrun codesign` (read in the p2996
   source at `562409c79`, not run). Here both `codesign` and
   `xcrun -f codesign` resolve to `/usr/bin/codesign`.
   Open Keychain Access:
   `open "/System/Library/CoreServices/Applications/Keychain Access.app"`.
   Then System Keychains, System, My Certificates, expand `lldb_codesign`,
   double-click "Imported Private Key", Access Control. Choose "Confirm
   before allowing access" and leave "Ask for Keychain password"
   unchecked. Under "Always allow access by these applications" click
   "+", press ⌘⇧G, type `/usr/bin/codesign`, and Add. Save Changes with an
   admin password. Check (it reads the first "Imported Private Key" in the
   System keychain; if that keychain holds other imported keys, confirm
   the entry belongs to `lldb_codesign`):

   ```sh
   security dump-keychain -a /Library/Keychains/System.keychain 2>/dev/null |
     awk '/"Imported Private Key"/{f=1} f&&/^access:/{a=1} a{print} a&&/^keychain:/{exit}' |
     grep -A5 ' sign$'
   ```

   Expected: one application, `0: /usr/bin/codesign (OK)` with
   `requirement: identifier "com.apple.security.codesign" and anchor apple`.
   Then re-run DB5. On 2026-11-14, with the limit in place, the `codesign`
   commands that `build.py`'s preflight and `install.py`'s re-sign run were
   run by hand on scratch copies. Both finished with rc 0 and no prompt.
   A breakpoint session through the re-signed debugserver copy
   (`LLDB_DEBUGSERVER_PATH`) stopped at the breakpoint. Later that day the
   build agent ran a full p2996 build and install with the limit in place
   (`-9f4a6fe02298`). It reports that the preflight, the CMake signing
   step and the re-sign all ran with no dialog, and that it reuses one
   build tree, configured with `--fresh`, where ninja re-linked and
   re-signed debugserver during this build. Checked here: that build-tree
   `bin/debugserver` shows `Authority=lldb_codesign` and
   `Signed Time` 21:06:17 local, after the limit and before the installed
   copy's re-sign (21:13:08), so the CMake step signed under the limit.
   DB5 passes on that build, now `current` ("Today" above). Whether
   other apps are now refused is untested, because that test opens a
   dialog.
3. Configure p2996 with `-DLLDB_USE_SYSTEM_DEBUGSERVER=OFF` and
   `-DLLDB_CODESIGN_IDENTITY=lldb_codesign`, and stop the build before
   configure if step 2 finds no certificate. CMake does not stop on its
   own (`lldb/tools/debugserver/source/CMakeLists.txt`,
   `get_debugserver_codesign_identity`): with `LLDB_CODESIGN_IDENTITY` set
   and the certificate missing, it only warns and keeps that identity, so
   the build reaches the signing step without a certificate; with neither,
   it signs debugserver ad hoc, and whether that can attach here is
   untested.
4. Rebuild and install; run the DB5 probe. Anything that edits
   debugserver after it is signed (`install_name_tool`, `strip`, an rpath
   step) breaks the signature. Leave debugserver out of such steps, or
   sign it again as the last step with its entitlements file
   (`lldb/tools/debugserver/resources/debugserver-macosx-entitlements.plist`).
5. Enable Developer mode once per Mac or VM, as an admin:
   `sudo DevToolsSecurity -enable`, then check that
   `DevToolsSecurity -status` prints `enabled`. Without it, the
   self-signed debugserver opened a password dialog (A6, reported by the
   build agent), which blocks unattended runs. In a VM, do it in the
   golden image. The setting covers the whole Mac: any program running as a
   `_developer` member can then attach a debugger to that user's other
   processes without a password, except hardened-runtime binaries that
   lack `get-task-allow`. `sudo DevToolsSecurity -disable` turns it off.
6. If the certificate cannot be made (no admin), keep
   `LLDB_USE_SYSTEM_DEBUGSERVER=ON`: lldb-p2996 then uses Xcode's
   debugserver, which worked without Developer mode. Record DB5 as FAIL
   with that workaround.

**DB5 blocker: lldb-p2996 crashed loading any program on macOS 27.** Fixed
by the cherry-pick below; keep the probe, and report it on the DB5 line if
it fails again. Probe:
`"$P2996/bin/lldb-p2996" -b -o 'target create /bin/ls'; echo $?`. Expected:
exit 0. Today: PASS, exit 0 on the build with #159849 (2026-11-14). Before
that build: exit 132 (128 + signal 4, `SIGILL`). The crash report in
`~/Library/Logs/DiagnosticReports/` says `EXC_BAD_ACCESS`
(`KERN_PROTECTION_FAILURE`), "Thread stack size exceeded due to excessive
recursion", with `ParseTrieEntries` calling itself, and names the signal as
`SIGILL`; so the exit code is this stack overflow, not a separate fault.
Apple `lldb` loads the same program.

Why: lldb reads each system library's symbol table, string table and export
trie out of the dyld shared cache it has mapped. It adds the distance from
the library's `__TEXT` to the cache's `__LINKEDIT` to the library's load
command offsets (`ObjectFileMachO::ParseSymtab`); in LLVM 21 the export trie,
dyld info, indirect symbol and function starts offsets are still 32-bit
fields. On macOS 27
that distance is more than 4 GiB for many libraries (`libcorecrypto`:
`0x1619b2000`), so the sum wraps. lldb then parses unrelated bytes as an
export trie; when those bytes happen to point back at themselves, the parser
recurses until it crashes. Verified on this Mac, on the build that did
not yet carry #159849:

- lldb-p2996 read `libcorecrypto`'s trie 4 GiB below the real one. The real
  trie is well formed: 1,140 exports, depth 12, no node reached twice.
- Of the 15 libraries `/bin/ls` loads, loaded one at a time, every library
  whose symbol table parse crashed lldb had a wrapping offset, and none
  without one crashed it. `libcopyfile` wrapped without crashing, so lldb
  read the wrong symbols for it silently.

Upstream fixed this in llvm/llvm-project #159849 ("Local structs for larger
VA offsets", September 2025), which moves those offsets into 64-bit structs.
It is in LLVM 22 and later and in Apple's `swiftlang/llvm-project`, but not in
`release/21.x`, which the p2996 fork is based on. Later upstream trie-parser
changes (#202773, #203055) only reject a cyclic trie, so they would stop the
crash but not the wrong reads, and they do not apply to the fork.

Fix: cherry-pick #159849 into the p2996 build; it applies cleanly to the
fork. Verified on the build that carries it (2026-11-14): the probe above
exits 0; each of the 15 libraries `/bin/ls` loads parses on its own,
including the 8 that crashed (`libcopyfile` now reports 181 symbols, not the
191 it read from the wrong place); and a C++26 program built with p2996 stops
at a breakpoint, `frame variable` prints a `std::vector`, and
`image lookup -n printf` finds it in `libsystem_c.dylib`.

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
`for f in realtime type; do "$P2996/bin/clang++-p2996" -std=c++26 -fsanitize=$f p.cpp -o t_$f && echo $f-ok; done`,
then build [the fuzz probe](#appendix-fuzz-probe) with `-fsanitize=fuzzer`
and run it with `-runs=16`. PASS if both print `-ok` and the fuzzer exits 0
after `Done 16 runs`. A program with its own `main` and no
`LLVMFuzzerTestOneInput` is not a fuzz target, so it no longer counts.

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

**V1. Tart (host).** Why: every tool is mise-managed. Tart is pinned in
`.mise/conf.d/vm.toml` (`tart` in mise's registry is `aqua:openai/tart`, the
release `tart.tar.gz` with sha256 checksums; macOS only) and, at the same
version, in the dotfiles global mise config. Inside this repository the
repository pin wins, so two pins that drift apart cannot both pass. Probe:
`tart --version`, `mise ls tart --json` and `mise which tart`. PASS if
`tart --version` equals the repository pin (`2.41.1`) and `tart` on `PATH`
is that mise install (or a mise shim for it), not Homebrew's or another
copy. The evidence names the dotfiles global pin when it differs or is
missing. Today (2026-11-15): PASS, `tart 2.41.1 from mise`, installed with
`mise install --locked`; the repository pin and the dotfiles global pin
resolve to one install folder, the `tart.app` bundle is whole and signed
by `Developer ID Application: Cirrus Labs, Inc.`, and the lock checksum
(`.mise/mise.lock`) matches the release's `tart_2.41.1_checksums.txt`.
Right after that install, V1 first reported "not installed": mise's
environment cache (`env_cache`, on in the global config) still held the
PATH from before. The task now re-runs itself once with
`MISE_ENV_CACHE=0`, so no check sees a stale PATH.

**V2. Base image pinned by digest (host).** The base image is
`ghcr.io/cirruslabs/macos-golden-gate-xcode:27.2`, the image closest to this
host (macOS 27.2 with Xcode). It replaces D24's `-vanilla` image (D136).
Digest on 2026-11-14:
`sha256:d7641b1d985fd53fbac071c663bf249007b9b387e16b7d576144588acb1d93f9`.
Probe: `tart list | grep golden-gate-xcode`. PASS if the local image was
pulled by that digest. Today: not run; Tart is not installed (V1).

**V3. Inside the guest (VM).** Run every section above inside the guest.
Expected differences: R2 N/A; DB5 needs the certificate (step 1) and
Developer mode (step 5, also A6) set up while the golden image was built,
and A3 needs `sudo xcodebuild -runFirstLaunch` there too, unless the base
image already ran it (untested). These are one-time settings per Mac or
VM: the host's A3 and A6 PASS says nothing about a guest.
Today: not run; Tart is not installed (V1).

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
  // Many racing increments: a single one fired TSan only 19 of 20 runs.
  std::thread t([] { for (int i = 0; i < 100000; ++i) g++; });
  for (int i = 0; i < 100000; ++i) g++;
  t.join();
  int* p = new int[2]; int r = p[argc + 1]; delete[] p;
  int big = INT_MAX; big += argc;
  return r + big;
}
```

### Appendix: fuzz probe

```cpp
// fuzz.cpp: a libFuzzer target; -fsanitize=fuzzer supplies main.
#include <cstddef>
#include <cstdint>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* d, size_t n) {
  return n > 0 && d[0] == 0xff ? 0 : 0;
}
```

### Appendix: lldb-dap probe

Two files: the program it debugs, and a small client that speaks the Debug Adapter Protocol to `lldb-dap` over stdio, the way an editor does. It needs only the Python standard library.

```cpp
// dap.cpp: the program the lldb-dap probe debugs.
#include <cstdio>
#include <string>
#include <vector>
struct Point { int x; double y; };
int main() {
  std::vector<int> v{1, 2, 3};
  std::string s = "p2996";
  Point pt{7, 2.5};
  std::printf("%zu %s %d\n", v.size(), s.c_str(), pt.x);  // breakpoint line: 10
  return 0;
}
```

Run (exit 0 and a last line `PASS` on success; line 10 is the `printf` line):

```sh
"$P2996/bin/clang++-p2996" -g -std=c++26 dap.cpp -o dapd
python3 -I dap_probe.py "$P2996/bin/lldb-dap-p2996" dapd dap.cpp 10
```

```python
# dap_probe.py: drive lldb-dap over stdio the way an editor does.
# Usage: python3 -I dap_probe.py <lldb-dap> <program> <source> <line>
# Prints PASS and exits 0, or prints one "FAIL: <reason>" line and exits 1.
import json, queue, subprocess, sys, threading, time

try:
    dap, prog, src, line = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    p = subprocess.Popen([dap], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
except (IndexError, ValueError, OSError) as e:  # bad arguments or lldb-dap path
    sys.exit(f"FAIL: {type(e).__name__}: {e}")
seq, pending, inbox = 0, [], queue.Queue()

def send(cmd, args=None):
    global seq
    seq += 1
    body = json.dumps({"seq": seq, "type": "request", "command": cmd,
                       "arguments": args or {}}).encode()
    p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    p.stdin.flush()
    return seq

def reader():  # runs in a thread, so wait() can time out while lldb-dap is silent
    try:
        while True:
            hdr = b""
            while not hdr.endswith(b"\r\n\r\n"):
                c = p.stdout.read(1)
                if not c:
                    inbox.put("lldb-dap exited")
                    return
                hdr += c
            n = int(hdr.decode().lower().split("content-length:")[1].split("\r\n")[0])
            inbox.put(json.loads(p.stdout.read(n)))
    except Exception as e:
        inbox.put(f"bad message from lldb-dap: {e!r}")

threading.Thread(target=reader, daemon=True).start()

def wait(pred, timeout=60):
    for i, m in enumerate(pending):  # messages that arrived out of order
        if pred(m):
            return pending.pop(i)
    end = time.monotonic() + timeout
    while True:
        try:
            left = end - time.monotonic()  # read the clock once per pass
            if left <= 0:  # also when other messages keep coming
                raise queue.Empty
            m = inbox.get(timeout=left)
        except queue.Empty:
            sys.exit(f"FAIL: lldb-dap sent nothing the probe was waiting for in {timeout}s")
        if isinstance(m, str):  # the reader stopped
            sys.exit(f"FAIL: {m}")
        if pred(m):
            return m
        pending.append(m)

def req(cmd, args=None):
    s = send(cmd, args)
    r = wait(lambda m: m.get("type") == "response" and m.get("request_seq") == s)
    if not r.get("success"):
        err = (r.get("body") or {}).get("error", {}).get("format")
        sys.exit(f"FAIL: {cmd}: {r.get('message') or err}")
    return r.get("body") or {}

def event(*names):
    return lambda m: m.get("type") == "event" and m.get("event") in names

def probe():  # returns the list of failed checks; empty means PASS
    req("initialize", {"clientID": "probe", "adapterID": "lldb-dap",
                       "linesStartAt1": True, "columnsStartAt1": True,
                       "pathFormat": "path"})
    launch = send("launch", {"program": prog})
    wait(event("initialized"))
    bp = req("setBreakpoints", {"source": {"path": src},
                                "breakpoints": [{"line": line}]})["breakpoints"][0]
    print("breakpoint verified:", bp.get("verified"))
    req("configurationDone")
    wait(lambda m: m.get("type") == "response" and m.get("request_seq") == launch)
    stop = wait(event("stopped", "exited", "terminated"))
    reason = stop.get("body", {}).get("reason")
    print("stopped:", reason)
    if stop["event"] != "stopped":
        sys.exit(f"FAIL: program {stop['event']} without stopping at line {line}")
    tid = stop["body"]["threadId"]
    frame = req("stackTrace", {"threadId": tid, "levels": 1})["stackFrames"][0]
    scopes = req("scopes", {"frameId": frame["id"]})["scopes"]
    local = next(s for s in scopes if s["name"].lower().startswith("local"))
    vars_ = {v["name"]: v for v in req("variables", {"variablesReference":
                                                     local["variablesReference"]})["variables"]}
    kids = [k["value"] for k in req("variables", {"variablesReference":
                                                  vars_["v"]["variablesReference"]})["variables"]]
    s = vars_["s"]["value"]
    print("v =", vars_["v"]["value"], kids, "| s =", s)
    req("continue", {"threadId": tid})
    end = wait(event("exited", "stopped", "terminated"))
    if end["event"] != "exited":
        sys.exit(f"FAIL: program {end['event']} after continue, not exited")
    code = end["body"]["exitCode"]
    print("exit code:", code)
    req("disconnect", {"terminateDebuggee": True})
    p.wait(timeout=20)
    checks = [("breakpoint not verified", bp.get("verified")),
              (f"stop reason {reason!r}", reason == "breakpoint"),
              (f"v children {kids}", kids == ["1", "2", "3"]),
              (f"s is {s}", s == '"p2996"'),
              (f"exit code {code}", code == 0)]
    return [name for name, good in checks if not good]

try:
    failed = probe()
except Exception as e:  # a reply without a field the probe needs, or a slow exit
    sys.exit(f"FAIL: {type(e).__name__}: {e}")
finally:
    if p.poll() is None:
        p.kill()
if failed:
    sys.exit("FAIL: " + "; ".join(failed))
print("PASS")
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
- Tart: `openai/tart` 2.41.1 release (`tart.tar.gz`, `tart_2.41.1_checksums.txt`) and the aqua registry entry `pkgs/openai/tart/registry.yaml`; GHCR manifests for
  `cirruslabs/macos-golden-gate-xcode:27.2`.
- Host probes: run on 2026-11-14 on macOS 27.2.1 (26B131), Xcode 27.2
  (27B52).
