#!/usr/bin/env bash
# clang-p2996 with compiler-rt, libc++, libc++abi and libunwind (environment-standard.md section 2,
# the toolchains/p2996/build.sh row; D30, D32, D88, D105). Started from the M0 (h) spike's build.sh
# and smoke.sh, which built and smoke-tested this commit on ubuntu-26.04-arm in run 43509894509
# (https://github.com/ray-manaloto/cpp-standard/actions/runs/43509894509).
#
#   build.sh <work dir> <install prefix> [configure]
#   build.sh patch <source dir> [patch dir]     (apply the patches only; tests/toolchain/)
#
# `mise run artifact:build p2996-linux-<arch>` runs it inside this commit's tools image, from a copy
# of the hashed files only, and packs the prefix. Every CMake argument lives here; the pins
# (source, commit) come from pins.toml next to it. The bootstrap compiler is apt.llvm.org's clang-23
# and lld-23 (apt.toml, so pins.toml sets apt_compiler = true). With `configure` it stops after the
# CMake configure step (a quick probe of the recipe). Linux only until M3.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

# Upstream fixes the pinned commit lacks; each patch's header names its upstream commit (D105).
# git apply runs with the source tree's parent as a ceiling, so no enclosing repository is found:
# inside one (the build's scratch can sit in a checkout), git apply exits 0 and changes nothing.
# Each patch must change every file it names, or the build fails.
apply_patches() { # <source dir> <patch dir>
  local src parent p f before after files
  src="$(cd "$1" && pwd)"
  parent="$(dirname "$src")"
  for p in "$2"/*.patch; do
    p="$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
    files=()
    while IFS= read -r f; do files+=("$f"); done < <(cd "$src" && GIT_CEILING_DIRECTORIES="$parent" git apply --numstat "$p" | cut -f3)
    [[ ${#files[@]} -gt 0 ]] || {
      echo "FAIL: $(basename "$p") names no file" >&2
      return 1
    }
    before="$(cd "$src" && git hash-object --no-filters "${files[@]}")"
    (cd "$src" && GIT_CEILING_DIRECTORIES="$parent" git apply "$p")
    after="$(cd "$src" && git hash-object --no-filters "${files[@]}")"
    [[ "$before" != "$after" ]] || {
      echo "FAIL: $(basename "$p") applied but changed none of ${files[*]}" >&2
      return 1
    }
    echo "applied $(basename "$p"): ${files[*]}"
  done
}
if [[ "${1:-}" == patch ]]; then
  apply_patches "${2:?source dir}" "${3:-$here/linux}"
  exit 0
fi

work="${1:?work dir}" prefix="${2:?install prefix}" stop="${3:-}"
[[ "$(uname -s)" == Linux ]] || {
  echo "FAIL: the macOS p2996 recipe arrives with M3" >&2
  exit 1
}
case "$(uname -m)" in
  aarch64) target=AArch64 ;;
  x86_64) target=X86 ;;
  *)
    echo "FAIL: unsupported arch $(uname -m)" >&2
    exit 1
    ;;
esac
pin() { python3 -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["source"][sys.argv[2]])' "$here/pins.toml" "$1"; }
url="$(pin url)" sha256="$(pin sha256)" commit="$(pin commit)"
llvm23=/usr/lib/llvm-23/bin
mkdir -p "$work" "$prefix"
log="$work/build.log"
phase() { echo "$(date -u +%H:%M:%S) $1" | tee -a "$log"; }

phase fetch
curl -fsSL --retry 3 -o "$work/src.tar.gz" "$url"
echo "$sha256  $work/src.tar.gz" | sha256sum -c -
rm -rf "$work/src"
mkdir "$work/src"
tar -xzf "$work/src.tar.gz" -C "$work/src" --strip-components 1
rm "$work/src.tar.gz"
apply_patches "$work/src" "$here/linux"

phase configure
cmake -G Ninja -S "$work/src/llvm" -B "$work/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$prefix" \
  -DCMAKE_C_COMPILER="$llvm23/clang" -DCMAKE_CXX_COMPILER="$llvm23/clang++" \
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
  -DLLVM_FORCE_VC_REVISION="$commit" \
  >"$work/cmake.log" 2>&1 || {
  tail -50 "$work/cmake.log"
  exit 1
}
grep -E '^-- (The (C|CXX) compiler identification|Linker detection)' "$work/cmake.log" || true
if [[ "$stop" == configure ]]; then
  phase "configured (stopping: configure only)"
  exit 0
fi

phase build
ninja -C "$work/build" install >"$work/ninja.log" 2>&1 || {
  tail -50 "$work/ninja.log"
  exit 1
}
phase installed

# --- smoke test (from the M0 (h) spike's smoke.sh, M0 (c); spikes/m0/README.md): reflection, ASan, UBSan and gcov-mode coverage
# with the built compiler and its own libc++ (D88). The llvm-cov and llvm-profdata tools are part of
# the install.
cxx="$prefix/bin/clang++"
triple="$("$cxx" -print-target-triple)"
rpath="-Wl,-rpath,$prefix/lib/$triple"
dir="$work/smoke"
rm -rf "$dir"
mkdir -p "$dir"
cat >"$dir/refl.cpp" <<'CPP'
#include <meta>
#include <print>
struct point { int x; int y; };
int main() {
  constexpr auto n = std::meta::nonstatic_data_members_of(^^point, std::meta::access_context::unchecked()).size();
  static_assert(n == 2);
  std::println("members: {}", n);
}
CPP
cat >"$dir/bug.cpp" <<'CPP'
int main(int argc, char**) { int* p = new int[1]; int v = p[argc]; delete[] p; return v; }
CPP
cat >"$dir/ub.cpp" <<'CPP'
#include <climits>
int main(int argc, char**) { int x = INT_MAX; x += argc; return x == 0; }
CPP
cat >"$dir/cov.cpp" <<'CPP'
int f(int a) { if (a > 0) return 1; return 2; }
int main() { return f(1) - 1; }
CPP
failed=0
check() { # <label> <command>
  if bash -c "$2"; then
    echo "smoke PASS: $1"
  else
    echo "smoke FAIL: $1" >&2
    failed=1
  fi
}
check "reflection with -freflection-latest and libc++" \
  "'$cxx' -std=c++26 -freflection-latest $rpath '$dir/refl.cpp' -o '$dir/refl' && '$dir/refl' | grep -qx 'members: 2'"
check "ASan reports a heap-buffer-overflow" \
  "'$cxx' -std=c++26 -g -fsanitize=address $rpath '$dir/bug.cpp' -o '$dir/bug' && ! '$dir/bug' 2>'$dir/asan.txt' && grep -q heap-buffer-overflow '$dir/asan.txt'"
check "UBSan reports a signed overflow" \
  "'$cxx' -std=c++26 -fsanitize=undefined -fno-sanitize-recover=all $rpath '$dir/ub.cpp' -o '$dir/ub' && ! '$dir/ub' 2>'$dir/ubsan.txt' && grep -q 'signed integer overflow' '$dir/ubsan.txt'"
# Compile and link in separate steps, so the notes and data files are cov.gcno and cov.gcda.
check "--coverage writes gcda and llvm-cov gcov reads it" \
  "cd '$dir' && '$cxx' -std=c++26 --coverage -c cov.cpp -o cov.o && '$cxx' --coverage $rpath cov.o -o cov && ./cov && test -s cov.gcda && '$prefix/bin/llvm-cov' gcov cov.cpp | grep -q 'Lines executed'"
[[ $failed -eq 0 ]] || exit 1
"$cxx" --version | head -1
phase finished
