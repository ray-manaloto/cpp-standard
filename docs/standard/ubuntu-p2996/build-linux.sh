#!/usr/bin/env bash
# clang-p2996 on Ubuntu 26.10 (amd64 or arm64, the machine it runs on): the
# D136 configuration adapted for Linux, with every LLVM project and runtime that
# builds there.
# build-linux.sh <work dir> <install prefix> <jobs>
# FLANG_JOBS (default jobs/4, at least 1) caps flang's own compiles, which
# take several GB of memory each (flang/docs/GettingStarted.md).
# Compiles go through sccache; its cache is $SCCACHE_DIR (default /sccache, the
# kept volume cpp-standard-sccache), so a rebuild after an input change that
# leaves the sources alone is mostly cache hits.
set -euo pipefail
export SCCACHE_DIR="${SCCACHE_DIR:-/sccache}" SCCACHE_CACHE_SIZE="${SCCACHE_CACHE_SIZE:-40G}"
command -v sccache >/dev/null || {
  echo "build-linux.sh: sccache not on PATH" >&2
  exit 1
}
sccache --start-server >/dev/null 2>&1 || true
sccache --zero-stats >/dev/null
work="$1" prefix="$2" jobs="$3"
flang_jobs="${FLANG_JOBS:-$((jobs / 4 > 0 ? jobs / 4 : 1))}"
# One native LLVM target, taken from the machine (a hard-coded target broke an
# earlier arm64 build, docs/designs/level-1/research/p2996-linux.md), plus
# NVPTX for OpenMP GPU offload: offload builds its NVPTX device runtime only
# when NVPTX is a target (offload/DeviceRTL/CMakeLists.txt:182-188). The
# runtimes (offload, openmp, flang-rt) build against libstdc++: their sources
# set no C++ library and nothing orders them after libc++'s headers, so with
# the libc++ default they race them (D136, amended 2026-11-16).
case "$(uname -m)" in
  x86_64) target=X86 ;;
  aarch64) target=AArch64 ;;
  *)
    echo "build-linux.sh: unsupported machine $(uname -m)" >&2
    exit 1
    ;;
esac
commit=562409c7942690d59ea470762515f88f24b16e23
# include-what-you-use, built in the LLVM tree as an external project (the
# dotfiles p2996 recipe does the same, dotfiles #707): the clang_21 branch head,
# IWYU 0.25, which matches p2996's clang 21.
iwyu_commit=791e69ea4662cb3e74e8128fd5fd69bd7f4ea6b3
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$work" "$prefix"
if [[ ! -d "$work/src/.git" ]]; then
  git init -q "$work/src"
  git -C "$work/src" fetch -q --depth 1 https://github.com/bloomberg/clang-p2996 "$commit"
  git -C "$work/src" checkout -q FETCH_HEAD
  git -C "$work/src" apply "$here/compiler-rt-remove-linux-scc-h.patch"
  # From the dotfiles p2996 recipe (python/toolchains/p2996/src/p2996/patches/, dotfiles 9550cea),
  # applied the way its source.py does.
  git -C "$work/src" apply --unidiff-zero "$here/lldb-base-specifier-derived.patch"
fi
if [[ ! -d "$work/iwyu/.git" ]]; then
  git init -q "$work/iwyu"
  git -C "$work/iwyu" fetch -q --depth 1 https://github.com/include-what-you-use/include-what-you-use "$iwyu_commit"
  git -C "$work/iwyu" checkout -q FETCH_HEAD
