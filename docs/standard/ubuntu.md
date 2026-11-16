# Ubuntu 26.10 C++ environment (amd64 and arm64): certification playbook

This playbook says what the Ubuntu 26.10 container needs, amd64 on the PC
and arm64 in Docker Desktop on the Mac,
for modern low-level C++ work: three compilers, their standard libraries and
runtimes, and the tools for analysis, debugging, profiling and metrics. It
also says how the container must run so that its numbers are as close to
the PC's bare metal as possible. Each item has a requirement, the reason for
it, a probe, the expected output, and a PASS/FAIL rule. A FAIL line in the
report is the list of what is missing or wrong.

It is the Linux sibling of [`macos.md`](macos.md) and keeps its section
letters where they apply. The decisions behind it are in
[`decisions-log.md`](../designs/level-1/decisions-log.md) (D10, D12, D25,
D27, D35, D45, D46, D48, D105 and D137). The design is
[`environment-standard.md`](../designs/environment-standard.md) §1.

## The machine

"The PC" is the self-hosted amd64 machine on the tailnet: an AMD Ryzen 9
5900X (Zen 3, 12 cores, 24 threads, AVX2 and no AVX-512), 62 GiB of RAM. Its
own OS is Omarchy (Arch based, kernel `7.2.15-1-omarchy`), not Ubuntu, so
Ubuntu 26.10 runs as a Docker container on it (Docker 29.9.2). A container
shares the host's kernel: every check that depends on the kernel (perf
counters, `perf_event_paranoid`, ptrace and ASLR, sanitizer memory layout,
cgroups) is marked **(container on the PC's Omarchy kernel)** here and
`[host kernel]` in the report. Those results say what the container does on
this kernel, not what Ubuntu's own kernel would do.

"The Mac" is the owner's Apple M2 Max (Armv8.6-A). The arm64 container runs
natively, with no emulation, in Docker Desktop (29.9.3), whose Linux VM
(kernel `7.0.14-linuxkit`, 8 CPUs and 16 GB as configured) is the Docker
host: there the kernel-dependent checks are about that VM's kernel, and
the report says so. The Mac is shared by many agents, so arm64 builds and
certification run only in a load window agreed with chief-of-staff, with the
build container capped (`--cpus 4 --memory 16g`, 4 jobs). Where a check
differs per architecture, its text gives both; a check is N/A only where the
hardware or host is absent, with the reason in its line.

## How to use it

1. Build the image once, on the PC: `mise run certify:ubuntu-image`. It
   builds [`ubuntu-cert.Dockerfile`](ubuntu-cert.Dockerfile), which pins
   every package (see "The end state").
2. Run `MISE_AUTO_INSTALL=0 mise run certify:ubuntu --allow-fail` from the
   Mac; the task refuses to start without `MISE_AUTO_INSTALL=0`, because a
   plain `mise run` can install a missing tool of this repository's config
   on the Mac first (rule 4). It also watches, on the Mac, the install
   folders of the tools this repository pins (`mise ls --current` entries
   whose config file is in this repository), not all of mise's installs,
   because other sessions on a shared Mac install unrelated tools. It names
   any path inside them, at any depth, added, removed or modified during the
   run, from a walk of every path at start and end and a marker file for
   files changed in place; a pinned tool's folder that appears during the
   run counts as added. Python's `__pycache__` folders, which hold compiled
   bytecode, not installs, are skipped. The report's
   `mise installs (this Mac):` line says `unchanged`,
   or names the change and fails the run (exit 3; another process installing
   at the same time also trips it, so rerun then). Both tasks reach
   the PC's Docker over ssh: set `CERT_UBUNTU_SSH` to the ssh destination of
   the PC (its tailnet name or an ssh alias for it). The Docker client they
   run on the Mac is pinned in this repository (`.mise/conf.d/docker.toml`,
   `docker-cli`), not taken from a user's global config. `docker build`
   (`certify:ubuntu-image`) also needs the buildx plugin, which the Docker
   client finds through the user's `~/.docker/config.json`; no repository
   pin covers it yet. On the PC, Docker and (for `--ab`) `bwrap` are host
   packages: reported, never changed (rule 4). The `ubuntu-certify`
   skill explains the report. The first report is
   `reports/ubuntu-pc-2026-11-15.txt`, next to this file; the current
   baseline is `reports/ubuntu-pc-2026-11-16-multiarch.txt`, from the
   image built from the multi-arch Dockerfile (`reports/ubuntu-pc-2026-11-16.txt`
   before it added the full LLVM set for p2996, GPU offload, and LLVM 23 at
   the `551bf48cf74f` snapshot).

   arm64, on the Mac: `mise run certify:ubuntu-image --local` builds the image
   natively in Docker Desktop (4 ninja jobs), and
   `MISE_AUTO_INSTALL=0 mise run certify:ubuntu --local --allow-fail`
   certifies it there, with no ssh. The "Docker host" is then Docker
   Desktop's Linux VM: the host-side probes run in it through `nsenter` from
   a privileged helper container. p2996 for arm64 is built the same way as on
   the PC, into a volume of the same name, in a container capped at
   `--cpus 4 --memory 16g` (Appendix: p2996 build). Run both only in a load
   window agreed with chief-of-staff. The arm64 baseline is
   `reports/ubuntu-mac-arm64-2026-11-16.txt`.
3. Write one report line per check: `<id> PASS|FAIL|N/A <one-line evidence>`.
4. Do not install or change anything while certifying. The image puts
   mise's shims first on `PATH` and sets `MISE_YES=1`, so the probes run with
   `MISE_AUTO_INSTALL=0` inside the container too: a shim for a tool the
   image lacks then fails instead of installing it. A FAIL names the fix;
   the fix is a separate step. Never change the PC host's settings: report
   them (V5) and route any change through cpp-standard-lead to dotfiles-lead.
5. Timing checks (U3, U4, V4, V6) count only when the PC's other containers
   (the self-hosted runners) were idle. The runner samples their CPU time
   around the timing pass and marks the lines "timing untrusted" when they
   used over one CPU-second, when a container started or stopped during the
   pass, or when one's CPU time could not be read.

The container runs with these flags, which `certify:ubuntu` encodes (V2
explains each one):

```sh
docker run --privileged --hostname cert -v cpp-standard-cert-build:/build \
  -v cpp-standard-p2996-562409c79426-d3773989aa5d:/opt/p2996:ro \
  -v /usr/lib/libcuda.so.<driver>:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \
  -v /usr/lib/libcuda.so.<driver>:/usr/lib/x86_64-linux-gnu/libcuda.so:ro \
  -v /usr/lib/libnvidia-ptxjitcompiler.so.<driver>:/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.1:ro \
  cpp-standard-cert-ubuntu:26.10
```

The three driver mounts are the PC's NVIDIA libraries at the version
`nvidia-smi` reports (GO); the host paths are where its distribution keeps
them.

## Usable today (the PC, 2026-11-16)

You can start a C++26 project in this container now. These results came from
running the probes below on the PC.

| Area | State | Workaround until fixed |
|---|---|---|
| GCC 16.2.0 (26.10 archive): `-freflection`, `import std` through CMake, ASan, TSan, UBSan, LSan | PASS | none needed |
| clang 23 (apt.llvm.org `resolute-23`): `import std` through CMake with libc++ and with libstdc++; ASan, TSan, UBSan | PASS | none needed |
| clang-p2996 562409c7 (amd64, built on the PC): reflection, `import std`, ASan, TSan, UBSan, tools, lldb and lldb-dap | PASS (P, DB4, DB5), with IWYU 0.25 built in the tree (P8) | none needed |
| p2996's full LLVM set: flang, BOLT, OpenMP with CPU offload, LLVM libc (overlay) | PASS (P11-P14) | none needed |
| OpenMP GPU offload on the GTX 1660 SUPER (`sm_75`) with p2996, clang 23 and GCC 16 | PASS (GO1-GO3) | each compiler needs its own flags (GO); the container needs the host's driver libraries, which `certify:ubuntu` mounts |
| MemorySanitizer | recorded, not certified (C6) | needs an MSan-built libc++, which no toolchain here ships |
| clang 23's default standard library | libstdc++ (C2) | pass `-stdlib=libc++` in the libc++ presets |
| apt libc++ hardening | default `NONE` (H2) | every libc++ preset sets `_LIBCPP_HARDENING_MODE` (H1) |
| `clangd-23` from apt.llvm.org | FAIL (E2): needs `libabsl20260107`, which 26.10 does not have | clangd 23.1.5 from the LLVM release tarball (in the image); its version differs from the apt clang 23.1.6 snapshot |
| The archive's `iwyu` package | not usable (B2, T3): IWYU 0.23 on clang 19, and it installs the archive `clang` 22, which takes over `cc`, `c++` and `clang++` | leave it out (the image does); the image builds IWYU 0.27 against LLVM 23 instead (T3) |
| GCC `<stacktrace>` | links only with `-lstdc++exp` (L4) | add `-lstdc++exp` to GCC targets that use it |
| perf, and lldb's default launch (ASLR off) | need more than Docker's default seccomp profile (V2) | the container runs `--privileged` (D137); without it, see V2 |
| CPU target | `-march=x86-64-v3` (U3, D137) | none needed |
| Build trees | on the volume `/build` (V4) | none needed |

### arm64 on the Mac (2026-11-16)

The same image and the same p2996 build, arm64 in Docker Desktop, certify
at 66 PASS, 1 FAIL (E2, as above), 16 N/A
(`reports/ubuntu-mac-arm64-2026-11-16.txt`). Everything in the table above
holds there too, except:

| Area | State | Workaround until fixed |
|---|---|---|
| OpenMP GPU offload | N/A (GO1-GO3): no NVIDIA GPU reaches Docker on the Mac | compiles; run it on the PC |
| Hardware counters | N/A (R2): Docker Desktop's VM has no PMU | `perf record -e cpu-clock` (R3) and callgrind (R7) |
| `-mcpu=native` | `generic` (U1): the VM hides the CPU model | name the target: `-mcpu=apple-m2` or `-march=armv8.6-a` |
| memprof, nsan | not built for AArch64 by compiler-rt (C5) | none |
| CPU target | proposed, decided in the Part B pull request (U) | none needed |

To launch and use the container, the `ubuntu-arm64-run` skill
(`mise run ubuntu:arm64`).

## The end state

| Component | Source | Built from source? | Why |
|---|---|---|---|
| Ubuntu 26.10 "stonking" | `ubuntu:26.10@sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7` (the amd64 manifest is `sha256:8f52618638aaad6b239d47d734112b15757a22fe1a8e76ace2c402e33ed672c8`) | no | The base (D25), pinned by digest. glibc 2.44. |
| GCC 16.2.0 + libstdc++ | 26.10 archive, `g++-16 16.2.0-3ubuntu1` | no | D25. |
| LLVM / clang 23 + libc++, libomp, liboffload | apt.llvm.org `llvm-toolchain-resolute-23`, `1:23.1.6~++20261115084239+551bf48cf74f-1~exp1~20261115204336.95` | no | D12, D25, D27. apt.llvm.org has no stonking suite. It deletes old snapshots within days, so a rebuild needs new pins; the image ID in the report is the record (D27). Moved on 2026-11-16 from `c47d7823685a`, which apt.llvm.org had already deleted when the GPU-offload layers needed an image rebuild. |
| clang 23 OpenMP NVPTX device runtime | `llvm/llvm-project` at `551bf48cf74f` (the apt snapshot's commit), `openmp` built for `nvptx64-nvidia-cuda` in the image's `llvm23-offload` stage with the apt `clang-23` | **yes** | GO2: no llvm-23 apt package and not the 23.1.5 release tarball ships it (the tarball has only `libomp.so` and `libompd.so`). Installed in `/opt/llvm23-offload`, linked as `/usr/lib/llvm-23/lib/nvptx64-nvidia-cuda`, where clang looks (`clang/lib/Driver/ToolChains/CommonArgs.cpp:3076-3078`). The stage checks its commit is the one in `LLVM_VER`, so the two move together. |
| CUDA 13.2.86 and 12.9.86 (ptxas, nvlink, fatbinary, libdevice, headers) | NVIDIA's redistributables (`cuda_nvcc`, `libnvvm`, `cuda_cudart`), each checked against the sha256 in `redistrib_13.2.2.json` / `redistrib_12.9.2.json`; only those files kept, in `/opt/cuda-13.2` and `/opt/cuda-12.9`, not on `PATH` | no | GO: clang's NVPTX offload runs `ptxas`, `nvlink` and `fatbinary`, with no toolkit-free path. clang 23 takes 13.2, the newest it fully supports (`clang/include/clang/Basic/Cuda.h:54`). p2996 takes 12.9 (GO1). |
| GCC 16 NVPTX offload | 26.10 archive, `gcc-16-offload-nvptx 16.2.0-3ubuntu1`, `nvptx-tools 0.20260402-1` | no | GO3. No CUDA toolkit: libgomp's plugin hands PTX to the driver. |
| clangd 23.1.5 | `LLVM-23.1.5-Linux-X64.tar.xz` (amd64, sha256 `f72edb0b36580ece7f52e23858f00c18fad4e87395ea7ad05d7e55c39f8fc78a`) or `LLVM-23.1.5-Linux-ARM64.tar.xz` (arm64, sha256 `44f1e4b7a125b2763d56386a199928dd57ec32e151cc6042dce2f7b0da7bb651`) from the llvmorg-23.1.5 release, unpacked to `/opt/llvm-23.1.5`; its attestation verified on 2026-11-15 with `gh attestation verify <tarball> --bundle <tarball>.jsonl --repo llvm/llvm-project` (exit 0; signer `release-binaries.yml@refs/tags/llvmorg-23.1.5`; the same check with `--repo llvm/clangir` exits 1) | no | E2: the apt `clangd-23` does not install on 26.10. Only `bin/clangd` and `lib/clang` are kept. |
| include-what-you-use 0.27 | `include-what-you-use/include-what-you-use` at `c9cbc836a1af` (tag 0.27, the `clang_23` head), built in the image's `iwyu` stage against `llvm-23-dev` and `libclang-23-dev` of the same snapshot | **yes** | T3: no package of IWYU for LLVM 23 exists; the archive `iwyu` is 0.23 on clang 19 (B2). Installed in `/opt/iwyu-llvm23`, linked into `/usr/local/bin`. |
| clang-p2996 + libc++ + IWYU 0.25 | `bloomberg/clang-p2996` at the pinned commit, with IWYU `791e69ea4662` (the `clang_21` head) as an LLVM external project, built in a container on the PC | **yes** | The reflection reference compiler (D30, D32); no prebuilt binary exists. Mounted read-only from a volume, not baked into the image (D49). |
| binutils 2.47, make 4.4.1, gdb 17.2, valgrind 3.27.1, linux-perf 7.3.0, cppcheck 2.21.0 | 26.10 archive | no | D45, D105, D19. |
| mise 2026.11.8 | the release tarball, checked by sha256 | no | D99. A stand-in for D73's packslip install until the M1a base image exists. |
| CMake 4.5.0, Ninja 1.13.2, sccache 0.19.0, vcpkg-tool 2026-10-29, gcovr 8.8, Doxygen 1.18.0, hyperfine 2.0.0, mold 3.0.0, uv 0.13.8, Python 3.14.8 | mise, from [`ubuntu-cert-tools/`](ubuntu-cert-tools/): `mise.toml` and its linux-x64 `mise.lock`, installed with `mise install --locked` | no | The Mac's versions (B1), plus mold. Python is there because a locked `pypi:` install (gcovr) needs a mise-managed interpreter. `--locked` refuses any tool or download not in the lock (checked: adding `jq` to the config makes the install fail). The image points `MISE_GLOBAL_CONFIG_FILE` at that `mise.toml` instead of changing a global config. |

[`ubuntu-cert.Dockerfile`](ubuntu-cert.Dockerfile) is the setup: it installs
exactly the table above and nothing else. It is a stand-in for the M1a base
and tools images (D45, D49).

### The p2996 build (amd64 and arm64)

The D136 configuration, with the changes Linux needs. The build ran in a
container from the image above (host compiler clang 23, `lld`), with
`python3-dev swig libedit-dev libxml2-dev zlib1g-dev libzstd-dev
libncurses-dev libffi-dev` added to that throwaway container only. The full
project list (2026-11-16) added one package, `libffi-dev`: without it
offload's host plugin is built to `dlopen("libffi.so")`
(`offload/plugins-nextgen/host/dynamic_ffi/ffi.cpp:32`), a name only the
dev package installs, so in the certified image (which has `libffi.so.8`)
it finds no device and every target region falls back to the host
(measured: "No images found compatible with the installed hardware"). With
it the plugin links `libffi.so.8` (`host/CMakeLists.txt:17-22`). flang,
MLIR, BOLT, openmp and the libc overlay need nothing more. The script is in
[Appendix: p2996 build](#appendix-p2996-build).

| Setting | Value | Why |
|---|---|---|
| `LLVM_ENABLE_PROJECTS` | `clang;clang-tools-extra;lld;lldb;mlir;polly;bolt;flang` | D136 (amended 2026-11-16): every project that builds on Linux, the macOS list. BOLT works here: it reads X86-64 and AArch64 ELF (`bolt/README.md:12`; `bolt/CMakeLists.txt:65` targets `AArch64;X86;RISCV`, and lines 88-93 build its runtime on Linux x86_64 and aarch64). flang is an extra project (`llvm/CMakeLists.txt:124`) that pulls in MLIR, clang and flang-rt (lines 164-179); it needs `LLVM_ENABLE_EH` off (`flang/CMakeLists.txt:20`, the default) and a 64-bit CPU (line 73). |
| `LLVM_ENABLE_RUNTIMES` | `libc;libunwind;libcxxabi;libcxx;compiler-rt;openmp;offload;flang-rt` | D136 (amended 2026-11-16); compiler-rt for the sanitizers (M0 (c)). **libc** is the overlay (`libllvmlibc.a` beside glibc): a full build is the default only for GPU targets (`libc/CMakeLists.txt:128-135`), and the overlay generates no headers, so it needs no PyYAML (`libc/cmake/modules/LLVMLibCHeaderRules.cmake:84-87`). **openmp** builds `libomp` and, on 64-bit Linux, its offload hooks (`openmp/CMakeLists.txt:103-114`). **offload** builds the host plugin (CPU offload, Linux only: `offload/CMakeLists.txt:157-161`; P13) and, because NVPTX is a target, the NVPTX device runtime (`offload/DeviceRTL/CMakeLists.txt:182-188`; GPU offload, GO1). The CUDA and AMDGPU plugins `dlopen` their drivers, so they need nothing at build time; with no AMDGPU backend there is no AMD device runtime. The Mac has none: offload does not build on Apple. **flang-rt** needs flang (`llvm/CMakeLists.txt:209-213`). |
| Left out | `libclc`, `llvm-libgcc` | libclc is the OpenCL C library for GPU devices (`libclc/CMakeLists.txt:120-130`: amdgcn, nvptx, r600, clspv targets); OpenMP offload does not use it, and nothing here compiles OpenCL. llvm-libgcc needs an explicit opt-in and is a configure error next to compiler-rt or libunwind (`llvm-libgcc/CMakeLists.txt:38-58`). |
| `FLANG_PARALLEL_COMPILE_JOBS` | the build's jobs / 4, at least 1 (`FLANG_JOBS` overrides) | Each flang compile takes several GB; this pool keeps them within the container's memory while the rest of LLVM builds at full width (`flang/CMakeLists.txt:486-494`). |
| `LLVM_TARGETS_TO_BUILD` | `X86` on amd64, `AArch64` on arm64, from `uname -m`; plus `NVPTX` | One native target; a hard-coded target broke an earlier arm64 build (`research/p2996-linux.md`), so the script picks it from the machine. `NVPTX` for OpenMP GPU offload (D136, amended 2026-11-16): offload builds its NVPTX device runtime only when NVPTX is a target (`offload/DeviceRTL/CMakeLists.txt:182-188`). No `AMDGPU`: no AMD hardware to certify, and it is one of the largest backends. arm64 builds `NVPTX` too, so both run the same script. |
| `RUNTIMES_CMAKE_ARGS` | `-DCMAKE_CXX_FLAGS=-stdlib=libstdc++` | The runtimes sub-build compiles offload, openmp and flang-rt with the just-built `clang++`, whose default is libc++. Those runtimes set no C++ library, and nothing orders them after libcxx generates its headers, so the first full build failed: `offload/tools/offload-tblgen/PrintGen.cpp: fatal error: 'type_traits' file not found` (2026-11-16). libcxx, libcxxabi, libunwind and compiler-rt are unaffected: they compile with `-nostdinc++` and link with `-nostdlib++` (`runtimes/CMakeLists.txt:152-161`). apt.llvm.org ships these runtimes the same way. Consequence (`readelf -d`): `libomptarget.so` needs `libstdc++.so.6`, so a libc++ program that offloads loads both C++ runtimes (they do not clash: `std` vs `std::__1`). `libomp.so`, `libc++.so.1`, `libc++abi.so.1` and `libunwind.so.1` need no libstdc++. |
| `LLVM_ENABLE_ASSERTIONS`, `LIBCXX_HARDENING_MODE`, `LLVM_INSTALL_UTILS` | `ON`, `extensive`, `ON` | As D136. |
| `LLDB_ENABLE_PYTHON` | `ON`, Ubuntu's Python 3.14 | lldb scripting and lldb-dap. On Linux lldb uses its own `lldb-server`; no code signing. |
| `CLANG_DEFAULT_CXX_STDLIB` | `libc++` | p2996 pairs with its own libc++ (D6). |
| `COMPILER_RT_DEFAULT_TARGET_ONLY` and the `linux/scc.h` patch | `ON`, patch from `spikes/m0/h/patches/` | D105: compiler-rt at this commit does not build against 26.10's kernel headers without it. |
| `lldb-base-specifier-derived.patch` | from the dotfiles p2996 recipe | lldb at this commit does not compile against p2996's `CXXBaseSpecifier` (it takes the derived record, not a flag): `TypeSystemClang.cpp:7862: no matching constructor for initialization of 'clang::CXXBaseSpecifier'`. The Mac build carries the same patch. M0 (h) built only `clang;lld`, so it never hit this. |
| Install prefix | `/opt/p2996` in the volume `cpp-standard-p2996-<commit12>-<inputs12>` (Appendix: p2996 build) | `research/p2996-linux.md`: a separate prefix, nothing on `PATH`. |

### What the container cannot have, or has only with a flag

| Item | Why | What to do |
|---|---|---|
| Ubuntu's own kernel | a container runs on the host's kernel (Omarchy 7.2.15 here) | label kernel-dependent results; never compare them with an Ubuntu host's |
| perf events | Docker's default seccomp profile refuses `perf_event_open` unless the container has `CAP_PERFMON` (V2) | `--privileged` (D137); `--cap-add PERFMON` alone is enough for perf |
| Disabling ASLR (`personality(ADDR_NO_RANDOMIZE)`), which lldb does by default | refused by Docker's default seccomp profile, with or without `CAP_PERFMON` or `CAP_SYS_PTRACE` (V2) | `--privileged` (D137); without it, debug with ASLR on: `settings set target.disable-aslr false`, and `"disableASLR": false` for lldb-dap |
| Host CPU settings (governor, boost, SMT, THP) | set on the host | report them (V5); change them only on the host, through dotfiles-lead |

## A. Host and OS

**A1. Ubuntu 26.10.** Probe: `. /etc/os-release; echo "$VERSION_ID $VERSION_CODENAME"`.
Expected: `26.10 stonking`. Today: PASS.

**A2. Base image pinned by digest.** Why: D25 pins the base by digest; the
image carries it as the label `org.opencontainers.image.base.digest`.
Probe (on the Docker host):
`docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.base.digest"}}' cpp-standard-cert-ubuntu:26.10`.
Expected: the digest of `ubuntu:26.10@sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7`.
PASS if equal.

**A3. Native amd64, no emulation.** Why: an emulated container runs many
times slower and its counters mean nothing. Probe:
`dpkg --print-architecture; uname -m` in the container, and on the host
`ls /proc/sys/fs/binfmt_misc/qemu-x86_64`. Expected: `amd64`, `x86_64`, and
no `qemu-x86_64` entry. PASS if all three. Today: PASS; the host registers
qemu only for foreign architectures (`qemu-aarch64` and others). arm64:
expected `arm64`, `aarch64`, and `uname -m` on the Docker host (Docker
Desktop's VM) `aarch64`; a `qemu-x86_64` handler there would only run x86
images, so it is recorded, not failed.

**A4. Kernel (container on the PC's Omarchy kernel).** Probe: `uname -r`.
Recorded in the report header; N/A, because the container cannot choose it.
Today: `7.2.15-1-omarchy`.

**A5. glibc.** Probe: `ldd --version | head -1`. Expected: `ldd (Ubuntu GLIBC
2.44-1ubuntu2) 2.44`. PASS if 2.44.

**A6. CPU features.** Why: the CPU target (U) depends on what the CPU has.
Probe:

```sh
/lib64/ld-linux-x86-64.so.2 --help | grep supported
for f in avx2 bmi2 fma adx sha_ni vaes vpclmulqdq avx512f; do grep -qw $f /proc/cpuinfo && echo $f; done
```

Expected: `x86-64-v3 (supported, searched)` and `x86-64-v2 (supported,
searched)` but not v4, and every flag except `avx512f`. PASS if so. The
level names and which are supported come from this glibc's own loader
(`ld.so --help`), not from a list in this playbook. arm64 (Apple M2,
Armv8.6-A): `asimd atomics crc32 aes sha2 asimddp lrcpc i8mm bf16` in
`/proc/cpuinfo` and no `sve` (Apple cores have none). PASS if so.

**A7. apt.llvm.org source.** Probe: `cat /etc/apt/sources.list.d/llvm.list`
and `gpg --show-keys --with-colons /usr/share/keyrings/apt-llvm.gpg`.
Expected: `llvm-toolchain-resolute-23 main` and the key fingerprint
`6084F3CF814B57C1CF12EFD515CF4D18AF4F7421` (M0 (f)). PASS if both.

## B. Build tools

**B1. Versions.** Probe:

```sh
for t in mise cmake ninja sccache vcpkg gcovr doxygen hyperfine mold; do
  printf '%-10s ' "$t"; "$t" --version 2>&1 | head -1
done
```

PASS if all nine print a version and CMake is 4.5 or later. The 26.10
archive has CMake 4.3.4 (D25), so CMake comes from mise.

**B2. No stray compilers.** Why: Ubuntu's `iwyu` package depends on the
archive's `clang` package (clang 22). Installing it makes `cc`, `c++` and
`clang++` resolve to `/usr/lib/llvm-22/bin/clang`, so a build that calls
`cc` silently uses clang 22. Probe:

```sh
for t in cc c++ gcc g++ clang clang++ lldb; do readlink -f "$(command -v $t)"; done
dpkg-query -W 'llvm-[0-9]*' 'clang-[0-9]*' | grep -v -- '-23'
for s in ~/.local/share/mise/shims/*; do mise which "${s##*/}" >/dev/null || echo "stray ${s##*/}"; done
```

PASS if every name is absent or resolves to GCC 16 or LLVM 23, no other
LLVM major is installed, and every mise shim on `PATH` has an active version
(`mise which <name>` succeeds). A stray shim, one with no active version,
errors or falls through to another tool of that name; the macOS B2 found
three on 2026-11-15. Seen while building the image by hand: FAIL
(`cc -> /usr/lib/llvm-22/bin/clang`, `clang-22 1:22.1.8-1ubuntu1`), from
`apt-get install iwyu`. The image leaves `iwyu` out.

**B3. sccache.** Probe: `sccache --show-stats | head -3`. PASS if it prints
statistics.

**B4. binutils and make.** Probe: `dpkg-query -W binutils make`. Expected:
`2.47-6ubuntu1` and `4.4.1-3`, the D105 pins. PASS if both.

## C. LLVM / clang 23 (apt.llvm.org)

**C1. Version and origin.** Probe: `clang++-23 --version | head -1;
apt-cache policy clang-23`. Expected: `Ubuntu clang version 23.1.6
(++20261115084239+551bf48cf74f-...)` installed from apt.llvm.org. That
version is a snapshot of the `release/23.x` branch: no llvmorg-23.1.6
release exists yet (23.1.5 is the newest).

**C2. Default standard library.** Why: on Linux clang links libstdc++ unless
told otherwise; D6 pairs clang with libc++. Probe:

```sh
clang++-23 -### -x c++ /dev/null -o /dev/null 2>&1 | grep -oE -- '-lstdc\+\+|-lc\+\+'
clang++-23 -stdlib=libc++ -print-file-name=libc++.modules.json
```

Expected: `-lstdc++`, and `/lib/x86_64-linux-gnu/libc++.modules.json`. PASS
if both. The libc++ presets pass `-stdlib=libc++`.

**C3. Links LLVM 23's libc++.** Probe:

```sh
printf '#include <print>\nint main(){std::println("ok");}\n' > p.cpp
clang++-23 -std=c++26 -stdlib=libc++ p.cpp -o p && ./p &&
  lib="$(readlink -f "$(ldd p | awk '/libc\+\+\.so/{print $3}')")" &&
  dpkg -S "$lib" && dpkg-query -W -f '${Version}\n' "$(dpkg -S "$lib" | cut -d: -f1)" clang-23
```

Expected: `ok`, and the loaded `libc++.so.1` (Ubuntu installs it as
`/usr/lib/x86_64-linux-gnu/libc++.so.1.0`) belongs to a package whose
version equals `clang-23`'s: the same apt.llvm.org build. PASS if both.

**C4. `import std` through CMake.** Use the CMake project in
[Appendix: CMake probe](#appendix-cmake-probe) with
`-DCMAKE_CXX_COMPILER=clang++-23`, once with
`-DCMAKE_CXX_FLAGS=-stdlib=libc++` and once without. Expected: `import std
ok` twice. Today: PASS (hand run, 2026-11-15).

**C5. Runtimes.** Probe: `ls "$(clang++-23 -print-resource-dir)"/lib/*/`.
Expected, at least, `libclang_rt.<name>` for: `asan tsan msan lsan
ubsan_standalone dfsan hwasan memprof nsan rtsan tysan scudo_standalone
gwp_asan safestack cfi fuzzer profile xray`. PASS if all 18. The macOS
playbook lists most of these as Linux-only. arm64: 16, without `memprof` and
`nsan`, which compiler-rt builds for x86_64 only
(`compiler-rt/cmake/Modules/AllSupportedArchDefs.cmake:94,96` at LLVM
`551bf48cf74f`); the probe looks in `clang++-23 -print-runtime-dir`.

**C6. Sanitizers fire (container on the PC's Omarchy kernel).** Use `san.cpp` from
[Appendix: sanitizer probe](#appendix-sanitizer-probe) (the same file as
macOS C6) for ASan, TSan, UBSan and MSan:

```sh
for s in address thread undefined memory; do
  clang++-23 -g -std=c++26 -stdlib=libc++ -fsanitize=$s san.cpp -o s_$s &&
    ASAN_OPTIONS=detect_leaks=0 ./s_$s 2>&1 | grep -m1 -E 'ERROR|WARNING|runtime error'
done
```

Why the race loops: with one increment in each thread, TSan reported it in
only 7 of 20 runs with GCC 16 and 3 of 20 with clang 23 (and 8 and 4 of 20
without `--privileged`). `san.cpp`'s race loops 100000 times in each thread
and fired in 30 of 30 runs with each of GCC 16, clang 23 and p2996
(2026-11-15). The runner still runs TSan up to three
times and passes on the first report: a reported race is always a real one in this code, so a retry
cannot make a false PASS, only avoid a false FAIL.

Expected: `heap-buffer-overflow`, `data race` and a UBSan `runtime error`.
PASS if those three fire. MSan is recorded, not required: "MemorySanitizer
requires that all program code is instrumented. This also includes any
libraries that the program depends on, even libc. Failing to achieve this
may result in false reports" (`clang/docs/MemorySanitizer.md` at
llvmorg-23.1.5). The probe's libc++ is not MSan-built, so a report or its
absence proves nothing: with clang 23 MSan reported
`use-of-uninitialized-value`; with p2996 it reported nothing. Real MSan runs
need an MSan-built libc++, which neither toolchain ships.

**C7. Tools.** Probe: `command -v clang-tidy-23 clang-format-23 llvm-mca-23
llvm-cov-23 llvm-profdata-23 ld.lld-23 lldb-23 lldb-dap-23 scan-build-23
llvm-bolt-23` and the tarball's `clangd`. PASS if all eleven exist.

**C8. Linkers.** Probe:
`for ld in bfd lld mold; do clang++-23 -std=c++26 -fuse-ld=$ld p.cpp -o p_$ld && ./p_$ld; done`.
Expected: `ok` three times. GNU ld (`bfd`) is the default; lld and mold are
presets for link-time comparisons (U4). `gold` is not offered: clang 23
rejects `-fuse-ld=gold` ("invalid linker name").

**C9. BOLT.** Why: BOLT reads only ELF, so it is a Linux-only optimiser
(macOS "What macOS cannot have"). Probe:
`clang++-23 -std=c++26 -O2 -Wl,--emit-relocs p.cpp -o pb && llvm-bolt-23 pb -o pb.bolt && ./pb.bolt`.
Expected: `ok`. PASS if so. Today: PASS (hand run).

## G. GCC 16.2 (26.10 archive)

**G1. Version and origin.** Probe: `g++-16 --version | head -1;
dpkg-query -W g++-16`. Expected: `g++-16 (Ubuntu 16.2.0-3ubuntu1) 16.2.0`.
PASS if the package is `16.2.0-3ubuntu1`. (macOS G3, the sysroot, has no
Linux counterpart.)

**G2. Reflection and `import std`.** `refl.cpp` from
[Appendix: reflection probe](#appendix-reflection-probe) with
`g++-16 -std=c++26 -freflection` prints `members=2`; the CMake probe with
`-DCMAKE_CXX_COMPILER=g++-16` prints `import std ok`. PASS if both. Today:
PASS (hand run).

**G4. Sanitizers (container on the PC's Omarchy kernel).** Expected: ASan,
TSan and UBSan fire on `san.cpp` (the C6 probe with `g++-16`, without
`-stdlib`), and LeakSanitizer reports the leak in
`printf 'int* p;\nint main(){ p = new int[4]; p = nullptr; }\n' > leak.cpp`
built with `-fsanitize=leak` ("detected memory leaks"). PASS if all four.
Unlike macOS, GCC's TSan and LSan exist on Linux. Today: PASS (hand run).
Build the probes without `-O`; see
[Appendix: sanitizer probe](#appendix-sanitizer-probe) for what `-O2` does
to them.

**G5. Never mix standard libraries.** Rule, no probe: all C++ dependencies
come from vcpkg with the matching triplet (K1).

The same rule covers LTO objects: they are linked only by the compiler that
made them. The archive `g++-16` compresses LTO bytecode with zstd ("Supported
LTO compression algorithms: zlib zstd"). The macOS recipe in
`toolchains/gcc-macos/` is built `--without-zstd` ("zlib" only). Built on
this image (2026-11-16, amd64), the two fail both ways on the same two-file
`-flto` program:

| Objects compiled by | LTO-linked by | Result |
|---|---|---|
| archive `g++-16` | recipe GCC (`--without-zstd`) | `lto1: fatal error: compiler does not support ZSTD LTO compression` |
| recipe GCC | archive `g++-16` | `lto1: internal compiler error: original not compressed with zstd` |

Each compiler links its own LTO objects. A vcpkg binary cache or prebuilt
static library holding LTO objects must come from the compiler that
consumes it.

**G6. Debug info links.** Probe:
`g++-16 -std=c++26 -g -fsanitize=address san.cpp -o g6 && echo link-ok`.
Expected: `link-ok`. (On macOS this check catches a crashing `dsymutil`;
Linux has no `dsymutil` step.)

## P. clang-p2996 (source build)

Set `P2996=/opt/p2996` (the mounted volume). The Linux install uses plain
tool names under `$P2996/bin` (`clang++`, `lldb`), not the macOS `-p2996`
suffixes, and is never on `PATH`.

**P1. Commit and build flags.** Probe: `"$P2996/bin/clang++" --version`.
Expected: the pinned commit (today `562409c7942690d59ea470762515f88f24b16e23`)
and `Build config: +assertions`. PASS if both.

**P2. libc++ by default, and it runs.** Why: with
`CLANG_DEFAULT_CXX_STDLIB=libc++` a plain compile links p2996's libc++, which
lives in `$P2996/lib/x86_64-unknown-linux-gnu`; the binary must find it
without `LD_LIBRARY_PATH`. Probe:
`"$P2996/bin/clang++" -std=c++26 p.cpp -o p2 && ./p2 && ldd p2 | grep 'libc++'`.
Expected: `ok` and a `libc++.so.1` under `$P2996`. PASS if both.

Caveat (the Linux side of the macOS GCC and p2996 rpath caveat): the binary's
`RUNPATH` is `/opt/p2996/bin/../lib/x86_64-unknown-linux-gnu`, the mount
point, not the volume's name (`readelf -d`, 2026-11-15). So removing an old
p2996 volume does not break a program built with it, unlike the Mac's hashed
prefixes. Instead, a program on `/build` loads the libc++ of whichever p2996
volume is mounted at `/opt/p2996` when it runs, with no check that it is the
build it was linked against. With none mounted, the loader goes on past the
`RUNPATH` to the system directories and can load the image's own apt
`libc++.so.1` (clang 23, a different build), which may fail on a missing
symbol or behave differently. Run
it with the volume it was built with, or link the static archives
(`-nostdlib++` with `$P2996/lib/x86_64-unknown-linux-gnu/libc++.a`,
`libc++abi.a` and `libunwind.a`). GCC's `libstdc++` comes from the 26.10
archive in `/usr/lib/x86_64-linux-gnu`, and GCC programs record no `RUNPATH`,
so the macOS GCC caveat does not apply here.

**P3. Hardening default.** Probe:
`grep -rh _LIBCPP_HARDENING_MODE_DEFAULT "$P2996"/include/*/c++/v1/__config_site`.
Expected: `16` (extensive). PASS if `16`.

**P4. Reflection, `import std`, sanitizers (container on the PC's Omarchy
kernel).** `refl.cpp` with `-std=c++26 -freflection-latest` prints
`members=2`; the CMake probe prints `import std ok`; the C6 loop with
`$P2996/bin/clang++` fires ASan, TSan and UBSan (MSan as in C6: recorded,
not required). PASS if all.

**P5. Projects present.** Probe: each of `clangd clang-tidy clang-format
clang-include-cleaner clang-query clang-doc scan-build ld.lld llvm-mca
llvm-cov llvm-profdata llvm-xray lldb lldb-dap mlir-opt` exists in
`$P2996/bin`, and
`"$P2996/bin/clang++" -O2 -mllvm -polly -c -x c++ /dev/null -o /dev/null && echo polly-ok`.
Expected: 15 and `polly-ok`.

**P6. LLVM utilities.** `FileCheck`, `not`, `count` and `yaml2obj` in
`$P2996/bin`. PASS if all four (`LLVM_INSTALL_UTILS=ON`).

**P7. Tools parse reflection.** `clang-tidy`, `clang-format --dry-run` and
`clang-include-cleaner` from `$P2996/bin` on `refl.cpp` (with `--
-std=c++26 -freflection-latest`) exit 0 with no `error:`. PASS if so.

**P8. include-what-you-use.** IWYU 0.25 (the `clang_21` branch head,
`791e69ea4662`) built in the p2996 tree as an LLVM external project
(`LLVM_EXTERNAL_PROJECTS=iwyu`, `IWYU_RESOURCE_RELATIVE_TO=iwyu`), the way
the dotfiles p2996 recipe builds it for macOS (dotfiles #707).
`build-linux.sh` pins the commit, so it is part of the volume's input
hash, and checks the checkout is exactly that commit. Probe:

```sh
"$P2996"/bin/include-what-you-use --version
printf '#include <vector>\nint main() { return 0; }\n' > iw.cpp
"$P2996"/bin/include-what-you-use -std=c++26 iw.cpp
```

Expected: exit 0, `include-what-you-use 0.25`, and a clang version naming
the p2996 commit; then "should remove these lines" with `#include <vector>`
and no `error:` (it found clang's builtin headers next to its own binary),
with exit 0 (without `--error`, IWYU exits 0 after an analysis). PASS if
all.

**P9. Coverage tools match the compiler.** Probe:

```sh
"$P2996/bin/clang++" --coverage -std=c++26 p.cpp -o pc && ./pc >/dev/null &&
"$P2996/bin/llvm-cov" gcov -n pc-p.gcda | head -2
```

Expected: `File 'p.cpp'` and `Lines executed:100.00%` (D88).

**P10. p2996 with `ld.lld`.** Probe:
`"$P2996/bin/clang++" -std=c++26 -fuse-ld=lld p.cpp -o pl && ./pl`.
Expected: `ok`. (On macOS this fails on the SDK's `.tbd` files; Linux has
none.)

P11 to P14 cover the projects and runtimes D136 (amended 2026-11-16) adds
on Linux. `<triple>` is `"$P2996/bin/clang++" -print-target-triple`
(`x86_64-unknown-linux-gnu` or `aarch64-unknown-linux-gnu`).

**P11. flang.** Probe: a `hello.f90` that prints `ok`,
`"$P2996/bin/flang" hello.f90 -o p11 && ./p11` with no `LD_LIBRARY_PATH`.
Expected: `ok` (flang-rt links and is found at run time). PASS if so.

**P12. BOLT on an ELF binary.** Why: BOLT reads only ELF, so Linux is
where it works. Probe: `llvm-bolt`, `perf2bolt` and `merge-fdata` in
`$P2996/bin`, then
`"$P2996/bin/clang++" -std=c++26 -O2 -Wl,--emit-relocs p.cpp -o p12 && "$P2996/bin/llvm-bolt" p12 -o p12.bolt && ./p12.bolt`.
Expected: all three tools and `ok`. PASS if so.

**P13. OpenMP and CPU offload.** Probe: a program with a
`#pragma omp parallel` reduction and a `#pragma omp target` region that
records `omp_is_initial_device()`, built with
`-fopenmp -fopenmp-targets=<triple>` and run with `OMP_NUM_THREADS=2`.
Expected: `threads=2 target_initial=0` (the target region ran through
offload's host plugin, not the fallback), and `ldd` resolves `libomp.so`
under `$P2996`. PASS if both. GPU offload is GO1.

**P14. LLVM libc (overlay).** Probe: `libllvmlibc.a` in
`$P2996/lib/<triple>`; a C program calling `strlen` linked with that
archive and `-Wl,-y,strlen`, then run. Expected: the linker reports the
definition of `strlen` from `libllvmlibc.a`, and the program prints `7`.
PASS if both.

## GO. OpenMP GPU offload

D136 (amended 2026-11-16): every compiler that can offload to the host's GPU
does, and is certified on it. The PC has an NVIDIA GeForce GTX 1660 SUPER
(Turing, `sm_75`), driver 615.78.08. The Mac has no NVIDIA GPU and Docker
Desktop passes no GPU through, so GO1-GO3 are N/A on arm64; the arm64 image
still carries the CUDA toolkits (`linux-sbsa` archives), so offload code
compiles there.

**The container's GPU.** `--privileged` already exposes `/dev/nvidia0`,
`/dev/nvidiactl` and `/dev/nvidia-uvm`. The user-space driver must match the
host's kernel module exactly, so `certify:ubuntu` mounts the host's own,
read-only, after checking it has the version `nvidia-smi` reports:
`libcuda.so.<driver>` as both `libcuda.so.1` and `libcuda.so` (both offload
plugins `dlopen("libcuda.so")`, the unversioned name:
`offload/plugins-nextgen/cuda/dynamic_cuda/cuda.cpp:101` at p2996, `:119` at
LLVM 23), and `libnvidia-ptxjitcompiler.so.<driver>` as
`libnvidia-ptxjitcompiler.so.1` (the driver compiles GCC's PTX with it;
without it libgomp stops with "Cannot map target functions or variables").
The report header names the driver. The upgrade path is CDI: the NVIDIA
container toolkit on the host (through dotfiles-lead), then
`--device nvidia.com/gpu=all`.

**The flags per compiler** (for the GPU presets, when the reference project adds them):

| Compiler | Flags | Why |
|---|---|---|
| p2996 | `-fopenmp --offload-arch=sm_75 --cuda-path=/opt/cuda-12.9` | CUDA 13's `ptxas` writes the new ELF SM encoding (the SM in bits 8-15, `EF_CUDA_SM_MASK`), which LLVM 23 reads (`llvm/lib/Object/ELFObjectFile.cpp:440-444`) and p2996's LLVM 21 does not: with CUDA 13.2 the run stops at "Unknown EF_CUDA_SM value" (`ELFObjectFile.cpp:684`, UNREACHABLE). CUDA 12.9 writes the old encoding. Drop 12.9 when p2996 rebases onto an LLVM that reads the new flags. clang 21 fully supports CUDA up to 12.3; on 2026-11-16 neither p2996 with 12.9 or 13.2 nor clang 23 with 13.2 or 12.9 printed a CUDA version warning for an OpenMP offload compile. `-fopenmp-target-jit` with CUDA 13.2 also runs, but it needs `ptxas` on `PATH` at run time. |
| clang 23 | `-fopenmp --offload-arch=sm_75 --cuda-path=/opt/cuda-13.2` | 13.2 is the newest CUDA clang 23 fully supports (`clang/include/clang/Basic/Cuda.h:54`). `cuda.h` (from `cuda_cudart`) must be there: clang reads the version from it and otherwise assumes "newer than supported" (`clang/lib/Driver/ToolChains/Cuda.cpp:221-231`). |
| GCC 16 | `-fopenmp -foffload=nvptx-none -foffload-options="-fcf-protection=none -march=sm_75"` | Ubuntu's GCC enables `-fcf-protection=full` by default, and the nvptx compiler refuses it ("'-fcf-protection=full' is not supported for this target"); the host code keeps it. No CUDA toolkit. |

The trimmed toolkits take 92 MB (`/opt/cuda-13.2`) and 74 MB (`/opt/cuda-12.9`) in the image (`du -sh` in the image build, 2026-11-16); `cuda_nvcc`, `libnvvm` and `cuda_cudart` 13.2 together unpack to 282 MB.

The runner writes `gpu.cpp`: a target region that sets
`initial = omp_is_initial_device()` and sums 1..100, run with
`OMP_TARGET_OFFLOAD=MANDATORY`, so a host fallback is a fatal error.
Expected: `devices=1 initial=0 sum=5050` (any device count of 1 or more).

**GO1. p2996.** PASS if the expected line.

**GO2. clang 23.** PASS if the expected line.

**GO3. GCC 16.** PASS if the expected line.

With no NVIDIA GPU in the container (`/dev/nvidia0` absent), GO1-GO3 are
N/A. That is the arm64 container in Docker on the Mac: Docker Desktop's
Linux VM gets no GPU, and no LLVM or GCC offload target exists for Apple
GPUs.

## D. Debuggers

Three debuggers: gdb (GCC's), LLVM 23 lldb, and p2996's lldb. The
container runs `--privileged` (D137), so each debugger launches with its
defaults. Under Docker's default seccomp profile instead,
`personality(ADDR_NO_RANDOMIZE)` is refused: lldb, which disables ASLR by
default, then fails with `error: Cannot launch '<program>': personality set
failed: Operation not permitted`, lldb-dap with `configurationDone: resume
request failed - process already running`, and gdb only warns ("Error
disabling address space randomization: Operation not permitted") and runs.
Neither `CAP_PERFMON` nor `CAP_SYS_PTRACE` changes that; only
`--security-opt seccomp=unconfined` or `--privileged` does (measured,
2026-11-15). To tune the flags down later, debug with ASLR on:
`settings set target.disable-aslr false` (in `~/.lldbinit`) and
`"disableASLR": false` in an lldb-dap launch configuration, both of which
work under the default profile (measured). Attaching to a running process
was not probed.

**DB1. gdb (container on the PC's Omarchy kernel).** Probe:

```sh
g++-16 -g -std=c++26 dap.cpp -o dapg
gdb -batch -ex 'break 10' -ex run -ex 'print v' -ex 'print s' -ex kill ./dapg
gdb -batch -ex 'python print(40+2)'
```

Expected: `GNU gdb (Ubuntu 17.2-1ubuntu1) 17.2`, `Breakpoint 1, main () at
dap.cpp:10`, `std::vector of length 3, capacity 3 = {1, 2, 3}` (the
libstdc++ pretty printers), `"p2996"`, and `42`. PASS if all.

**DB2. LLVM 23 lldb (container on the PC's Omarchy kernel).** Probe:

```sh
clang++-23 -g -std=c++26 dap.cpp -o dapd
lldb-23 -b -o 'b dap.cpp:10' -o run -o 'frame variable s' -o kill ./dapd
lldb-23 -b -o 'script print(40+2)'
```

Expected: `stop reason = breakpoint 1.1`, `(std::string) s = "p2996"`, and
`42` (apt's `python3-lldb-23`). PASS if all three.

**DB3. lldb-dap 23 (container on the PC's Omarchy kernel).** The client in
[Appendix: lldb-dap probe](#appendix-lldb-dap-probe) against
`/usr/lib/llvm-23/bin/lldb-dap` and `dapd`. PASS if it prints `PASS`.

**DB4. p2996 lldb (container on the PC's Omarchy kernel).** DB2 with
`$P2996/bin/clang++` and `$P2996/bin/lldb`: breakpoint, `s = "p2996"` from
libc++, and `script` printing `42`. PASS if all.

**DB5. p2996 lldb-dap (container on the PC's Omarchy kernel).** DB3 with
`$P2996/bin/lldb-dap`. PASS if `PASS`. (No code signing on Linux: lldb runs
its own `lldb-server`.)

## L. Library features (headers)

**L1. Required C++26 headers compile.** `<expected> <flat_map> <format>
<mdspan> <print> <ranges>` with `-std=c++26 -fsyntax-only` on clang 23 with
libc++, clang 23 with libstdc++, p2996 and GCC 16. PASS if none is missing.

**L2. Known gaps are guarded, not failed.** Probe:
`printf '#include <version>\n__cpp_lib_generator __cpp_lib_stacktrace\n' > v.cpp`
then `<compiler> -std=c++26 -E -P v.cpp | tail -1`.

| Feature | clang 23 libc++ | p2996 libc++ | libstdc++ 16 (GCC 16, clang 23) |
|---|---|---|---|
| `<generator>` (`__cpp_lib_generator`) | not implemented | not implemented | `202207L` |
| `<stacktrace>` (`__cpp_lib_stacktrace`) | not implemented | not implemented | `202011L` (needs `-lstdc++exp`, L4) |

PASS if the output matches the table. On macOS libstdc++ leaves
`__cpp_lib_stacktrace` undefined; on Linux it is defined.

**L3. Detecting reflection.** As macOS L3: the guard
`#if defined(__cpp_impl_reflection) || __has_feature(reflection)` is true on
GCC 16 with `-freflection` and on p2996 with `-freflection-latest`. PASS if
both print `REFL_YES` for the probe in the runner.

**L4. `<stacktrace>` with GCC links with `-lstdc++exp`.** Why: GCC keeps
`std::stacktrace` in a separate library. Probe:

```sh
printf '#include <stacktrace>\n#include <print>\nint main(){ std::println("frames={}", std::stacktrace::current().size() > 0); }\n' > st.cpp
g++-16 -std=c++26 -g st.cpp -o st            # fails to link
g++-16 -std=c++26 -g st.cpp -o st -lstdc++exp && ./st
```

Expected: the first link fails (`collect2: error: ld returned 1 exit
status`); the second prints `frames=true`. PASS if so.

## H. Hardening presets

**H1. Per-project levels.** The presets in macOS H1 apply unchanged. On
Linux they are mandatory for clang 23: apt's libc++ is built with
`_LIBCPP_HARDENING_MODE_DEFAULT 2`, which is `_LIBCPP_HARDENING_MODE_NONE`
(`1 << 1` in `__config`), so without a preset a libc++ build has no checks.
p2996's own libc++ defaults to extensive (P3).

**H2. The level took effect.** Probe:

```sh
printf '#include <vector>\nint main(){std::vector<int> v(1); return v[5];}\n' > h.cpp
clang++-23 -std=c++26 -stdlib=libc++ h.cpp -o h0 && ./h0; echo "exit=$?"
clang++-23 -std=c++26 -stdlib=libc++ -D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE h.cpp -o h1 && ./h1; echo "exit=$?"
g++-16 -std=c++26 -D_GLIBCXX_ASSERTIONS h.cpp -o h2 && ./h2; echo "exit=$?"
"$P2996/bin/clang++" -std=c++26 h.cpp -o h3 && ./h3; echo "exit=$?"
```

Expected: no trap for `h0`; `exit=132` (SIGILL: on x86 the trap is `ud2`)
for `h1` and `h3`, and on arm64 `exit=133` (SIGTRAP: the trap is `brk`, as
on arm64 macOS); `exit=134`
(SIGABRT) for `h2`. Every compile must succeed, and `h0` must exit
normally (0 to 125: not a signal, and not 126 or 127 from a program that
did not run).
PASS if all four.

## K. Dependencies (vcpkg)

**K1. Three x64-linux triplets.** As macOS K1, with `VCPKG_TARGET_ARCHITECTURE
x64` and `VCPKG_CMAKE_SYSTEM_NAME Linux`: `x64-linux-gcc16`,
`x64-linux-clang23-libcxx` and `x64-linux-p2996-libcxx` (the design's
`arm64-linux-*` names, amd64 copies from M2). N/A: no C++ project in this
repository yet (D5).

**K2. vcpkg works.** Probe: `vcpkg version | head -1`. PASS if it prints a
version.

## E. Editor and code navigation

**E1. Compile database.** As macOS E1. N/A until there is a project.

**E2. clangd matching clang 23.** Why: clangd parses with its own frontend,
so it should be the same version as the compiler. Probe:
`/opt/llvm-23.1.5/bin/clangd --version` against `clang++-23
--version`, and `clangd --check=e.cpp` on a libstdc++ file with a
`compile_commands.json` entry for `clang++-23`. PASS if the versions are
equal and the check ends `All checks completed, 0 errors`.
Today: FAIL. apt.llvm.org's `clangd-23` does not install on 26.10:

```text
clangd-23 : Depends: libabsl20260107 (>= 20260107.0-0~) but it is not installable
            Depends: libre2-11-absl20260107 but it is not installable
```

26.10 has `libabsl20260526` only. The packages are built for resolute,
whose Abseil differs; no other installed LLVM 23 binary lacks a library (an
`ldd` scan of the 196 ELF files of the installed packages found none
missing). Mixing in resolute's Abseil is not allowed by the D25/D27 pins.
The image therefore takes clangd from the nearest release tarball, 23.1.5,
whose clangd loads (no missing libraries) and checks the file with 0 errors
using libstdc++ 16's headers and the tarball's own clang 23.1.5 builtin
headers. The version still differs from the apt snapshot (23.1.6), so E2
stays FAIL. Fix, in order of preference:

1. When llvmorg-23.1.6 ships, take clangd from its tarball (verify its
   `.jsonl` attestation first). Pros: same version, same pattern as the Mac
   (D38). Cons: a second source for one LLVM tool.
2. When apt.llvm.org adds a stonking suite (D25 already says to switch),
   use its `clangd-23`. Pros: one source. Cons: no date.
3. The standalone `clangd/clangd` releases. Pros: small. Cons: a third
   source, versioned separately; not checked here.

**E3. clangd for reflection.** Probe (with
`printf -- '-std=c++26\n-freflection-latest\n' > compile_flags.txt`):
`"$P2996/bin/clangd" --check=refl.cpp`. Expected: `All checks completed, 0
errors`.

## T. Static and dynamic analysis

**T1. clang-tidy and clang-format.** Rule: the LLVM 23 tools for plain
projects, the p2996 tools for reflection projects (P7, D19).

**T2. Clang Static Analyzer.** Probe: `scan-build-23 --help | head -1`.
Expected: `USAGE: scan-build [options] <build command> [build options]`.

**T3. IWYU.** An IWYU built against LLVM 23 for clang 23 projects, and P8's
for p2996. The 26.10 archive has `iwyu 8.23-1build1`, which reports
`include-what-you-use 0.23 based on Ubuntu clang version 19.1.7` and pulls
in clang 22 (B2), so it is not used. Instead the image builds IWYU 0.27 in
a separate stage (`ubuntu-cert.Dockerfile`, stage `iwyu`) against
apt.llvm.org's `llvm-23-dev` and `libclang-23-dev` from the same 23.1.6
snapshot as clang-23, installs it in `/opt/iwyu-llvm23`, and links
`include-what-you-use`, `iwyu_tool.py` and `fix_includes.py` into
`/usr/local/bin`. The development packages stay out of the final image.
The pin is commit `c9cbc836a1af`, which is both IWYU's tag 0.27 and the
head of its `clang_23` branch (checked 2026-11-15). Probe: as P8, with
`include-what-you-use` from `PATH`. Expected: exit 0,
`include-what-you-use 0.27` and the same `clang version 23.1.6` that
`clang++-23 --version` prints; then the unused `<vector>` flagged with no
`error:`. PASS if all.

Risk: apt.llvm.org deletes old snapshots within days (D12). If the 23.1.6
snapshot is gone, this image cannot be rebuilt as written: keep the built
image (it is the record), and for a new image move `LLVM_VER` to the
current snapshot, rebuild, and rerun the full certification (C1 and T3
check the versions match).

**T4. More sanitizers.** Probe:

```sh
for f in realtime type; do clang++-23 -std=c++26 -fsanitize=$f p.cpp -o t_$f && ./t_$f; done
clang++-23 -fsanitize=fuzzer fuzz.cpp -o fz && ./fz -runs=16 2>&1 | grep 'Done 16 runs'
```

`fuzz.cpp` is [Appendix: fuzz probe](#appendix-fuzz-probe), the same file as
macOS T4. Expected: `ok` twice, then `Done 16 runs` and exit 0. PASS if
all. `-fsanitize=fuzzer` needs a `LLVMFuzzerTestOneInput` target: linking
`p.cpp` with it fails here (`undefined reference to
'LLVMFuzzerTestOneInput'`).

**T5. Valgrind.** Why: D19 runs Valgrind on Linux GCC; D35 takes
deterministic instruction counts from it. Probe (GCC, `-g -O0`):
`valgrind --leak-check=full ./leak` reports `definitely lost: 16 bytes`; a
read one past a `new int[2]` reports `Invalid read of size 4`;
`--tool=callgrind` prints `Collected`; `--tool=cachegrind --cache-sim=yes`
prints the `D1  miss rate`. PASS if all four. Today: PASS (valgrind-3.27.1).

**T6. Tier-2 tools.** cppcheck (2.21.0, archive), ClangBuildAnalyzer,
clang-uml, mrdocs: N/A until D19 moves them to tier 1.

**T7. XRay.** Probe:

```sh
clang++-23 -std=c++26 -fxray-instrument -fxray-instruction-threshold=1 p.cpp -o px &&
XRAY_OPTIONS="patch_premain=true xray_mode=xray-basic" ./px; ls xray-log.*
```

Expected: `ok` and an `xray-log.px.*` file. PASS if the log exists. (XRay
works on Linux; on macOS it does not, macOS T7.)

## R. Profiling and metrics

**R1. perf (container on the PC's Omarchy kernel).** Probe: `perf
--version`. Expected: `perf version 7.3.0` (package `linux-perf
7.3.0-10.10`; Ubuntu 26.10 ships `/usr/bin/perf` in `linux-perf`, not in a
kernel-versioned `linux-tools` package). The host kernel is 7.2; perf 7.3
runs against it.

**R2. Hardware counters (container on the PC's Omarchy kernel).** Why: D35
takes hardware counters from the PC. Probe:
`perf stat -x, -e cycles,instructions,cache-misses,branch-misses -- ./p`.
PASS if all four are counted. Needs `CAP_PERFMON`, which `--privileged`
includes (V2). Outside the
Level-1 gate: D46 moves the PMU check to Level 2, and only callgrind
instruction counts (R7) are Level 1. arm64 on the Mac: N/A. Docker
Desktop's VM exposes no hardware PMU (`/sys/bus/event_source/devices` holds
only `breakpoint kprobe software tracepoint uprobe`); the line lists them.
U3's `instructions:u` counts are absent there for the same reason.

**R3. Sampling (container on the PC's Omarchy kernel).** Probe:
`perf record -F 999 -g -o r.data -- ./p && perf report -i r.data --stdio`.
PASS if the report has sample lines. With the host's `kptr_restrict=0`, perf
warns that it could not record the kernel reference relocation symbol; user
samples are unaffected. arm64 on the Mac, with no hardware PMU (R2): it
samples the software `cpu-clock` event instead of cycles, on a 0.3 s loop,
since a timer cannot sample a program that ends in a millisecond; the line
says so.

**R4. llvm-mca.** Probe: `clang++-23 -O2 -march=znver3 -S k.cpp -o k.s &&
llvm-mca-23 -mcpu=znver3 k.s | grep Iterations` (and the same with p2996),
with `k.cpp` the dot product from macOS R4. Expected: `Iterations: 100`
twice. Hand run: `Total Cycles: 1347`, `Block RThroughput: 13.2`. arm64:
the same with `-mcpu=apple-m2` for both the compile and llvm-mca.

**R5. Build timing.** `clang++-23 -std=c++26 -ftime-trace -c p.cpp` writes
`p.json`. PASS if so.

**R6. Benchmark timing.** `hyperfine --version` prints a version.

**R7. Deterministic instruction count.** Why: D46 keeps
`perf:instructions` (callgrind, no privileges) in Level 1. Probe: run
`valgrind --tool=callgrind` twice on the same `-O2` binary. PASS if both
print the same `Collected` count.

## U. CPU target

Which `-march` to build with is a trade between speed on the machine and
running elsewhere. These checks measure it; the choice is D137 for amd64.
arm64 (proposed in the Part B pull request, decided there): the targets are
`-march=armv8-a` (the portable baseline), `-march=armv8.2-a`,
`-march=armv8.6-a` (the M2's level) and `-mcpu=apple-m2`, with
`armv8.2-a` against `apple-m2` in U2. Docker Desktop's VM hides the CPU
model (MIDR part `0x000`), so `g++-16 -mcpu=native` says `generic`: on
arm64, U1 shows only that every target builds, not that a target is tuned to
a CPU the container can see, and U3's times are for the M2 under the VM.

**U1. Targets accepted.** Probe: both compilers compile with
`-march=x86-64`, `-march=x86-64-v3`, `-march=x86-64-v3 -mtune=znver3` and
`-march=znver3`, and `g++-16 -march=native -Q --help=target | grep
'march='` prints `znver3`. PASS if all. arm64: both compilers build each
arm64 target above; `-mcpu=native` is recorded. PASS if all build.

**U2. What znver3 adds over x86-64-v3.** Probe: the difference of
`g++-16 -march=x86-64-v3 -Q --help=target` and the same with
`-march=znver3`, enabled `-m` options only. Hand run (GCC 16.2): `abm adx
aes clflushopt clwb clzero fsgsbase mwaitx pclmul pku prfchw rdpid rdrnd
rdseed sha sse4a vaes vpclmulqdq wbnoinvd xsavec xsaveopt xsaves`. clang 23
adds the same set (its macros also show `INVPCID`; GCC's list shows `abm`
and `clflushopt`). A binary built with `-march=znver3` may use any of these
and stops with SIGILL on a CPU without one; an `x86-64-v3` binary needs only
the v3 set (AVX2, BMI2, FMA, MOVBE and the rest of the psABI level). N/A:
the list is the evidence. arm64: `armv8.2-a` against `-mcpu=apple-m2`,
from clang's `__ARM_FEATURE_*` macros, because GCC's `-Q --help=target`
lists no AArch64 extensions. On 2026-11-16: `AES BF16 BF16_SCALAR_ARITHMETIC
BF16_VECTOR_ARITHMETIC BTI COMPLEX CRYPTO DOTPROD FP16_FML
FP16_SCALAR_ARITHMETIC FP16_VECTOR_ARITHMETIC FRINT JCVT MATMUL_INT8 PAUTH
RCPC SHA2 SHA3 SHA512`.

**U3. Measured speed per target.** Probe: `bench.cpp` from
[Appendix: bench probe](#appendix-bench-probe), built with `g++-16 -O2` for
each U1 target, run with `hyperfine` (best of 5, pinned to cores 2-5), and
`perf stat -e instructions:u`. Every build must print the same result. N/A:
the times are the evidence for D137; FAIL only if a build fails or the
outputs differ. Today (2026-11-15, runners idle): x86-64 241 ms and
1,543,403,602 instructions; x86-64-v3 244 ms and 1,270,336,752;
x86-64-v3 with `-mtune=znver3` 244 ms; znver3 245 ms and 1,270,336,751.
v3 retires 18% fewer instructions than generic x86-64, at a wall time
within 1.2% (four runs that day: v3 244-246 ms, x86-64 241-244 ms); znver3 gains nothing
measurable over v3. D137 picks `x86-64-v3`. One benchmark is thin
evidence: re-measure on the reference project.

**U4. Linker speed.** Probe: link the same 65 `-O2 -g` objects with
`-fuse-ld=bfd`, `lld` and `mold` (best of 5). N/A: the times are the
evidence; FAIL only if a link fails. Today: GNU ld 67 ms, lld 37 ms, mold
27 ms.

**U5. LTO and PGO.** Probe: `bench.cpp` with `g++-16 -flto=auto`,
`clang++-23 -flto=thin -fuse-ld=lld`, and a profile-generate, run,
profile-use cycle with each compiler (`llvm-profdata-23 merge` for clang).
PASS if all four build and print the same result as plain `-O2`.

## V. Container runtime (near-native)

The owner's goal: the container runs as close to the PC's native speed as
possible. Each check measures one part of that.

**V1. No CPU or memory limits (container on the PC's Omarchy kernel).**
Probe: `cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max; nproc`.
Expected: `max 100000`, `max`, and 24 (the host's thread count). PASS if so.
`certify:ubuntu` passes no `--cpus`, `--memory` or `--cpuset-cpus`.

**V2. Privileged, and what each narrower flag gives (container on the PC's
Omarchy kernel).** Why: Docker's default seccomp profile refuses `perf_event_open`
unless the container holds `CAP_PERFMON` (or `CAP_SYS_ADMIN`); the host's
`perf_event_paranoid` is 2 (user-space counts only without
`CAP_PERFMON`; linux v7.2 `Documentation/admin-guide/perf-security.rst`).
The host's Yama `ptrace_scope` is 1 (`/proc/sys/kernel/yama/ptrace_scope`):
a process may trace only its descendants unless it holds `CAP_SYS_PTRACE`
(`Documentation/admin-guide/LSM/Yama.rst`). lldb launches its inferior as
a child (DB2, DB4), which level 1 allows, and `--privileged` holds
`CAP_SYS_PTRACE` for attach. Measured on 2026-11-15 with `perf stat -e
instructions:u` and `perf record` on the same binary:

| Flags | perf | lldb `run` (ASLR off) |
|---|---|---|
| none (default seccomp) | refused: "No permission to enable instructions:u event" | refused (`personality`) |
| `--cap-add PERFMON` | user and kernel counts, record works | refused |
| `--cap-add PERFMON --cap-add SYS_PTRACE` | the same | refused |
| `--security-opt seccomp=unconfined` | user-only counts (paranoid 2) | works |
| `--privileged` | user and kernel counts | works |

The owner chose `--privileged` (D137: "get it to work, it is always easier
to tune down"), so perf and the debuggers' defaults work without
workarounds. Probe: `grep -E '^(CapEff|Seccomp):' /proc/self/status`. PASS
if `CapEff` has bit 38 (`CAP_PERFMON`) and bit 21 (`CAP_SYS_ADMIN`) and
`Seccomp` is 0 (no filter): the `--privileged` container. Security cost: the
container has every capability, every host device and no syscall filter,
so it can read host-wide performance data and kernel addresses (the host
has `kptr_restrict=0`) and can change the host. It is for the dev and
certification container only, never the CI runner containers, which stay
unprivileged (D48). Tuning down, from the table: `--cap-add PERFMON` alone
gives perf; lldb then needs ASLR left on (section D).

**V3. Process and memory limits (container on the PC's Omarchy kernel).**
Probe: `cat /sys/fs/cgroup/pids.max; ulimit -n; ulimit -l; df -h /dev/shm;
cat /proc/1/comm`. PASS if `pids.max` is `max` or at least 32768, the
kernel's default `pid_max`. Today: `pids.max` is 76881 with or without
`--pids-limit -1`: the host's systemd `DefaultTasksMax` (15% of the
kernel's task limit) sets it, not Docker. Host values on 2026-11-15:
`systemctl show -p DefaultTasksMax` 76881, `kernel.threads-max` 512544,
`kernel.pid_max` 4194304; 15% of the smaller, 512544, is 76881. `nofile` 65536, `memlock` 8192
KiB, `/dev/shm` 64 MiB and no init process are Docker's defaults; no probe
here needed more, so `certify:ubuntu` does not change them.

**V4. Build trees on a volume (timing).** Why: the container's root is
overlayfs on the host's btrfs; a volume is plain btrfs. Probe: the runner
builds a 192-file CMake project with `ninja -j$(nproc)` in the container's
root and in `/build` (the volume), best of 3. PASS if `/build` is not
overlayfs; the times are the evidence. Hand run (fmt 12.1.0, GCC 16,
`-j24`, three runs each, runners idle): overlayfs 27.77-27.99 s, volume
27.58-27.62 s.

**V5. Host settings (container on the PC's Omarchy kernel).** Probe (sysfs
is visible in the container):
`cat /sys/devices/system/cpu/cpu0/cpufreq/{scaling_governor,scaling_driver,energy_performance_preference}
/sys/devices/system/cpu/cpufreq/boost /sys/devices/system/cpu/smt/control
/sys/kernel/mm/transparent_hugepage/enabled`. N/A: reported, never changed.
Today: governor `powersave` with `amd-pstate-epp` and EPP
`balance_performance`, boost 1, SMT on, THP `always`. These move wall times
on both sides of V6 alike; a host change goes through dotfiles-lead.

**V6. Host vs container A/B (timing).** Why: "near native" has to be
measured. Probe (`certify:ubuntu --ab`): export the container's filesystem
to `/var/tmp/cpp-standard-cert-ab` on the host, then run the same workload
three times on each side, alternating: in the container, and on the host
in that same filesystem under `bwrap` (bubblewrap, a user namespace with no
cgroup limits, seccomp profile or overlayfs). The workload is compiling
`heavy.cpp` ([Appendix: heavy probe](#appendix-heavy-probe)) and running
`bench.cpp`, both on cores 2-5, timed with `hyperfine` (best of 5) and
counted with `perf stat -e instructions:u`. The directory is deleted at the
end. PASS if the container is at most 2% slower than the host on both. The
host's `perf_event_paranoid` is 2, so the host side can count only user
space: equal `instructions:u` shows both sides ran the same code, and the
container's overhead (syscalls, seccomp filtering, overlayfs) shows only in
wall time. Today: PASS (2026-11-15, runners idle). Compile 5021 ms in the
container vs 5029 ms on the host (-0.2%); benchmark 243 vs 243 ms (+0.0%);
`instructions:u` within 0.02% (compile) and 0.001% (benchmark). Three
earlier runs the same day gave +0.6%, +0.2% and +0.0% (compile) and
+0.4%, +0.4% and +0.0% (benchmark). The
rootfs (2,843 MB) was removed after the run. arm64: N/A. The Docker host is
Docker Desktop's Linux VM, and the Mac runs macOS, so no host runs this
toolchain natively to compare against.

## Report

```text
Ubuntu certification  <label>  <date>
Ubuntu 26.10  kernel <A4> (container on the PC's Omarchy kernel)  glibc <A5>
CPU <model>  Docker <version>  image <id>
docker run flags: <flags>
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

Build `san.cpp` and `leak.cpp` without `-O`. Measured at `-O2` (2026-11-16,
amd64, both the archive `g++-16` and a GCC 16.2.0 built from the release
tarball):

- `leak.cpp` has no allocation left: `-S` output has 0 calls to
  `operator new[]`, against 1 at `-O0`. LeakSanitizer then reports nothing.
- TSan reported the race in only 2 to 6 of 10 runs, with either compiler.

Neither is a compiler or hardening difference. Adding `-O2` to G4 makes its
LSan probe fail every time and its TSan probe fail some of the time. A
sanitizer report at `-O2` still means what it says; only a missing report
proves nothing. The clang runs (C6) were not measured at `-O2`.

### Appendix: fuzz probe

```cpp
// fuzz.cpp: a libFuzzer target; -fsanitize=fuzzer supplies main.
#include <cstddef>
#include <cstdint>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* d, size_t n) {
  return n > 0 && d[0] == 0xff ? 0 : 0;
}
```

### Appendix: bench probe

```cpp
// bench.cpp: CPU-bound kernels for the CPU-target (U3) and A/B (V6) checks.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <vector>
int main(int argc, char**) {
  const std::size_t n = std::size_t{1} << 22;
  std::vector<std::uint32_t> a(n), b(n);
  std::uint64_t x = 88172645463325252ull + std::uint64_t(argc);
  for (std::size_t i = 0; i < n; ++i) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    a[i] = std::uint32_t(x); b[i] = std::uint32_t(x >> 32);
  }
  std::uint64_t sum = 0;
  for (int r = 0; r < 40; ++r)
    for (std::size_t i = 0; i < n; ++i)
      sum += std::uint64_t(a[i] ^ (b[i] >> (r & 7))) * (a[i] | 1u);
  std::sort(a.begin(), a.end());
  std::printf("%llu\n", static_cast<unsigned long long>(sum + a[n / 2]));
}
```

### Appendix: heavy probe

```cpp
// heavy.cpp: a header-heavy translation unit for the A/B compile (V6).
#include <chrono>
#include <format>
#include <map>
#include <ranges>
#include <regex>
#include <string>
#include <unordered_map>
#include <vector>
std::string heavy(const std::vector<int>& v) {
  std::map<int, std::string> m;
  for (int x : v | std::views::filter([](int i) { return i % 2 != 0; })) m[x] = std::format("{}", x);
  std::regex r("[0-9]+");
  std::unordered_map<std::string, int> u;
  for (auto& [k, s] : m)
    if (std::regex_match(s, r)) u[s] = k;
  return std::format("{} {}", u.size(), std::chrono::seconds(m.size()));
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
clang++-23 -g -std=c++26 dap.cpp -o dapd
python3 -I dap_probe.py /usr/lib/llvm-23/bin/lldb-dap dapd dap.cpp 10
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

## Appendix: p2996 build

The build inputs are files in this repository, in
[`ubuntu-p2996/`](ubuntu-p2996/): the script `build-linux.sh`, the
`linux/scc.h` patch from `spikes/m0/h/patches/` (D105), and
`lldb-base-specifier-derived.patch`, copied from the dotfiles p2996 recipe
(`python/toolchains/p2996/src/p2996/patches/`, last changed in dotfiles
`9550cea`). sha256 on 2026-11-16:

| File | sha256 |
|---|---|
| `build-linux.sh` | `fc4b5f0eceac79d9452335bc0b4a4412d6a98849e91ccaa9ef1e022eaa33b58d` |
| `compiler-rt-remove-linux-scc-h.patch` | `c9e835ef4f553b03246d9371bc0ec4b9215e1fb7ef0714e2964ea8cda8562443` |
| `lldb-base-specifier-derived.patch` | `7e83f3e0b77422037eaa08e454b57e1e80227a7dd51bc5fcf68960530f66ddc5` |

The install goes into a Docker volume named
`cpp-standard-p2996-<commit12>-<inputs12>`. `<inputs12>` is the first 12 hex
digits of the sha256 of the three files concatenated in that order (today
`cpp-standard-p2996-562409c79426-d3773989aa5d`). A new commit or a changed
input gives a new volume; an existing one is never overwritten. The name
does not include the architecture: the amd64 volume on the PC and the arm64
volume in the Mac's Docker Desktop have the same name, built from the same
inputs. That is safe while each Docker host holds one architecture; a host
that held both would need the architecture in the name. Adding it now would
rename the PC's certified amd64 volume, so it waits for the next input change.
`certify:ubuntu` computes the same name and mounts it read-only at
`/opt/p2996`. `CERT_P2996_VOL=<volume>` mounts another volume instead, to
check a scratch build before it gets its final name; the report header names
the volume mounted.

Run it in a throwaway container from the certified image, with the build
dependencies named in "The p2996 build" installed in that container
only, the three files next to each other, the volume (created with
`--label org.cpp-standard.cert=1`) at `/opt/p2996`, and the kept sccache
volume `cpp-standard-sccache` at `/sccache`:
`build-linux.sh /work /opt/p2996 20`. Every compile goes through sccache
(`CMAKE_<LANG>_COMPILER_LAUNCHER`), and the script prints
`sccache --show-stats` at the end, so a rebuild after an input change that
leaves the LLVM sources alone is mostly cache hits. Measured on 2026-11-15:
the first build missed all 6134 compiles and filled 633 MB of cache; a
rebuild of the same tree from an empty build directory hit all 6134 and
took 93 s, where a full build takes about 45 minutes. Adding IWYU (P8)
changed the inputs; that build hit 6134 of 6149 compiles (the 15 misses are
IWYU's own) and took 215 s. On 2026-11-16 the full project list,
NVPTX and the new image (whose clang 23 is a different build, so no cache
entry matched) missed all 6590 compiles and took 49 min 49 s with 20 jobs.
arm64, the same day, in the Mac's Docker Desktop: the same three files,
`build-linux.sh /work /opt/p2996 4` in a container capped at `--cpus 4
--memory 16g`, missed all 6576 compiles and took 76 min 28 s, with no
out-of-memory kill. The result defaults to `aarch64-unknown-linux-gnu`,
with the AArch64 and NVPTX back ends; the volume is 7.5 GB and its cache
1.06 GB.
M1a replaces it with
`toolchains/p2996/` and the hash-keyed builder (D49, D85).

## Sources

- Commands run in the container on the PC, 2026-11-14 and 2026-11-15:
  image `ubuntu:26.10@sha256:b5194b8e...56f7`, the packages in "The end
  state", Docker 29.9.2 on the host.
- apt metadata: `apt-cache show clangd-23` (its `Depends`),
  `apt-cache policy` for every pinned package, `apt-cache show iwyu`.
- LLVM: release `llvmorg-23.1.5` assets and digests (GitHub API);
  `libcxx/include/__config` (`_LIBCPP_HARDENING_MODE_*` values) and
  `__config_site` as installed by `libc++-23-dev`.
- clang-p2996: `bloomberg/clang-p2996` at `562409c7`;
  `docs/designs/level-1/research/p2996-linux.md`; `spikes/m0/README.md`
  (M0 (c), (f), (h)). The project and runtime list, offload and the CUDA
  ELF flags: that tree's `llvm/`, `bolt/`, `flang/`, `libc/`, `openmp/`,
  `offload/`, `libclc/`, `llvm-libgcc/` and `runtimes/` CMake files and
  `llvm/lib/Object/ELFObjectFile.cpp`, at the lines cited.
- LLVM 23 offload: `llvm/llvm-project` at `551bf48cf74f` (the apt
  snapshot's commit): `openmp/docs/Building.md`, `openmp/device/`,
  `clang/lib/Driver/ToolChains/{Cuda,CommonArgs}.cpp`,
  `clang/include/clang/Basic/Cuda.h`, `llvm/lib/Object/ELFObjectFile.cpp`;
  the contents of the apt `liboffload-23`, `libomp-23-dev` and other llvm-23
  packages (`dpkg -c`), and of `LLVM-23.1.5-Linux-X64.tar.xz` (`tar -t`).
- arm64: compiler-rt's `AllSupportedArchDefs.cmake:94,96` (memprof and
  nsan are x86_64 only) at LLVM `551bf48cf74f`; the arm64 `apt-cache madison`
  of every pinned package in an arm64 `ubuntu:26.10` container (all 37 at
  the same versions); NVIDIA's `linux-sbsa` redistributables in the same
  JSON files; mise's and LLVM's release digests for the arm64 assets.
- CUDA: NVIDIA's `redistrib_13.2.2.json` and `redistrib_12.9.2.json`
  (<https://developer.download.nvidia.com/compute/cuda/redist/>), the source of
  every archive digest in the image.
- GPU offload runs (GO): commands run in the container on the PC on
  2026-11-16, NVIDIA driver 615.78.08, GTX 1660 SUPER.
- Docker: the default seccomp profile and capability behaviour as measured in
  V2 and DB2 (Docker 29.9.2, server commit `0367cbeb49`). Primary sources
  requested offline for openwiki (workspace `cpp-standard`): moby
  `profiles/seccomp/default.json` at that commit, the `docker run`
  reference, the kernel's `perf-security.rst` and `sysctl/kernel.rst`,
  `perf_event_open(2)`, `capabilities(7)`, `personality(2)`, GCC 16.2
  `x86-tune.def` and `invoke.texi`, LLVM `X86.td` and the Znver3 scheduling
  model, AMD's Family 19h Software Optimization Guide, valgrind 3.27.1,
  glibc 2.44 NEWS, systemd `DefaultTasksMax`, and bubblewrap 0.13.1.
