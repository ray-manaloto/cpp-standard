#!/usr/bin/env bash
# Shared body of the sanitizer fixtures (ticket #134, D37, D42): a source with one planted
# fault, built with the sanitizer flags of its check preset (cmake/presets/checks.json), then
# measured by the real check the gate runs (`mise run ci:sanitizers`, the command behind step 6).
# Exits 0 only when that check fails with its name, "ci:sanitizers", and the planted fault's own
# sanitizer reports it. A compile failure, a check that fails for another reason, or a check
# that accepts the fault is not a pass; a missing compiler exits 3 ("could not run", see
# `mise run ci-must-fail`).
# MUST_FAIL_PLANT=accept substitutes a clean source and runs the same sanitizer check.
# Usage: sanitizer-fault.sh <asan|ubsan|tsan> <gcc16|clang23|p2996>
set -euo pipefail
# shellcheck disable=SC2046
unset $(git rev-parse --local-env-vars) # a git hook's GIT_DIR must not reach the tools below
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
kind="${1:?fault kind: asan, ubsan or tsan}"
compiler="${2:?compiler: gcc16, clang23 or p2996}"
check="ci:sanitizers"
case "$kind" in
  asan) fault="a heap-buffer-overflow" ;;
  ubsan) fault="a signed integer overflow" ;;
  tsan) fault="a data race on two threads" ;;
  *)
    echo "unknown fault kind $kind" >&2
    exit 2
    ;;
esac
case "$compiler" in
  gcc16)
    cxx=g++-16
    ;;
  clang23)
    cxx=clang++-23
    ;;
  p2996)
    prefix="${CPPSTD_P2996_PREFIX:-}"
    [[ -n "$prefix" && -x "$prefix/bin/clang++" ]] || {
      echo "could not run: CPPSTD_P2996_PREFIX names no p2996 toolchain (mise run toolchain:fetch)" >&2
      exit 3
    }
    cxx="$prefix/bin/clang++"
    ;;
  *)
    echo "unknown compiler $compiler" >&2
    exit 2
    ;;
esac
command -v "$cxx" >/dev/null || {
  echo "could not run: $cxx is not installed" >&2
  exit 3
}
case "$kind" in
  asan)
    preset="$compiler-asan-ubsan"
    class=AddressSanitizer
    token="AddressSanitizer: heap-buffer-overflow"
    ;;
  ubsan)
    preset="$compiler-asan-ubsan"
    class=UndefinedBehaviorSanitizer
    token="runtime error: signed integer overflow"
    ;;
  tsan)
    preset="$compiler-tsan"
    class=ThreadSanitizer
    token="ThreadSanitizer: data race"
    ;;
esac

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cat >"$work/CMakeLists.txt" <<EOF
cmake_minimum_required(VERSION 4.5)
project(cppstd_fault LANGUAGES CXX)
enable_testing()
add_executable(fault fault.cpp)
add_test(NAME fault COMMAND fault)
EOF
cat >"$work/fault.cpp" <<'CPP'
#include <cstdlib>
int main() {
  char* p = static_cast<char*>(std::malloc(4));
  p[7] = 1;  // the planted heap-buffer-overflow
  return p[7];
}
CPP
[[ "$kind" != "ubsan" ]] || cat >"$work/fault.cpp" <<'CPP'
#include <cstdio>
int main() {
  int big = 2147483647;
  big = big + 1;  // the planted signed integer overflow
  std::printf("%d\n", big);
  return 0;
}
CPP
[[ "$kind" != "tsan" ]] || cat >"$work/fault.cpp" <<'CPP'
#include <thread>
int data = 0;
int main() {
  std::thread a([] { for (int i = 0; i < 100000; ++i) ++data; });
  for (int i = 0; i < 100000; ++i) ++data;
  a.join();
  return data == 0 ? 1 : 0;
}
CPP
if [[ "${MUST_FAIL_PLANT:-}" == accept ]]; then
  printf 'int main() { return 0; }\n' >"$work/fault.cpp"
fi
# Exercise the actual inherited check flags. This fixture needs only the compiler
# toolchain file; it has no vcpkg ports or project build dependencies.
cp "$root/CMakePresets.json" "$work/"
ln -s "$root/cmake" "$work/cmake"
(cd "$work" && cmake --preset "$preset" -B "$work/build" \
  -DCMAKE_TOOLCHAIN_FILE="$root/cmake/toolchains/$compiler.cmake") || exit 2
cmake --build "$work/build" || exit 2

rc=0
out="$(cd "$root" && mise run -q ci:sanitizers --build-dir "$work/build" 2>&1)" || rc=$?
echo "$out"
if [[ $rc -eq 0 ]]; then
  echo "went green: $check accepted the fixture source" >&2
  exit 1
fi
if [[ "${MUST_FAIL_PLANT:-}" == accept ]]; then
  echo "$check rejected the clean control fixture" >&2
  exit 2
fi
grep -F "ci:sanitizers: FAIL $work/build:" <<<"$out" | grep -F "$class" >/dev/null || {
  echo "$check failed, but not with its own name" >&2
  exit 2
}
grep -Fq "$token" <<<"$out" || {
  echo "the failure does not name the fault ($token)" >&2
  exit 2
}
printf 'int main() { return 0; }\n' >"$work/fault.cpp"
cmake --build "$work/build" || exit 2
(cd "$root" && mise run -q ci:sanitizers --build-dir "$work/build") || {
  echo "$check refused the clean control" >&2
  exit 2
}
echo "REFUSED as required: $check refused $fault with its own name"
exit 0
