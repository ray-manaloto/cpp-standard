# Hands-on 2: system layout, libc++, `import std`, `mise oci build` (2026-11-13)

Setup as in `bootstrap-handson.md`: ubuntu:26.04 (linux/arm64 native), mise 2026.11.7 (sha256-pinned), same `mise.toml`/`mise.lock` (clang-23 1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94, cmake 4.5.0, ninja 1.13.2, conda gxx 16.2.0). Scripts: `<research-cache>/experiments/h2/out/t{1,2,3,4}.sh`. One throwaway container, removed afterwards. Host untouched.

## Results

| # | Test | Result |
|---|---|---|
| 1 | `mise bootstrap --skip tools --yes` as root, then `MISE_DATA_DIR=/tmp/fresh mise install --system --locked && mise reshim --system`, then user `dev` with PATH=/usr/local/share/mise/shims | OK. apt source + clang-23 installed by bootstrap, tools only in system dir, no root-install double step. dev ran cmake 4.5.0, ninja 1.13.2, conda g++ 16.2.0, clang++-23 23.1.6. |
| 2 | apt `libc++-23-dev=$V libc++abi-23-dev=$V` (V = served candidate, identical to clang-23 version) ; `clang++-23 -std=c++23 -stdlib=libc++` `<print>`+`<expected>` | OK, prints `hi 42 202302`. ldd: libc++.so.1, libc++abi.so.1 (/usr/lib/aarch64-linux-gnu), libm, libgcc_s, libc. No libstdc++. |
| 3a | CMake 4.5.0 + Ninja, clang++-23, `-DCMAKE_CXX_FLAGS=-stdlib=libc++`, named module + `import std;` | OK. `CMAKE_CXX_STDLIB_MODULES_JSON` NOT needed (CMake found it). Passing `-DCMAKE_EXPERIMENTAL_CXX_IMPORT_STD=ON` is unused (warning "Manually-specified variables were not used"): in 4.5 `import std` needs no experimental flag. Output `hello module 202302`. std module built from /usr/lib/llvm-23/share/libc++/v1/std.cppm. |
| 3b | same project, `CXX=/usr/local/share/mise/shims/g++` (conda 16.2.0) | OK, no flags. Built from the conda `.../include/c++/bits/std.cc` using conda's own `libstdc++.modules.json`. `hello module 202302`. |
| 4 | `MISE_EXPERIMENTAL=1 mise oci build` in the arm64 container | Runs (Linux host OK). Fails: apt source from `[bootstrap.apt.sources]` is NOT applied. |

Both 3a and 3b worked first try; there were no module errors to record. `find` showed modules json at `/usr/lib/aarch64-linux-gnu/libc++.modules.json` (and `/usr/lib/llvm-23/lib/`), `/usr/lib/gcc/aarch64-linux-gnu/15/libstdc++.modules.json`, and the conda one.

## Commands (essentials)

```sh
mkdir -p /etc/mise && cp mise.toml mise.lock /etc/mise/ && cd /etc/mise
export MISE_TRUSTED_CONFIG_PATHS=/etc/mise
mise bootstrap --skip tools --yes
MISE_DATA_DIR=/tmp/fresh mise install --system --locked && mise reshim --system
su dev -c 'PATH=/usr/local/share/mise/shims:$PATH cmake --version; ninja --version; g++ --version; clang++-23 --version'
apt-get install -y libc++-23-dev=$V libc++abi-23-dev=$V
clang++-23 -std=c++23 -stdlib=libc++ a.cpp -o a
# CMakeLists: cmake_minimum_required(4.2) project(m CXX) CMAKE_CXX_STANDARD 23 CMAKE_CXX_SCAN_FOR_MODULES ON
#   add_executable(m main.cpp); target_sources(m PRIVATE FILE_SET CXX_MODULES FILES hello.cppm)
CXX=clang++-23 cmake -S . -B ba -G Ninja -DCMAKE_CXX_FLAGS=-stdlib=libc++ && cmake --build ba
CXX=$(which g++) cmake -S . -B bb -G Ninja && cmake --build bb
```

## Verbatim problems and notes

- Test 1, non-root user: `mise WARN  failed to read lockfile /etc/mise/mise.lock (possible corruption): ... Permission denied (os error 13)`. Cause: my `cp` from the bind mount left `mise.lock` mode `-rw-------` root. Tools still resolved through shims. Fix: `chmod 644 /etc/mise/mise.lock`. (Not re-run after the chmod.)
- "Double step": `bootstrap --skip tools` followed by `install --system` with a fresh MISE_DATA_DIR avoided the prior error (root user-level install counted as "already installed"). Note I set MISE_DATA_DIR only for the system install; I did not test whether a plain `--system` without the override works after `--skip tools` (the prior failure came from a user-level install, which `--skip tools` now avoids; untested without the override).
- Test 4 verbatim (config: `[bootstrap.apt.sources.llvm]` as in the main file, `[bootstrap.packages] "apt:clang-23" = "<pinned>"`, `[tools] ninja="1.13.2"`, `[oci] from="ubuntu:26.04"`):
  - First run without env: `mise ERROR mise oci build is experimental. Enable it with 'mise settings experimental=true'`
  - With MISE_EXPERIMENTAL=1: `mise pulling base image: ubuntu:26.04`, then it runs apt in a chroot-like rootfs (`apt-get -c .../mise-oci.conf -o Dir=/tmp/mise-oci-apt-rootfs-XXXX/rootfs ... update`, then `... install -y --no-install-recommends -- clang-23=1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94`), then
    `mise ERROR mise oci build apt-get failed while installing OCI system packages: exit status: 100` / `E: Unable to locate package clang-23`.
  - Interpretation: the `update` ran against the stock Ubuntu sources only; the llvm source defined in `[bootstrap.apt.sources]` was not written into the OCI rootfs apt config (I did not read the rootfs to confirm directly; the rootfs is temp and deleted). `oci build` runs on the arm64 host arch and says "Build on a Linux host with the image's architecture".

## Untested

- amd64 (no time); native x64 or emulated.
- `mise oci build` with no `[oci]`/other variants, `--include-global`, or an apt-source workaround (e.g. a custom base image that already has the llvm source; `--copy` of a sources file into the image before apt runs).
- Plain `install --system` after `--skip tools` without a fresh MISE_DATA_DIR; `--only packages`.
- Running the built executables on a non-root user from the shims (3a/3b ran as root; test 1 verified tools as dev, not the module build).
- Mixing libc++ (clang) and conda libstdc++ in one link.
