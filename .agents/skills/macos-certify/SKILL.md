---
name: macos-certify
description: Run the macOS C++ environment certification (docs/standard/macos.md) on this Mac or inside a Tart VM, read the PASS/FAIL/N/A report, and refresh the committed baseline. Use it whenever someone asks to certify, check, verify or re-run the macOS playbook or checklist, asks "is this Mac ready for C++", "does the toolchain still work", "what is failing on the Mac", after any toolchain change (p2996 rebuild or switch of current, GCC or LLVM install, Xcode or macOS update, mise or Python change), and before calling a Mac or VM image done.
---

# macOS certification

`docs/standard/macos.md` is the playbook: one check per item (A1 to V3),
each with a probe and a PASS rule. `mise run certify:macos` runs every probe
and prints the playbook's report: one `<id> PASS|FAIL|N/A <evidence>` line
per check, a summary, and a fix for each FAIL. The task is
`.mise/tasks/certify/macos`. It reads the probe sources (refl.cpp, san.cpp,
dap.cpp, dap_probe.py, the CMake probe) from the playbook's appendix at run
time, so edit them there, not in the task.

It installs nothing and changes nothing outside a temporary scratch
directory (playbook rule 4). A full host run takes about a minute. It
refuses to start (exit 2) unless `MISE_AUTO_INSTALL=0` is set: without it,
`mise run` installs any missing tool of this repository's config before the
task starts, so a check could PASS on a tool the Mac did not have. It
then re-runs itself once with `MISE_ENV_CACHE=0`, because mise's
environment cache can hold a PATH from before a tool was installed.

## Run it

From the repository root:

```bash
MISE_AUTO_INSTALL=0 mise run certify:macos --allow-fail                 # the full report on stdout
MISE_AUTO_INSTALL=0 mise run certify:macos --only DB,P4 --allow-fail    # one section or a few checks
MISE_AUTO_INSTALL=0 mise run certify:macos --allow-fail --keep          # keep the scratch dir and its logs
```

Without `--allow-fail` the task exits 1 when any check fails, except the
"known upstream" FAILs (today only P10), which it lists on their own summary
line; use that form in automation that must stop on a regression. A check
becomes known upstream only when the playbook says so and names the upstream
change that clears it; add its id to `known_upstream` in the task. Each check also prints its line
on stderr as it finishes, so a long run shows progress.

`--only` takes ids or prefixes: `DB` selects DB1 to DB5, `C` selects C1 to
C9. A6 is decided after DB5, so it prints after the D section.

## Refresh the baseline

The committed baseline is `docs/standard/reports/macos-host-<date>.txt`.
After a toolchain change, write a new one and compare:

```bash
MISE_AUTO_INSTALL=0 mise run certify:macos --allow-fail --out docs/standard/reports/macos-host-$(date +%F).txt
git diff --no-index docs/standard/reports/macos-host-2026-11-15.txt docs/standard/reports/macos-host-$(date +%F).txt
```

A check that changes from PASS to FAIL is a regression: report it with the
evidence line. A FAIL that turns PASS needs the playbook's "Today" line and
the "Usable today" table updated in the same change. The report masks the
home directory as `~` and the account name as `<user>`, and labels the
machine `host` (or `vm`), so it can be committed to this public repository.

## In a Tart VM

The task reads `kern.hv_vmm_present`. In a guest it reports R2, V1 and V2 as
N/A. V3 is PASS only on a full run (no `--only`) with no FAIL above it other
than a known-upstream one, FAIL
otherwise, and N/A under `--only`. V1 and V2 pass on the host (2026-11-15);
the guest path has not run yet.

## Reading the report

- **N/A is not PASS.** G5, H1 and T1 are rules with no probe; K1 and E1 need
  a C++ project, and this repository has none yet; T6 tools are tier 2; T7
  XRay does not work on Darwin. None of them is proven by a report.
- Several FAILs share one cause. The fix list repeats it per id; group them
  when you report (all of C, DB2, L1's and R4's clang 23 halves are the
  missing LLVM 23 tarball).
- A check that covers all three compilers (L1, L2) FAILs when one is
  missing; it never passes on the compilers it found.
- A6 with Developer mode `disabled` is PASS only if DB5 reached its
  breakpoint in the same run (the run is unattended, so no password dialog
  was answered).
- DB5 counts only the debugserver whose parent is this run's lldb and whose
  real path is the build's own, so another session's debugserver cannot pass it.
- G4 adds what happens with the G6 PATH fix applied (`with /usr/bin first:
  asan=yes ubsan=yes`), so a G4 FAIL caused only by G6 is visible as such.

## Gotchas

- Never pipe a sanitized program into `grep -q` under `pipefail`: the
  program exits nonzero on purpose, so the pipeline fails even when grep
  matches. The task captures the output and matches with `[[ ]]`.
- The CMake probe's `m.cpp` is given on one comment line. GCC needs
  `import std;` on its own line, so the task splits it.
- p2996's `arm64-apple-darwin-clang++.cfg` holds no `-isysroot`; it pulls
  it in with `@arm64-apple-darwin.cfg`. P2 follows `@` lines.
- `--out` is resolved against the directory you ran from; the run itself
  works in the scratch dir.
- The task runs with this repository's mise environment, so its `PATH` can
  differ from an interactive shell. G6 depends on which `dsymutil` is first
  on `PATH`.
- macOS has no `timeout`; the task uses a perl `alarm` wrapper (exit 142 on
  timeout). It is bash 3.2 code, because `/bin/bash` is 3.2.
