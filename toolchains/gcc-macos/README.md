# GCC 16.2.0 for macOS arm64 (D33)

The Mac has no upstream GCC port for Apple silicon. D33 builds GCC from source with the GCC Darwin
maintainer's patch (`iains/gcc-16-branch`), following Homebrew's `gcc.rb` without Homebrew.

Since 2026-11-16 (owner: option A) the recipe has **no Homebrew dependency**:

- gmp, mpfr, mpc and isl are built in-tree from GCC's own prerequisite archives;
- zstd is left out (`--without-zstd`; it only compresses LTO bytecode);
- make is Apple's `/usr/bin/make`.

The build id is `71abf0a170ab`, from `macos/build-inputs.json`. The first D33 build
(`16.2.0-9f99e2b94d93`, Homebrew libraries) stays recorded byte for byte in `macos/d33-*`, and
this recipe never writes to its folder.

| File | What it is |
|---|---|
| `pins.toml` | Tarball and patch URLs with sha256, the Homebrew commit, the prerequisite archives, host versions |
| `build.sh` | Fetch, check, patch, unpack the prerequisites in-tree, configure, make and install. `--check` stops after building the four libraries |
| `macos/build-inputs.json` | This recipe's inputs record. The build id is the first 12 hex digits of its sha256 |
| `macos/configure-args.txt` | The configure arguments after `--prefix` and `--with-pkgversion`, one per line; `build.sh` reads them |
| `macos/d33-inputs.json`, `macos/d33-configure-args.txt` | The first D33 build's records, byte for byte (id `9f99e2b94d93`) |

## The in-tree prerequisites

`configure` downloads nothing: it builds gmp, mpfr, mpc and isl along with GCC when it finds
their sources in `gmp/`, `mpfr/`, `mpc/` and `isl/` beside `gcc/`. GCC's
`contrib/download_prerequisites` fetches them from `https://gcc.gnu.org/pub/gcc/infrastructure/`
and checks the sha512 list in `contrib/prerequisites.sha512`. That script also always adds gettext,
and there is no option to skip it. `--disable-nls` doesn't need gettext, so `build.sh` fetches the
same four archives itself and checks each against that sha512 list in the pinned GCC tarball:

| Library | Archive | First D33 build (Homebrew) |
|---|---|---|
| gmp | `gmp-6.3.0.tar.bz2` | 6.3.0 |
| mpfr | `mpfr-4.2.2.tar.bz2` | 4.2.2 |
| mpc | `mpc-1.3.1.tar.gz` | 1.4.1 |
| isl | `isl-0.24.tar.bz2` | 0.28 |

mpc and isl are older than the Homebrew ones. GCC's `install.texi` says the in-tree build "is only
supported with the GMP version that download_prerequisites installs", and the same for MPFR and
MPC, so this recipe uses GCC's set. They are built as static libraries into the compiler, so a
library upgrade can no longer break an installed GCC.

## Evidence

- **`--check` run (2026-11-16, Xcode 27.2, `-j4`, 2m03s):**
  - the tarball, the patch and the four archives all checked OK;
  - `configure` used the in-tree libraries ("using in-tree isl");
  - `libgmp.a`, `libmpfr.a`, `libmpc.a` and `libisl.a` built with `/usr/bin/make` 3.81;
  - `configure.log` names no `/opt/homebrew` path.
- **Tarball and patch.** The tarball sha256 matches `gcc.rb` at homebrew-core `4a334d2f`. The
  patch at its URL hashes to the recorded sha256. The first D33 build applied it: a reverse dry
  run in its source tree exits 0.
- **Configure and make.** These are the first D33 build's arguments, with four changes:
  - the Homebrew `--with-gmp`, `--with-mpfr`, `--with-mpc` and `--with-isl` are removed;
  - `--with-zstd` is replaced by `--without-zstd`;
  - the make arguments `BOOT_LDFLAGS` and `LDFLAGS_FOR_TARGET=-Wl,-headerpad_max_install_names`
    are kept, as in `gcc.rb`;
  - make is `/usr/bin/make`. GCC needs GNU make 3.80 or later, per `install.texi`.

## Full build (2026-11-16)

`build.sh <scratch> 6` with `HOME` pointed into a scratch folder, so the install and its
`current` link landed there and the installed D33 build was not touched:

- **Result:** exit 0 in 58 minutes, three-stage bootstrap, peak 8.7 GB (8.1 GB build, 0.5 GB
  install).
- **No Homebrew:** `otool -L` on `cc1`, `cc1plus`, `lto1` and `f951` lists only
  `/usr/lib/libSystem.B.dylib`, `/usr/lib/libz.1.dylib` and `/usr/lib/libiconv.2.dylib`.
- **macOS playbook checks:**
  - G1: pkgversion `cpp-standard GCC 16.2.0 (D33 71abf0a170ab)`;
  - G2: the reflection probe prints `members=2`, and the CMake probe prints `import std ok`;
  - G3: `--with-sysroot` is Xcode's `MacOSX.sdk`, 27.2;
  - G4: ASan and UBSan fire, and `-fsanitize=thread` fails to link (`___tsan_func_entry`), as
    expected;
  - G6: `-g` with ASan links.
  - G5 is a rule, not a probe.
- **The same recipe on Ubuntu 26.10 amd64** (configure without `--build` and `--with-sysroot`,
  plus `--disable-multilib`) bootstraps in 32 minutes at `-j16` and links no gmp, mpfr, mpc,
  isl or zstd.

Not done yet: installing this build as the real `current`. Until then, `current` is the first
D33 build. **The job count** of the first D33 build was not recorded; `build.sh` defaults to
the CPU count.

## Guards

`build.sh` exits 3 before doing anything if any of these differs from `macos/build-inputs.json`:

- the Xcode build;
- the SDK version and path;
- Apple clang (`/usr/bin/clang`, `clang++`);
- `/usr/bin/make`;
- `ld`;
- the Darwin major.

It also:

- names those executables by path and sets `CC` and `CXX`;
- sets `PATH` to the Xcode toolchain plus the system folders (no `/opt/homebrew`);
- clears the `*_FOR_TARGET`, linker and search-path overrides, then checks which `ld` `PATH`
  selects;
- refuses an existing target folder, or a work folder that already holds sources or a build.

## Limits

- **rpath.** Programs it links record the hashed prefix as their rpath, not `current`
  (macOS playbook, G1).
- **No TSan or LSan,** and ASan hangs with `detect_leaks=1` (design, Risks; D33).
- **Not upstream.** The Darwin patch is not upstream. A new macOS SDK can break it; the fallback
  is reverting the bump.
- **Not yet a mise task**, and not yet run inside the Tart VM. Both belong to the
  unified-playbook work. That work will also decide whether Spack builds GCC, LLVM and p2996.
