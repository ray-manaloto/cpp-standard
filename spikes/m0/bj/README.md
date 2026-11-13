# M0 (b) and (j) spike

gcov-mode coverage (D88) of a C++ named module: `src/encoder.cppm`, a
stand-in for the encoder module, with run-time branches and a `consteval`
helper only `static_assert` uses. `run.sh <c++> <gcov>` builds it with
`--coverage` through CMake and Ninja, runs the test, and requires 100% line
coverage through gcovr with no exclusion markers. It then adds
`src/uncovered.cppm` (`-DMUST_FAIL=ON`) and requires gcovr to fail.

`.github/workflows/spike-m0-bj.yml` runs it on GCC 16 (`gcov-16`), on clang
23 from apt.llvm.org (`llvm-cov-23 gcov`, libc++), and, on dispatch with a
spike-m0-h run id, on that run's p2996 toolchain (`llvm-cov gcov`). The
pass step requires the module's row in the report (an empty report also
meets the threshold); the must-fail step requires gcovr's exit code 2 and
the fixture's row, so a tool error is not counted as the gate working. Results go to `spikes/m0/README.md`. Deleted after M0.
