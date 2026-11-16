# GPU offloading on the Mac's Apple GPU (2026-11-16)

The owner's rule (D136, amended 2026-11-16): "GPU offloading support for any
compiler that supports it on the host." The host GPU is an Apple M2 Max
(`system_profiler SPDisplaysDataType`: vendor Apple (0x106b), 38 cores,
"Metal Support: Metal 4"), on macOS 27.2. Asked what the macOS playbook should
do about it, the owner answered "all of the above": record why the stock
compilers cannot offload, build AdaptiveCpp with its Metal backend and probe
it, and build chipStar and probe it.

Every claim below names its source. Upstream repositories were read at:

| Repository | Commit | Date |
|---|---|---|
| AdaptiveCpp/AdaptiveCpp | `fe81de555a801f2847489e23ac9b638514966986` | 2026-11-12 |
| CHIP-SPV/chipStar | `d3ce6238f6219ac4c4ea7cdf92f42624c37114c3` | 2026-11-11 |
| kpet/clvk | `9862fce7d1b9b68a45986ef5e15b2fb81e417246` | 2026-11-15 |
| llvm/llvm-project (p2996 base) | `562409c7942690d59ea470762515f88f24b16e23` | |

## 1. Why stock clang and GCC cannot offload to an Apple GPU

- **No Apple GPU target in clang.** "Clang supports offloading to X86_64,
  AArch64, PPC64[LE], NVIDIA GPUs (all models) and AMD GPUs (all models)"
  (<https://clang.llvm.org/docs/OpenMPSupport.html>, read 2026-11-16).
- **No offload runtime on macOS.** libomptarget refuses to build there:
  "libomptarget cannot be built on Windows and MacOS X"
  (`offload/CMakeLists.txt:15-16` at `562409c7`). So even the CPU host plugin,
  which Ubuntu builds, is missing on the Mac (playbook, "What macOS cannot
  have").
- **No LLVM backend for Apple's GPU IR (AIR) or Metal.** An RFC of
  2026-05-29, "[RFC] Add an Apple Metal/AIR backend target"
  (<https://discourse.llvm.org/t/90936>), proposes an experimental target
  that lowers LLVM IR to a `.metallib`. The author says: "To my knowledge
  there is no open-source path from arbitrary LLVM IR to a loadable .metallib
  today". A reviewer replied on 2026-06-24 that "all of them at once make it
  extremely unlikely that you can get this merged". The red flags include no
  word from Apple; the author: "I definitely don't know how to approach say an
  Apple official to give their say on the idea of this".
- **An earlier OpenMP prototype was never upstreamed.** A reply in August 2023
  in "llvm OpenMP support for Apple Silicon"
  (<https://discourse.llvm.org/t/59120/4>) says: "We can now get simple
  computation running on macOS but nothing is or is able to be upstreamed
  yet."
- **An LLVM maintainer calls it possible but not planned.** On the Darwin
  OpenMP-offload driver fix (llvm/llvm-project#186208, comment of 2026-03-12,
  <https://github.com/llvm/llvm-project/pull/186208#issuecomment-4049352069>):
  "It would be theoretically possible to make a Metal backend to do GPU
  offloading there."
- **GCC offloads only to NVIDIA and AMD.** The offload targets are
  `nvptx-none` and `amdgcn-amdhsa` (`gcc/doc/install.texi:2681-2690`,
  releases/gcc-16). There is no Apple GPU target.

So p2996, clang 23 and GCC 16 get no GPU check on the Mac. That is not a gap
in the playbook: no build of these compilers can offload there.

## 2. AdaptiveCpp: SYCL and C++ standard parallelism on Metal

**What it is.** AdaptiveCpp is a SYCL implementation whose "generic"
single-pass compiler (SSCP) puts LLVM IR into the binary and JIT-compiles it
for the device at run time. The Metal backend was merged in
`94e174989894a2b91486f8ad1d9e9dfd6493edac` ("Add Metal Backend (#1961)",
2026-02-26). `doc/install-metal.md` says the flow "compiles SYCL kernels to
LLVM IR at compile time, then translates that IR to Metal Shading Language
(MSL) at runtime". So it uses Apple's own MSL compiler and needs no LLVM
backend for AIR.

**Status and limits** (`doc/install-metal.md`):
- "The Metal backend is experimental".
- "macOS 26. The backend has only been tested on macOS 26". This host runs
  macOS 27.2.
- "`double` is not supported" (no fp64 in Apple GPUs). 64-bit atomics are
  emulated. `sycl::stream` and printf are not supported. Pointer-to-integer
  casts are limited.
- Open Metal issues: #2311 (last-work-group reduction gives wrong results),
  #2312 (`__acpp_sscp_get_num_subgroups` is not implemented), #2313 ("Conflicting
  address space information in PHI node"). #2310 (atomic capability queries)
  is not Metal-specific.

**Which LLVM.** The evidence rules out each LLVM already on the Mac:

| Candidate | Why not |
|---|---|
| LLVM 23.1.5 tarball (D38) | Above the supported range: configure stops with "LLVM versions greater than 21 are not yet tested/supported" (`CMakeLists.txt:479-481`). It also has no `libLLVM.dylib`. |
| LLVM 21.1.8 release tarball | The SSCP flow links the shared libLLVM: `src/compiler/llvm-to-backend/CMakeLists.txt:41-48` stops with "does not have libLLVM.so" without it. LLVM's release cache (`clang/cmake/caches/Release.cmake` at `llvmorg-21.1.8`) never sets `LLVM_BUILD_LLVM_DYLIB`, and the 23.1.5 tarball, built the same way, has only static `libLLVM*.a`. |
| p2996 (`21.0.0git`) | A development version: configure stops unless `ACPP_EXPERIMENTAL_LLVM=ON` (`CMakeLists.txt:482-486`). `doc/installing.md:29`: "Please do not use a development version or vendor-specific fork of LLVM". It is also built with assertions on, which `doc/install-llvm.md:33` warns against. |
| Homebrew `llvm@20` / `llvm@21` (upstream CI's choice) | Outside mise, global; this repository installs no toolchain through Homebrew (D38). |

The pinned build is therefore **LLVM 21.1.8 from source**: the latest 21.x
release (2025-12-16), the top of the range in the support table
(`doc/installing.md:60`, "LLVM >= 15 and LLVM <= 21"). It builds clang and
lld, plus the openmp runtime for the CPU backend, for AArch64 only, in Release
mode with `LLVM_BUILD_LLVM_DYLIB=ON` and `LLVM_LINK_LLVM_DYLIB=ON`
(`doc/install-llvm.md:33-34`). AdaptiveCpp is then configured as upstream's
Metal CI does (`.github/workflows/macos-metal.yml`): Apple clang as the host
compiler, `-DWITH_METAL_BACKEND=ON`, `-DACPP_COMPILER_FEATURE_PROFILE=full`.
That CI tests LLVM 20; 21 is inside the documented range but has no Metal CI
evidence upstream. The 2-stage build that `doc/installing.md:189-194`
recommends for macOS is for ABI clashes between Apple clang and a separately
built LLVM; the Metal CI does without it.

**metal-cpp.** Apple's C++ wrapper for Metal. The macOS 27.2 SDK has no
`Metal/Metal.hpp`, so `src/runtime/CMakeLists.txt:454-473` fetches
`apple/metal-cpp` at `release/metal-cpp_macOS26_iOS26` unless
`METAL_INCLUDE_DIR` is given. The pinned build passes `METAL_INCLUDE_DIR`
from a checkout at a fixed commit.

**C++ standard parallelism (stdpar).** `--acpp-stdpar` offloads parallel
algorithms such as `std::transform(std::execution::par_unseq, ...)`. Two
caveats from `doc/stdpar.md`:
- "only supported in conjunction with `libstdc++` >= 11 ... Support for
  `libc++` is likely easy to add" (line 8). The Mac uses libc++.
- Offload is heuristic: without `--acpp-stdpar-unconditional-offload` the
  runtime may run a call on the host (`doc/env_variables.md:22-23`). The probe
  compiles with that flag, so a correct result came from the GPU.
- Stack memory cannot be offloaded ("will not offload in this case", line
  152). The probe uses heap vectors.

**Related evidence.** kokkos/kokkos#9750 (open): with about 300 lines of
changes, Kokkos's SYCL backend on AdaptiveCpp Metal passes "all 229
single-precision scaluq tests ... on an Apple M3 Ultra", "Tested only on an
Apple M3 Ultra with macOS 26.7.1 and AdaptiveCpp develop `6c923f68`".

**Results on this host:** see section 4.

## 3. chipStar: CUDA and HIP on the Apple GPU

**What it is.** chipStar compiles CUDA and HIP to SPIR-V and runs it through
OpenCL, Level Zero or Vulkan.

**Three macOS routes exist. Only one is tested upstream on an Apple GPU:**

| Route | Source | GPU? | State |
|---|---|---|---|
| PoCL (OpenCL on the CPU) | `docs/MacOS.md` | **no**, CPU only | The documented macOS setup. It installs into `/etc/OpenCL/vendors` with `sudo` and edits `~/.zshrc`. |
| clvk → MoltenVK → Metal | IWOCL 2026 talk ([slides](https://www.iwocl.org/wp-content/uploads/IWOCL-2026-Velesko-ChipStar.pdf)): "chipStar→ clvk → MoltenVK → Metal on M-series silicon. VERIFIED END-TO-END" on an Apple M4: 4 HeCBench apps pass, "+ 9 partial-PASS" | yes | No build recipe in the chipStar repository. clvk appears only in code comments (`src/CHIPBindings.cc:4207`, `src/backend/OpenCL/CHIPBackendOpenCL.cc:3091`). clvk's own macOS CI runs on Mesa lavapipe, a CPU Vulkan (`kpet/clvk` `.github/workflows/presubmit.yml:207-215`). Khronos has deprecated MoltenVK: "For Vulkan on Metal, Khronos now recommends KosmicKrisp on Apple Silicon Macs" (KhronosGroup/MoltenVK README). |
| Native Vulkan on Mesa KosmicKrisp | `.github/workflows/unit-tests-macos-vulkan.yml` ("Apple M4 through Mesa KosmicKrisp (Vulkan on Metal)") | yes | Upstream's only Apple-GPU CI. Needs `-DCHIP_USE_NATIVE_VULKAN_SPIRV=ON`, which "requires LLVM 24+" (`CMakeLists.txt:491-494`), plus libclc built for `spirv64-unknown-vulkan` (`README.md:156`). LLVM 24 is not released, so this means a pinned commit of LLVM main. Known failures are listed under `kosmickrisp-m4` (`tests/known_failures.yaml:620`). |

**Owner decision (2026-11-16, via cpp-standard-lead):** route 3, the upstream
CI route, after AdaptiveCpp is done. Later the same day all Apple GPU work
was put on hold (see "Status").

**KosmicKrisp build cost** (from <https://docs.mesa3d.org/drivers/kosmickrisp.html>):
"a Vulkan conformant implementation for macOS on Apple Silicon hardware ...
on top of Metal 4, which requires macOS 26 and up". Requirements: meson
1.9.1+, cmake, pkg-config, libclc, LLVM 20.1.8+, spirv-llvm-translator,
spirv-tools (static preferred), and the Python packages mako, packaging and
pyyaml. Configure line: `meson setup <mesa> -Dplatforms=macos
-Dvulkan-drivers=kosmickrisp -Dgallium-drivers= -Dopengl=false
-Dzstd=disabled --prefer-static`. Here every dependency comes from a pinned
source build or a project-local Python virtual environment, never Homebrew.
The LLVM main build that chipStar needs (with libclc) can serve Mesa too.
Estimate at `-j6`: LLVM main with clang, lld and libclc 60-90 min;
SPIRV-LLVM-Translator and SPIRV-Tools about 10 min; Mesa with only
KosmicKrisp about 15 min; the Vulkan loader a few minutes; chipStar about 15
min.

## 4. Results on this host

**Spike (2026-11-16): AdaptiveCpp `fe81de555a80` against p2996.** This was
a feasibility run in a scratch directory, configured with
`-DACPP_EXPERIMENTAL_LLVM=ON`. It was not the pinned build. It checked that
the Metal backend works on macOS 27.2, where upstream has tested only 26,
before LLVM 21.1.8 was built. Verbatim output:

```text
$ acpp-info -l
Loaded backend 0: OpenMP
  Found device: AdaptiveCpp OpenMP host device
Loaded backend 1: Metal
  Found device: Apple M2 Max

$ acpp -O2 -o sycl acpp_sycl.cpp && ./sycl
device: Apple M2 Max (Metal (platform 0))
[AdaptiveCpp Warning] kernel_cache: This application run has resulted in new binaries being JIT-compiled. ...
sycl: 0/1048576 wrong
```

stdpar with the Mac's libc++
(`acpp -O2 --acpp-stdpar --acpp-stdpar-unconditional-offload acpp_stdpar.cpp`):

```text
include/AdaptiveCpp/hipSYCL/std/stdpar/detail/execution_fwd.hpp:14:10: fatal error: 'pstl/execution_defs.h' file not found
1 error generated.
```

Workaround tried: the same probe with GCC 16's libstdc++ (the D33 build;
`-nostdinc++ -isystem <gcc>/include/c++/16 -isystem
<gcc>/include/c++/16/aarch64-apple-darwin27 -nostdlib++ -lstdc++`). It
compiles, then fails to link, because the AdaptiveCpp runtime is built
against libc++:

```text
Undefined symbols for architecture arm64:
  "hipsycl::rt::dag_builder::add_command_group(std::unique_ptr<hipsycl::rt::operation, std::default_delete<hipsycl::rt::operation>>, hipsycl::rt::requirements_list const&, hipsycl::rt::execution_hints const&)", referenced from: ...
  "hipsycl::rt::result::what[abi:cxx11]() const", referenced from: ...
```

So GO6 (stdpar) is a known upstream FAIL, and GO5 (SYCL) is the GPU proof.

**Why a libstdc++ runtime alone cannot fix stdpar.** The owner asked
whether a second AdaptiveCpp runtime built with libstdc++ would let GO6 pass.
On its own it would not. The runtime calls the JIT translator with standard
library types across a C++ interface:
- `src/runtime/metal/metal_queue.cpp:943-944` calls
  `compiler::createLLVMToMetalTranslator(kernel_names)`.
- `include/hipSYCL/compiler/llvm-to-backend/LLVMToBackend.hpp:53-80`:
  `LLVMToBackendTranslator`'s constructor and methods take `std::string` and
  `std::vector<std::string>`.

That translator links `libLLVM.dylib`, built against libc++. Two ways to mix
the libraries both fail:
- **A libstdc++ runtime with the libc++ translator.** `std::string` crosses
  between two incompatible ABIs: at best a link error (the `[abi:cxx11]`
  symbols above), at worst memory corruption.
- **Runtime and translator both on libstdc++.** This needs a libLLVM built
  against libstdc++, which means a second LLVM build. The clang plugin
  (`libacpp-clang`), which clang loads, has to stay on libc++.

The workable setup is therefore a full libstdc++ stack, which upstream does
not support (option A in "Resume here").

**Pinned build: not run.** On 2026-11-16 the owner put Apple GPU offloading
on hold (below) before the LLVM 21.1.8 build started.
`toolchain:acpp-metal` is written but has never run at its pins.

## Status: on hold (owner, 2026-11-16)

The owner's words: "let's hold off on apple compiler offloading for now.
make sure all research and work done is documented and we can come back to
it later." `certify:macos` reports GO4-GO7 as N/A "on hold". The probe code
and the build task are kept, and `go_hold=no` in the task turns the checks
back on. GO1-GO3 (OpenMP offload with p2996, clang 23 and GCC 16) are N/A on
macOS for good (section 1). The ids match `ubuntu.md`'s GO section.

## Resume here

1. **LLVM 21.1.8 with libLLVM.dylib, then AdaptiveCpp.**
   - Run `mise run toolchain:acpp-metal --llvm-only`, then
     `mise run toolchain:acpp-metal`. The default is `-j6`; ask for the
     shared Mac's heavy-work slot first.
   - Cost: LLVM (clang, lld, openmp, AArch64, Release) about 45-75 min.
     AdaptiveCpp about 10 min; the spike built it at `-j4` in about that time.
   - Then set `go_hold=no` in `.mise/tasks/certify/macos` and run
     `MISE_AUTO_INSTALL=0 mise run certify:macos --only GO`.
   - Expected, from the spike: GO4 PASS, GO5 PASS, GO6 FAIL known upstream,
     GO7 FAIL (not built).
   - The pins are LLVM `2078da43e25a` (llvmorg-21.1.8), AdaptiveCpp
     `fe81de555a80` and metal-cpp `f567ed836e4c`. Before building, check
     whether AdaptiveCpp now supports LLVM 22 or newer: a newer LLVM may
     allow the same build against a newer release.
2. **stdpar (GO6).** Three options:
   - **(A) A full libstdc++ stack.** A second LLVM 21.1.8, only its dylib,
     built by the new clang against GCC 16's libstdc++ (gcc-d33). Then the
     AdaptiveCpp runtime and translators against it, with the plugin and
     driver from the libc++ install, in `<acpp12>-<id>-libstdcxx`. Cost:
     about 35-50 min of LLVM plus debugging rounds, realistically 1.5-2 h,
     with no guarantee it works. Upstream does not support this mix, and the
     gcc-d33 rpath caveat (playbook G1) applies to the new libLLVM.
   - **(B) Keep the known-upstream FAIL and ask upstream.** File an
     AdaptiveCpp issue asking for libc++ stdpar support (`doc/stdpar.md:8`:
     "likely easy to add if there is demand"). No build cost.
   - **(C) Add libc++ support to stdpar ourselves,** as an upstream PR. Cost
     unknown: stdpar hooks libstdc++'s internal pstl backend
     (`include/AdaptiveCpp/hipSYCL/std/stdpar/detail/execution_fwd.hpp:14`
     includes `pstl/execution_defs.h`).
   - Recommended: (B), then (C) if stdpar is wanted on the Mac.
3. **chipStar (GO7), route 3** (the owner's choice).
   - Build LLVM main at a pinned commit with clang, lld and libclc for
     `spirv64-unknown-vulkan`. On macOS, pass `CMAKE_AR` and `CMAKE_RANLIB`
     from LLVM (chipStar `README.md:156-165`).
   - Then SPIRV-LLVM-Translator and SPIRV-Tools; Mesa KosmicKrisp with meson
     and a project-local Python venv (mako, packaging, pyyaml), never
     Homebrew; the Vulkan loader; and chipStar with
     `-DCHIP_USE_NATIVE_VULKAN_SPIRV=ON`.
   - Cost at `-j6`: LLVM 60-90 min, Mesa about 15 min, the rest about 30 min
     (section 3).
   - The probe still has to be written: a HIP kernel whose device name comes
     from `hipGetDeviceProperties` and whose results are checked.
   - Recheck first whether LLVM 24 has been released.
4. **Tart guest.** Untested. macOS guests have a paravirtualized GPU, but
   whether Metal compute works there for AdaptiveCpp is unknown. The GO
   checks are host checks.
5. **openwiki sources:** section 5.

## 5. Sources to index (openwiki)

| Source | Ref |
|---|---|
| AdaptiveCpp docs (`doc/install-metal.md`, `doc/stdpar.md`, `doc/installing.md`, `doc/env_variables.md`) | AdaptiveCpp/AdaptiveCpp `fe81de555a80` |
| chipStar (`README.md`, `docs/MacOS.md`, `.github/workflows/unit-tests-macos-vulkan.yml`, `tests/known_failures.yaml`) | CHIP-SPV/chipStar `d3ce6238f621` |
| clvk (`README.md`, `.github/workflows/presubmit.yml`) | kpet/clvk `9862fce7d1b9` |
| MoltenVK README (deprecation notice) | KhronosGroup/MoltenVK `main`, read 2026-11-16 |
| Mesa KosmicKrisp driver docs | <https://docs.mesa3d.org/drivers/kosmickrisp.html>, read 2026-11-16 |
| metal-cpp | apple/metal-cpp, the commit the build pins |
| clang OpenMP support | <https://clang.llvm.org/docs/OpenMPSupport.html> |