fi
# IWYU unpatched: exactly the pinned commit, nothing changed or added.
[[ "$(git -C "$work/iwyu" rev-parse HEAD)" == "$iwyu_commit" && -z "$(git -C "$work/iwyu" status --porcelain)" ]] || {
  echo "build-linux.sh: $work/iwyu is not a clean checkout of $iwyu_commit" >&2
  exit 1
}
# Every run, a fresh or a reused tree: the pinned commit with exactly these two
# patches, or stop. LLVM_FORCE_VC_REVISION below stamps the commit into
# --version, so the tree must really be that commit.
[[ "$(git -C "$work/src" rev-parse HEAD)" == "$commit" ]] || {
  echo "build-linux.sh: $work/src is not at $commit" >&2
  exit 1
}
# The working tree must equal the commit plus exactly the two patches: build the
# expected tree in a scratch index, the actual one in another, and compare.
idx="$(mktemp -d)"
tree_of() { # tree_of INDEX-FILE: write the index as a tree object, print its id
  GIT_INDEX_FILE="$1" git -C "$work/src" write-tree
}
GIT_INDEX_FILE="$idx/want" git -C "$work/src" read-tree "$commit"
GIT_INDEX_FILE="$idx/want" git -C "$work/src" apply --cached "$here/compiler-rt-remove-linux-scc-h.patch"
GIT_INDEX_FILE="$idx/want" git -C "$work/src" apply --cached --unidiff-zero "$here/lldb-base-specifier-derived.patch"
GIT_INDEX_FILE="$idx/have" git -C "$work/src" read-tree "$commit"
GIT_INDEX_FILE="$idx/have" git -C "$work/src" add -A
want="$(tree_of "$idx/want")" have="$(tree_of "$idx/have")"
rm -rf "$idx"
[[ "$want" == "$have" ]] || {
  echo "build-linux.sh: $work/src differs from $commit plus the two patches" >&2
  exit 1
}
cmake -G Ninja -S "$work/src/llvm" -B "$work/build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" \
  -DCMAKE_C_COMPILER=clang-23 -DCMAKE_CXX_COMPILER=clang++-23 -DLLVM_USE_LINKER=lld \
  -DCMAKE_C_COMPILER_LAUNCHER=sccache -DCMAKE_CXX_COMPILER_LAUNCHER=sccache \
  -DLLVM_ENABLE_PROJECTS="clang;clang-tools-extra;lld;lldb;mlir;polly;bolt;flang" \
  -DLLVM_EXTERNAL_PROJECTS=iwyu -DLLVM_EXTERNAL_IWYU_SOURCE_DIR="$work/iwyu" \
  -DIWYU_RESOURCE_RELATIVE_TO=iwyu \
  -DLLVM_ENABLE_RUNTIMES="libc;libunwind;libcxxabi;libcxx;compiler-rt;openmp;offload;flang-rt" \
  -DFLANG_PARALLEL_COMPILE_JOBS="$flang_jobs" \
  -DRUNTIMES_CMAKE_ARGS="-DCMAKE_CXX_FLAGS=-stdlib=libstdc++" \
  -DLLVM_TARGETS_TO_BUILD="$target;NVPTX" \
  -DLLVM_ENABLE_ASSERTIONS=ON -DLIBCXX_HARDENING_MODE=extensive -DLLVM_INSTALL_UTILS=ON \
  -DLLDB_ENABLE_PYTHON=ON -DPython3_EXECUTABLE=/usr/bin/python3 \
  -DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON -DCLANG_DEFAULT_CXX_STDLIB=libc++ \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF -DCLANG_INCLUDE_TESTS=OFF \
  -DLLVM_PARALLEL_LINK_JOBS=4 \
  -DLLVM_FORCE_VC_REPOSITORY=https://github.com/bloomberg/clang-p2996 -DLLVM_FORCE_VC_REVISION="$commit"
ninja -C "$work/build" -j"$jobs" install
sccache --show-stats
# The Linux counterpart of the macOS config files (macOS C2, P2): clang adds no
# rpath for its own runtimes, so without these a program finds the system
# libc++ (or no libunwind) at run time. Link-only (`$`), relative to the
# config file (<CFGDIR>), so the install can move.
triple="$("$prefix/bin/clang" -print-target-triple)"
for drv in clang clang++ flang; do
  printf '%s\n' "\$-Wl,-rpath,<CFGDIR>/../lib/$triple" >"$prefix/bin/$triple-$drv.cfg"
done
