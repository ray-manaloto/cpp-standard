#!/usr/bin/env bash
# M0 (h) and (c) spike (environment-standard.md section 10, D32, D67): a cold
# build of clang-p2996 with compiler-rt on a hosted runner, recording peak
# disk and wall time, then a smoke test of reflection, ASan, UBSan and
# coverage with the built compiler. Deleted after M0.
#
#   build.sh <work dir> <install prefix>
set -euo pipefail

work="$1" prefix="$2"
commit="562409c7942690d59ea470762515f88f24b16e23"   # bloomberg/clang-p2996, branch p2996, 2026-11-03
case "$(uname -m)" in
  aarch64) target=AArch64 ;;
  x86_64) target=X86 ;;
  *) echo "unsupported arch $(uname -m)" >&2; exit 1 ;;
esac
log="$work/m0h.log"
mkdir -p "$work" "$prefix"
fs_used() { df --output=used -B1M "$work" | tail -1 | tr -d ' '; }

# Peak disk: sample the file system that holds the work dir every 15 s.
start_used="$(fs_used)"
echo 0 > "$work/peak"
( peak=0
  while :; do
    u="$(fs_used)"; (( u > peak )) && peak=$u && echo "$peak" > "$work/peak.tmp" && mv "$work/peak.tmp" "$work/peak"
    sleep 15
  done ) >/dev/null 2>&1 &
sampler=$!
trap 'kill "$sampler" 2>/dev/null || true' EXIT

phase() { echo "$(date +%s) $1" >> "$log"; echo "::notice::M0 (h) phase $1 at $(date -u +%H:%M:%S)"; }

phase start
git init -q "$work/src"
git -C "$work/src" fetch -q --depth 1 https://github.com/bloomberg/clang-p2996 "$commit"
git -C "$work/src" checkout -q FETCH_HEAD
phase fetched

cmake -G Ninja -S "$work/src/llvm" -B "$work/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$prefix" \
  -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
  -DLLVM_USE_LINKER=lld \
  -DLLVM_ENABLE_PROJECTS="clang;lld" \
  -DLLVM_ENABLE_RUNTIMES="libcxx;libcxxabi;libunwind;compiler-rt" \
  -DLLVM_TARGETS_TO_BUILD="$target" \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DCLANG_INCLUDE_TESTS=OFF \
  -DCOMPILER_RT_BUILD_SANITIZERS=ON -DCOMPILER_RT_BUILD_PROFILE=ON \
  -DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON \
  -DCOMPILER_RT_BUILD_LIBFUZZER=OFF -DCOMPILER_RT_BUILD_MEMPROF=OFF \
  -DCOMPILER_RT_BUILD_XRAY=OFF -DCOMPILER_RT_BUILD_ORC=OFF \
  -DCLANG_DEFAULT_CXX_STDLIB=libc++ \
  -DLLVM_FORCE_VC_REPOSITORY=https://github.com/bloomberg/clang-p2996 \
  > "$work/cmake.log" 2>&1 || { tail -50 "$work/cmake.log"; exit 1; }
phase configured
ninja -C "$work/build" install > "$work/ninja.log" 2>&1 || { tail -50 "$work/ninja.log"; exit 1; }
phase installed

kill "$sampler" 2>/dev/null || true
# One last sample: the end of the install, with the build tree and the
# prefix both present, can fall between two samples.
peak="$(cat "$work/peak")"; peak="${peak:-0}"
u="$(fs_used)"; (( u > peak )) && peak=$u
build_mb="$(du -sm "$work/build" | cut -f1)"
prefix_mb="$(du -sm "$prefix" | cut -f1)"
s() { awk -v p="$1" '$2 == p { print $1 }' "$log"; }
{
  echo "commit=$commit"
  echo "arch=$(uname -m) cpus=$(nproc) work=$work"
  echo "fetch_s=$(( $(s fetched) - $(s start) ))"
  echo "configure_s=$(( $(s configured) - $(s fetched) ))"
  echo "build_install_s=$(( $(s installed) - $(s configured) ))"
  echo "total_s=$(( $(s installed) - $(s start) ))"
  echo "fs_used_start_mb=$start_used fs_used_peak_mb=$peak"
  echo "build_tree_mb=$build_mb install_prefix_mb=$prefix_mb"
} | tee "$work/m0h-result.txt"
