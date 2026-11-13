#!/usr/bin/env bash
# M0 (c) smoke test: reflection, ASan, UBSan and coverage with the built
# clang-p2996 and its own libc++. Deleted after M0.
#
#   smoke.sh <install prefix> <scratch dir>
set -euo pipefail
prefix="$1" dir="$2"
cxx="$prefix/bin/clang++"
triple="$("$cxx" -print-target-triple)"
rt="-Wl,-rpath,$prefix/lib/$triple"
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
#include <cstdlib>
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
ok=0
check() {
  if "$@"; then
    echo "M0 (c) PASS: $label"
  else
    echo "::error::M0 (c) FAIL: $label"
    ok=1
  fi
}

label="reflection with -freflection-latest and libc++"
check bash -c "'$cxx' -std=c++26 -freflection-latest -stdlib=libc++ $rt '$dir/refl.cpp' -o '$dir/refl' && '$dir/refl' | grep -qx 'members: 2'"

label="ASan reports a heap-buffer-overflow"
check bash -c "'$cxx' -std=c++26 -stdlib=libc++ -g -fsanitize=address $rt '$dir/bug.cpp' -o '$dir/bug' && ! ASAN_OPTIONS=detect_leaks=1 '$dir/bug' 2> '$dir/asan.txt' && grep -q heap-buffer-overflow '$dir/asan.txt'"

label="UBSan reports a signed overflow"
check bash -c "'$cxx' -std=c++26 -stdlib=libc++ -fsanitize=undefined -fno-sanitize-recover=all $rt '$dir/ub.cpp' -o '$dir/ub' && ! '$dir/ub' 2> '$dir/ubsan.txt' && grep -q 'signed integer overflow' '$dir/ubsan.txt'"

# Compile and link in separate steps, so the notes and data files are
# cov.gcno and cov.gcda (a one-step -o build names them cov-cov.*).
label="--coverage writes gcda and llvm-cov gcov reads it"
check bash -c "cd '$dir' && '$cxx' -std=c++26 -stdlib=libc++ --coverage -c cov.cpp -o cov.o && '$cxx' -stdlib=libc++ --coverage $rt cov.o -o cov && ./cov && test -s cov.gcda && '$prefix/bin/llvm-cov' gcov cov.cpp | grep -q 'Lines executed'"

exit $ok
