#!/usr/bin/env bash
# Shared body of the uncovered-line fixtures (ticket #132, D88, D131): a first-party source with one
# line no test reaches, built and run with <compiler>'s own coverage flags, then measured by the real
# coverage check (`mise run ci:coverage`, the command the gate runs per preset). Exits 0 only when
# that check fails with its name, "ci:coverage", and its report lists exactly that source's line as
# missed. A compile failure, a test that fails or a passing check is not a pass; a missing compiler
# exits 3 ("could not run", see `mise run ci-must-fail`).
# Usage: uncovered-line.sh gcc16|clang23|p2996
set -euo pipefail
# shellcheck disable=SC2046
unset $(git rev-parse --local-env-vars) # a git hook's GIT_DIR must not reach the tools below
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
case "${1:?compiler}" in
  gcc16)
    cxx=g++-16
    flags=()
    gcov='gcov-16'
    ;;
  clang23)
    cxx=clang++-23
    flags=(-stdlib=libc++)
    gcov="llvm-cov-23 gcov"
    ;;
  p2996)
    prefix="${CPPSTD_P2996_PREFIX:-}"
    [[ -x "$prefix/bin/clang++" ]] || {
      echo "could not run: CPPSTD_P2996_PREFIX names no p2996 toolchain (mise run toolchain:fetch)" >&2
      exit 3
    }
    cxx="$prefix/bin/clang++"
    flags=(-stdlib=libc++ "-Wl,-rpath,$prefix/lib/aarch64-unknown-linux-gnu")
    gcov="$prefix/bin/llvm-cov gcov"
    ;;
  *)
    echo "unknown compiler $1" >&2
    exit 2
    ;;
esac
command -v "$cxx" >/dev/null || {
  echo "could not run: $cxx is not installed" >&2
  exit 3
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/src" "$work/build"
cat >"$work/src/pick.cpp" <<'CPP'
int pick(bool first) {
  if (first) {
    return 1;
  }
  return 2;  // no test reaches this line
}
CPP
cat >"$work/main.cpp" <<'CPP'
int pick(bool first);
int main() { return pick(true) == 1 ? 0 : 1; }
CPP
(
  cd "$work/build"
  "$cxx" "${flags[@]}" --coverage -O0 -c ../src/pick.cpp -o pick.o
  "$cxx" "${flags[@]}" -c ../main.cpp -o main.o
  "$cxx" "${flags[@]}" --coverage pick.o main.o -o test
  ./test
)

rc=0
out="$(cd "$root" && mise run -q ci:coverage --build-dir "$work/build" --source-root "$work" --gcov "$gcov" 2>&1)" || rc=$?
echo "$out"
if [[ $rc -eq 0 ]]; then
  echo "went green: ci:coverage accepted a source with an uncovered line" >&2
  exit 1
fi
grep -q '^ci:coverage: FAIL .*below 100% line coverage' <<<"$out" || {
  echo "ci:coverage failed, but not for the coverage threshold" >&2
  exit 1
}
grep -Eq 'pick\.cpp +[0-9]+ +[0-9]+ +[0-9]+% +5$' <<<"$out" || {
  echo "the report does not show the one missed line (src/pick.cpp, line 5)" >&2
  exit 1
}
exit 0
