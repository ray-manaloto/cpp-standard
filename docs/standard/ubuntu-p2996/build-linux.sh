#!/usr/bin/env bash
# clang-p2996 on Ubuntu 26.10 amd64: the D136 configuration adapted for Linux.
# build-linux.sh <work dir> <install prefix> <jobs>
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
commit=562409c7942690d59ea470762515f88f24b16e23
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
  -DLLVM_ENABLE_PROJECTS="clang;clang-tools-extra;lld;lldb;mlir;polly" \
  -DLLVM_ENABLE_RUNTIMES="libunwind;libcxxabi;libcxx;compiler-rt" \
  -DLLVM_TARGETS_TO_BUILD=X86 \
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
for drv in clang clang++; do
  printf '%s\n' '$-Wl,-rpath,<CFGDIR>/../lib/x86_64-unknown-linux-gnu' \
    >"$prefix/bin/x86_64-unknown-linux-gnu-$drv.cfg"
done
