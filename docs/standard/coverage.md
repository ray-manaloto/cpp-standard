# Coverage

Every first-party line under `src/` is covered by a test, on every compiler of the gate. The rule is D88;
the one-tool-per-build-tree layout is D131; the design is
[`environment-standard.md`](../designs/environment-standard.md) §5.

## The rule

- **100% line coverage of first-party code.** First-party code is everything under `src/`. Tests,
  fixtures, the vcpkg checkout and the compilers' own headers are not measured.
- **No exclusions.** No coverage-exclusion marker of any tool (`GCOVR_EXCL`, `LCOV_EXCL`, `// pragma: no cover`
  and the like) is allowed in `src/`. A line that cannot run is removed or tested.
- **Consteval code is not counted.** gcov-mode tools never see code that runs only at compile time. It is
  tested with `static_assert` in the module itself (`src/cppstd/core.cppm` does this for `parse_u32`).

## How it is measured

Each compiler measures its own build tree, in gcov mode, with its own tool. The three reports are separate;
nothing merges them.

| Preset | Compiler | gcov tool |
|---|---|---|
| `gcc16-coverage` | `g++-16` | `gcov-16` |
| `clang23-coverage` | `clang++-23` with libc++ | `llvm-cov-23 gcov` |
| `p2996-coverage` | `clang++` of the p2996 toolchain with its libc++ | `llvm-cov gcov` of that toolchain |

The preset builds in Debug with `--coverage -O0` and records the tool as `CPPSTD_GCOV` in the cache.
`mise run ci:coverage <preset>` runs gcovr once on the preset's build tree with that tool, filters to `src/`,
and fails below 100%. It also fails when a `src/` source has no row in the report (a source no test loaded).
A failure prints `ci:coverage: FAIL <label> is below 100% line coverage of src/`.

## Running it

- `mise run ci` builds, tests and measures every gate preset in the tools image (the `gate-linux-arm64` check).
- `mise run ci:fast [preset]` does the same for one preset (default `gcc16-coverage`).
- `mise run ci:coverage <preset>` measures an existing build tree. `--build-dir`, `--source-root` and `--gcov`
  replace the preset's defaults; the must-fail fixtures use them on a small tree.
- `mise run doctor` lists what the machine lacks for the above.

## The fixtures

`fixtures/must-fail/uncovered-line-{gcc16,clang23,p2996}` each build a source with one line no test reaches and
run `ci:coverage` on it with that compiler's tool. They pass only when the check fails with its own name and
the report shows that line as missed. `mise run ci-must-fail` runs them in the `must-fail` check.

## Dependencies

The test framework `bext-ut` comes from vcpkg in manifest mode, at the baseline pinned in
`vcpkg-configuration.json` (D113). `mise run vcpkg:bootstrap` makes the checkout in `.cache/vcpkg` at that
baseline; `--check` fails when it is at another commit (fixture `vcpkg-baseline`). There is no binary cache.
