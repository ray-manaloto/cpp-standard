#!/usr/bin/env bash
# M0 (b) and (j): build the module test with --coverage, run it, and require
# 100% line coverage through gcovr with no exclusions; then build the
# must-fail fixture and require gcovr to fail.
#   [REFLECTION_FLAG=<flag>] run.sh <c++ compiler> <gcov executable>
# e.g. run.sh g++-16 gcov-16, or run.sh /opt/p2996/bin/clang++ "/opt/p2996/bin/llvm-cov gcov"
set -euo pipefail
cxx="$1"
gcov="$2"
here="$(cd "$(dirname "$0")" && pwd)"
out="${OUT:-$PWD/out}"

build() { # <dir> <must_fail>
  cmake -S "$here" -B "$1" -G Ninja -DCMAKE_CXX_COMPILER="$cxx" -DMUST_FAIL="$2" -DREFLECTION_FLAG="${REFLECTION_FLAG:-}" >"$1.cmake.log" 2>&1 ||
    {
      tail -40 "$1.cmake.log"
      return 1
    }
  cmake --build "$1"
  ctest --test-dir "$1" --output-on-failure
}

report() { # <dir> <report name>
  gcovr --root "$here" --object-directory "$1" --gcov-executable "$gcov" \
    --filter "$here/src/" --txt "$out/$2.txt" --print-summary --fail-under-line 100
}

# The row of <file> in a gcovr text report, with a non-zero line count.
has_row() { grep -E "^$1 +[1-9][0-9]* " "$2"; }

mkdir -p "$out"
"$cxx" --version | head -1
gcovr --version | head -1

# D88: no exclusion markers anywhere in the spike.
rc=0
grep -rnE 'GCOVR_EXCL|LCOV_EXCL|GCOV_EXCL' "$here/src" "$here/tests" || rc=$?
if [[ $rc -ne 1 ]]; then
  echo "FAIL: exclusion marker found, or grep failed (exit $rc)"
  exit 1
fi

build "$out/pass" OFF
report "$out/pass" pass
# An empty report also meets --fail-under-line 100, so the module must be in it.
has_row src/encoder.cppm "$out/pass.txt" || {
  echo "FAIL: src/encoder.cppm is not in the report"
  exit 1
}
echo "PASS: 100% line coverage of the module"

build "$out/must-fail" ON
status=0
report "$out/must-fail" must-fail || status=$?
# Exit 2 is gcovr's --fail-under-line failure; any other code is a tool error.
if [[ $status -ne 2 ]]; then
  echo "FAIL: gcovr exited $status, not 2 (the line threshold)"
  exit 1
fi
has_row src/uncovered.cppm "$out/must-fail.txt" || {
  echo "FAIL: src/uncovered.cppm is not in the report"
  exit 1
}
echo "PASS: the uncovered-line fixture fails the gate"
