#!/usr/bin/env bash
# Build GCC 16.2.0 for macOS arm64 the way the D33 build of 2026-11-15 was built.
# The steps follow Homebrew's gcc.rb at the commit in pins.toml, without Homebrew.
#
# Usage: toolchains/gcc-macos/build.sh <work-dir> [jobs]
#   Downloads and checks the tarball and patch, applies the patch, configures, builds and
#   installs into ~/.local/share/gcc-d33/16.2.0-<id>, where <id> is the first 12 hex digits
#   of the sha256 of macos/d33-inputs.json (the D33 build's own inputs record).
#   <work-dir> must be new or empty: sources are always extracted and patched afresh.
#
# Not yet run from this script: it records the D33 recipe (see README.md). The original
# build's parallel-job count was not recorded; the default here is the CPU count.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
[[ $# -ge 1 ]] || {
  echo "usage: build.sh <work-dir> [jobs]" >&2
  exit 2
}
mkdir -p "$1"
work="$(cd "$1" && pwd)"
jobs="${2:-$(sysctl -n hw.ncpu)}"

[[ "$(uname -sm)" == "Darwin arm64" ]] || {
  echo "build.sh: macOS arm64 only" >&2
  exit 2
}

ver=16.2.0
tar_url="https://ftp.gnu.org/gnu/gcc/gcc-${ver}/gcc-${ver}.tar.xz"
tar_sha=e6738e29597f733270731aa90600f37ffdc045079dfc27ec7e8192cc81085c3e
patch_url="https://raw.githubusercontent.com/Homebrew/homebrew-core/4a334d2f90f786c3fc86cbc9cf72b2f13961b078/Patches/gcc/gcc-${ver}.diff"
patch_sha=578a78ae0bc62a02f260b6a20c7f23e71deee16ed644e9cb5619247be4df5a71

id="$(shasum -a 256 "$here/macos/d33-inputs.json" | cut -c1-12)"
prefix="$HOME/.local/share/gcc-d33/${ver}-${id}"

# The executables this build uses, named by path so PATH and CC/CXX cannot swap them.
cc=/usr/bin/clang
cxx=/usr/bin/clang++
gmake=/opt/homebrew/opt/make/bin/gmake
sdk_want=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk

# The id names the D33 inputs record, so this host must match that record. Otherwise a build
# with other tools or libraries would land in, and overwrite, the D33 folder. A host that
# differs needs a new inputs record (and so a new id), not this one.
bad=0
need() { # description have want
  [[ "$2" == "$3" ]] || {
    echo "build.sh: $1 is '${2:-missing}', the D33 record says '$3'" >&2
    bad=1
  }
}
for kv in gmp=6.3.0 mpfr=4.2.2 libmpc=1.4.1 isl=0.28 zstd=1.5.7_1 make=4.4.1; do
  k="${kv%%=*}"
  need "Homebrew $k" "$(basename "$(readlink "/opt/homebrew/opt/$k" 2>/dev/null)" 2>/dev/null || true)" "${kv#*=}"
done
need "Xcode" "$(xcodebuild -version 2>/dev/null | tr '\n' ' ')" "Xcode 27.2 Build version 27B52 "
need "the SDK" "$(xcrun --show-sdk-version 2>/dev/null) $(xcrun --show-sdk-path 2>/dev/null)" "27.2 $sdk_want"
need "$cc" "$("$cc" --version 2>/dev/null | head -1)" "Apple clang version 21.0.0 (clang-2100.4.1.1)"
need "$cxx" "$("$cxx" --version 2>/dev/null | head -1)" "Apple clang version 21.0.0 (clang-2100.4.1.1)"
# Configure takes ld and as from PATH (D33: ld from the Xcode toolchain). Pin PATH to that
# toolchain plus the system folders, drop every *_FOR_TARGET and linker override, and check
# the ld that PATH now selects.
xctc=/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin
export PATH="$xctc:/usr/bin:/bin:/usr/sbin:/sbin"
unset LD AS LD_FOR_TARGET AS_FOR_TARGET LD_FOR_BUILD AS_FOR_BUILD DEFAULT_LINKER DEFAULT_ASSEMBLER
need "ld on PATH" "$(command -v ld)" "$xctc/ld"
need "ld" "$(ld -v 2>&1 | head -1 | sed 's/.*PROJECT://')" "ld-27106.1"
need "gmake" "$("$gmake" --version 2>/dev/null | head -1)" "GNU Make 4.4.1"
need "the Darwin major" "$(uname -r | cut -d. -f1)" "27"
((bad == 0)) || exit 3
[[ ! -e "$prefix" ]] || {
  echo "build.sh: $prefix exists; refusing to overwrite it" >&2
  exit 3
}
[[ ! -e "$work/gcc-${ver}" && ! -e "$work/build" ]] || {
  echo "build.sh: $work already holds gcc-${ver} or build; use a new or empty work dir" >&2
  exit 3
}

mkdir -p "$work/src"
fetch() { # url sha256 dest
  if [[ ! -f "$3" ]]; then
    curl -fL --retry 3 -o "$3.part" "$1"
    mv "$3.part" "$3"
  fi
  echo "$2  $3" | shasum -a 256 -c -
}
fetch "$tar_url" "$tar_sha" "$work/src/gcc-${ver}.tar.xz"
fetch "$patch_url" "$patch_sha" "$work/src/gcc-${ver}.diff"

tar -C "$work" -xf "$work/src/gcc-${ver}.tar.xz"
(cd "$work/gcc-${ver}" && patch -p1 <"$work/src/gcc-${ver}.diff")

export CC="$cc" CXX="$cxx"

mkdir -p "$work/build"
cd "$work/build"
# Order and values as in the D33 compiler's "Configured with:" line. The arguments after
# --with-pkgversion are macos/d33-configure-args.txt.
../gcc-${ver}/configure \
  --prefix="$prefix" \
  --with-pkgversion="cpp-standard GCC ${ver} (D33 ${id})" \
  --disable-nls \
  --enable-checking=release \
  --with-gcc-major-version-only \
  --enable-languages=c,c++,objc,obj-c++,fortran \
  --program-suffix=-16 \
  --with-gmp=/opt/homebrew/opt/gmp \
  --with-mpfr=/opt/homebrew/opt/mpfr \
  --with-mpc=/opt/homebrew/opt/libmpc \
  --with-isl=/opt/homebrew/opt/isl \
  --with-zstd=/opt/homebrew/opt/zstd \
  --with-system-zlib \
  --build=aarch64-apple-darwin27 \
  --with-sysroot="$sdk_want" \
  2>&1 | tee ../configure.log

# Avoid "Updated load commands do not fit in the header" (gcc.rb).
"$gmake" -j"$jobs" \
  BOOT_LDFLAGS=-Wl,-headerpad_max_install_names \
  LDFLAGS_FOR_TARGET=-Wl,-headerpad_max_install_names \
  2>&1 | tee ../build.log

# D33 installed straight into the prefix (no DESTDIR) and did not strip: stripping makes
# the binaries unsuitable for loading plugins (gcc.rb).
"$gmake" install 2>&1 | tee ../install.log
ln -sfn "${ver}-${id}" "$HOME/.local/share/gcc-d33/current"
"$prefix/bin/g++-16" --version | head -1
