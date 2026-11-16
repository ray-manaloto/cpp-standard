#!/usr/bin/env bash
# Build GCC 16.2.0 for macOS arm64 (D33) with no Homebrew dependency.
# The steps follow Homebrew's gcc.rb at the commit in pins.toml, without Homebrew: gmp, mpfr,
# mpc and isl are built in-tree from the exact archives GCC's contrib/prerequisites.sha512
# names, zstd is left out, and make is Apple's /usr/bin/make.
#
# Usage: toolchains/gcc-macos/build.sh <work-dir> [jobs] [--check]
#   Downloads and checks the sources, applies the Darwin patch, configures, builds and
#   installs into ~/.local/share/gcc-d33/16.2.0-<id>, where <id> is the first 12 hex digits
#   of the sha256 of macos/build-inputs.json. <work-dir> must be new, or hold only src/ archives.
#   --check stops after building the four in-tree libraries (stage 1) and installs nothing.
#
# macos/d33-inputs.json and macos/d33-configure-args.txt record the first D33 build
# (16.2.0-9f99e2b94d93, Homebrew libraries); this script no longer builds that one.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
check=0
args=()
for a in "$@"; do
  if [[ "$a" == --check ]]; then check=1; else args+=("$a"); fi
done
[[ ${#args[@]} -ge 1 ]] || {
  echo "usage: build.sh <work-dir> [jobs] [--check]" >&2
  exit 2
}
mkdir -p "${args[0]}"
work="$(cd "${args[0]}" && pwd)"
jobs="${args[1]:-$(sysctl -n hw.ncpu)}"

[[ "$(uname -sm)" == "Darwin arm64" ]] || {
  echo "build.sh: macOS arm64 only" >&2
  exit 2
}

ver=16.2.0
tar_url="https://ftp.gnu.org/gnu/gcc/gcc-${ver}/gcc-${ver}.tar.xz"
tar_sha=e6738e29597f733270731aa90600f37ffdc045079dfc27ec7e8192cc81085c3e
patch_url="https://raw.githubusercontent.com/Homebrew/homebrew-core/4a334d2f90f786c3fc86cbc9cf72b2f13961b078/Patches/gcc/gcc-${ver}.diff"
patch_sha=578a78ae0bc62a02f260b6a20c7f23e71deee16ed644e9cb5619247be4df5a71
# GCC's contrib/download_prerequisites base URL and archives, without gettext (that script
# always adds it; --disable-nls does not need it). Each is checked against the sha512 list
# that ships in the pinned GCC tarball.
prereq_url=https://gcc.gnu.org/pub/gcc/infrastructure/
prereqs=(gmp-6.3.0.tar.bz2 mpfr-4.2.2.tar.bz2 mpc-1.3.1.tar.gz isl-0.24.tar.bz2)

id="$(shasum -a 256 "$here/macos/build-inputs.json" | cut -c1-12)"
prefix="$HOME/.local/share/gcc-d33/${ver}-${id}"

# The executables this build uses, named by path so PATH and CC/CXX cannot swap them.
cc=/usr/bin/clang
cxx=/usr/bin/clang++
make=/usr/bin/make
sdk_want=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk

# The id names macos/build-inputs.json, so this host must match it. A host that differs needs a new
# inputs record (and so a new id).
bad=0
need() { # description have want
  [[ "$2" == "$3" ]] || {
    echo "build.sh: $1 is '${2:-missing}', macos/build-inputs.json says '$3'" >&2
    bad=1
  }
}
need "Xcode" "$(xcodebuild -version 2>/dev/null | tr '\n' ' ')" "Xcode 27.2 Build version 27B52 "
need "the SDK" "$(xcrun --show-sdk-version 2>/dev/null) $(xcrun --show-sdk-path 2>/dev/null)" "27.2 $sdk_want"
need "$cc" "$("$cc" --version 2>/dev/null | head -1)" "Apple clang version 21.0.0 (clang-2100.4.1.1)"
need "$cxx" "$("$cxx" --version 2>/dev/null | head -1)" "Apple clang version 21.0.0 (clang-2100.4.1.1)"
need "$make" "$("$make" --version 2>/dev/null | head -1)" "GNU Make 3.81"
need "the Darwin major" "$(uname -r | cut -d. -f1)" "27"
# Configure takes ld and as from PATH (D33: ld from the Xcode toolchain). Pin PATH to that
# toolchain plus the system folders, drop every *_FOR_TARGET, linker and search-path
# override, and check the ld that PATH now selects. /opt/homebrew is not on PATH.
xctc=/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin
export PATH="$xctc:/usr/bin:/bin:/usr/sbin:/sbin"
unset LD AS LD_FOR_TARGET AS_FOR_TARGET LD_FOR_BUILD AS_FOR_BUILD DEFAULT_LINKER DEFAULT_ASSEMBLER
unset CPATH LIBRARY_PATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
need "ld on PATH" "$(command -v ld)" "$xctc/ld"
need "ld" "$(ld -v 2>&1 | head -1 | sed 's/.*PROJECT://')" "ld-27106.1"
((bad == 0)) || exit 3
((check == 1)) || [[ ! -e "$prefix" ]] || {
  echo "build.sh: $prefix exists; refusing to overwrite it" >&2
  exit 3
}
[[ ! -e "$work/gcc-${ver}" && ! -e "$work/build" ]] || {
  echo "build.sh: $work already holds gcc-${ver} or build; use a new or empty work dir" >&2
  exit 3
}

mkdir -p "$work/src"
fetch() { # url dest
  if [[ ! -f "$2" ]]; then
    curl -fL --retry 3 -o "$2.part" "$1"
    mv "$2.part" "$2"
  fi
}
fetch "$tar_url" "$work/src/gcc-${ver}.tar.xz"
echo "$tar_sha  $work/src/gcc-${ver}.tar.xz" | shasum -a 256 -c -
fetch "$patch_url" "$work/src/gcc-${ver}.diff"
echo "$patch_sha  $work/src/gcc-${ver}.diff" | shasum -a 256 -c -

tar -C "$work" -xf "$work/src/gcc-${ver}.tar.xz"
src="$work/gcc-${ver}"
(cd "$src" && patch -p1 <"$work/src/gcc-${ver}.diff")

# In-tree libraries: each archive must match its line in the tarball's own sha512 list, then
# unpacks into gmp/, mpfr/, mpc/ or isl/ beside gcc/, where configure builds it with GCC.
for ar in "${prereqs[@]}"; do
  fetch "$prereq_url$ar" "$work/src/$ar"
  line="$(grep -F "  $ar" "$src/contrib/prerequisites.sha512")" || {
    echo "build.sh: $ar is not in contrib/prerequisites.sha512" >&2
    exit 3
  }
  (cd "$work/src" && echo "$line" | shasum -a 512 -c -)
  tar -C "$src" -xf "$work/src/$ar"
  base="${ar%.tar.*}"
  mv "$src/$base" "$src/${base%%-*}"
done

export CC="$cc" CXX="$cxx"
configure_args=()
while IFS= read -r line; do configure_args+=("$line"); done <"$here/macos/configure-args.txt"

mkdir -p "$work/build"
cd "$work/build"
"$src/configure" \
  --prefix="$prefix" \
  --with-pkgversion="cpp-standard GCC ${ver} (D33 ${id})" \
  "${configure_args[@]}" \
  2>&1 | tee ../configure.log

make_args=("BOOT_LDFLAGS=-Wl,-headerpad_max_install_names" "LDFLAGS_FOR_TARGET=-Wl,-headerpad_max_install_names")
if ((check == 1)); then
  "$make" -j"$jobs" "${make_args[@]}" all-stage1-gmp all-stage1-mpfr all-stage1-mpc all-stage1-isl \
    2>&1 | tee ../check.log
  ls -l gmp/.libs/libgmp.a mpfr/src/.libs/libmpfr.a mpc/src/.libs/libmpc.a isl/.libs/libisl.a
  echo "build.sh: --check passed: the four in-tree libraries built; nothing installed"
  exit 0
fi

# Avoid "Updated load commands do not fit in the header" (gcc.rb).
"$make" -j"$jobs" "${make_args[@]}" 2>&1 | tee ../build.log

# D33 installs straight into the prefix (no DESTDIR) and does not strip: stripping makes the
# binaries unsuitable for loading plugins (gcc.rb).
"$make" install 2>&1 | tee ../install.log
# No compiler binary may link a Homebrew library. otool -L exits 0 even when it cannot open a
# file, so each binary must exist and otool's output must start with its path; anything else
# stops the script instead of passing the check.
for bin in cc1 cc1plus lto1 f951; do
  path="$prefix/libexec/gcc/aarch64-apple-darwin27/16/$bin"
  [[ -x "$path" ]] || {
    echo "build.sh: $path is missing" >&2
    exit 1
  }
  libs="$(otool -L "$path" 2>&1)"
  [[ "$libs" == "$path:"* ]] || {
    echo "build.sh: otool -L failed on $path: $libs" >&2
    exit 1
  }
  if grep -q /opt/homebrew <<<"$libs"; then
    echo "build.sh: $bin links a Homebrew library" >&2
    exit 1
  fi
done
ln -sfn "${ver}-${id}" "$HOME/.local/share/gcc-d33/current"
"$prefix/bin/g++-16" --version | head -1
