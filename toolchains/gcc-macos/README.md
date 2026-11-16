# GCC 16.2.0 for macOS arm64 (D33)

The Mac has no upstream GCC port for Apple silicon. D33 builds GCC from source with the GCC Darwin
maintainer's patch (`iains/gcc-16-branch`), following Homebrew's `gcc.rb` without Homebrew. This folder records the
recipe of the D33 build of 2026-11-15, installed as
`~/.local/share/gcc-d33/16.2.0-9f99e2b94d93` (pkgversion `cpp-standard GCC 16.2.0 (D33
9f99e2b94d93)`), so the build no longer depends on the leftover build cache it was found in.

| File | What it is |
|---|---|
| `pins.toml` | Tarball and patch URLs with sha256, the Homebrew commit, library and host versions |
| `build.sh` | Fetch, check, patch, configure, make and install, in the D33 order |
| `macos/d33-inputs.json` | The D33 build's own inputs record, byte for byte. The build id is the first 12 hex digits of its sha256: `9f99e2b94d93` |
| `macos/d33-configure-args.txt` | The D33 configure arguments after `--prefix` and `--with-pkgversion`, byte for byte (sha256 `70cb94b9…`, as named in `d33-inputs.json`) |

## Evidence

Recorded from the D33 build cache on 2026-11-16:

- **Tarball.** `gcc-16.2.0.tar.xz` sha256 `e6738e29…85c3e`. The same sha256 appears in
  `Formula/g/gcc.rb` at homebrew-core `4a334d2f`.
- **Darwin patch.** `Patches/gcc/gcc-16.2.0.diff` at homebrew-core `4a334d2f`, sha256
  `578a78ae…5a71`. The file at that URL has the same sha256 (checked 2026-11-16).
  - **The patch was applied.** In the build's source tree, `patch -p1 -R --dry-run` with that
    diff exits 0, so every hunk is present. The forward dry run fails with "already applied".
- **Configure.** The installed compiler's `gcc-16 -v` "Configured with:" line is
  `--prefix`, `--with-pkgversion`, then exactly `macos/d33-configure-args.txt`.
  - Against `gcc.rb` it differs only in `--prefix`, `--with-pkgversion`, `--libdir` (Homebrew
    uses `lib/gcc/current`), `--with-bugurl`, and the SDK given as a fixed path.
- **Make.** The make arguments are `BOOT_LDFLAGS=-Wl,-headerpad_max_install_names
  LDFLAGS_FOR_TARGET=-Wl,-headerpad_max_install_names` (`d33-inputs.json`, the same as
  `gcc.rb`). The build ran the three-stage bootstrap (`stage_final` = `stage3` in `build.log`).
- **Install.** A plain `gmake install` straight into the prefix, with no `DESTDIR` and no strip
  (`install.log`).

## Not recorded

- **Parallel jobs.** The job count of the original `gmake` is not recorded. `build.sh`
  defaults to the CPU count.
- **Exact command lines.** No script survived. `build.sh` is reconstructed from the records
  above and has **not been run yet**. A run should reproduce the same configure line, which
  `gcc-16 -v` shows.

## Limits

- **Homebrew libraries.** `cc1plus` links Homebrew's gmp, mpfr, libmpc, isl and zstd
  dynamically, so a `brew upgrade` that changes a library version breaks the compiler until it
  is rebuilt (macOS playbook, G1).
  - **`build.sh` checks the host first.** It exits 3 if any of these differs from the D33
    record: a Homebrew keg version, the Xcode build, the SDK version and path, Apple clang
    (`/usr/bin/clang`, `clang++`), `ld`, `gmake` 4.4.1, or the Darwin major. It names those
    executables by path and sets `CC` and `CXX`. It sets `PATH` to the Xcode toolchain (whose
    `ld` the D33 configure used, per its `config.log`) plus the system folders, clears the
    `*_FOR_TARGET` and linker overrides, and checks the `ld` that `PATH` then selects. It also exits 3
    if the target folder exists, or if the work folder already holds sources or a build: it
    always extracts and patches afresh. A host that differs needs a new inputs record and so a new id; it must not
    overwrite the D33 build.
  - Checked 2026-11-16 on the build host: every version matches, and the script stops at the
    existing folder.
- **rpath.** Programs it links record the hashed prefix as their rpath, not `current`
  (macOS playbook, G1).
- **No TSan or LSan,** and ASan hangs with `detect_leaks=1` (design, Risks; D33).
- **Not upstream.** The Darwin patch is not upstream. A new macOS SDK can break it; the fallback
  is reverting the bump.
- **Not yet a mise task.** Making this a task, running it inside the Tart VM, and building
  the libraries from pinned sources instead of Homebrew kegs belong to the unified-playbook
  work.
