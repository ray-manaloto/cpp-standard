#!/usr/bin/env bash
# Install from the signed Ubuntu snapshot. Only these first APT requests use
# the CA bundle supplied by the image-ID-pinned donor. Subsequent HTTPS uses
# the Ubuntu ca-certificates package installed into this fresh root.
install_snapshot_prerequisites() {
  local ca_file="$1" snapshot
  test -s "$ca_file" || return 1
  snapshot="$(sed -nE 's/^APT::Snapshot "([0-9]{8}T[0-9]{6}Z)";$/\1/p' mise.ubuntu.toml)"
  [[ "$snapshot" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || return 1
  local -a apt_options=(-o "APT::Snapshot=$snapshot" -o "Acquire::https::CaInfo=$ca_file")
  apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update || return "$?"
  apt-get "${apt_options[@]}" install -y --no-install-recommends ca-certificates curl
}

# The post-packages task can refresh .mise/mise.lock. Keep the archive sealed
# and /work empty for the later source build.
bootstrap_compiler_project() (
  set -eu
  project="$(mktemp -d "${TMPDIR:-/tmp}/cpp-bootstrap.XXXXXXXX")"
  trap 'rm -rf -- "$project"' EXIT
  cp -R "$1/." "$project/"
  chmod u+w "$project" "$project/.mise"
  cd "$project"
  # Project-only tools (including lint shims) live and die with this checkout.
  # The later locked cert install starts with its own empty mise data directory.
  export MISE_DATA_DIR="$project/.bootstrap-tools"
  PATH="$MISE_DATA_DIR/shims:$PATH" CI=true MISE_TRUSTED_CONFIG_PATHS="$PWD" mise -E ubuntu bootstrap --yes
)

# Run with the locked cert tool binaries on PATH. The project profile selects
# sccache only on macOS, and Ninja can invoke its compiler launcher from /work.
build_p2996() {
  MISE_AUTO_INSTALL=0 mise -C "${MISE_GLOBAL_CONFIG_FILE%/*}" exec -- bash "$@"
}

# Inside the fresh, capped Ubuntu container only.
[[ "${BASH_SOURCE[0]}" == "$0" ]] || return 0
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive MISE_YES=1
export MISE_TRUSTED_CONFIG_PATHS=/project:/opt/cpp-standard-tools
export PATH="/root/.local/share/mise/shims:$PATH"

[[ "$(dpkg --print-architecture)" == amd64 && "$(uname -m)" == x86_64 ]]
grep -Fx 'VERSION_ID="26.10"' /etc/os-release
grep -zFxq container=docker /proc/1/environ
test ! -e /var/run/docker.sock
read -r quota period </sys/fs/cgroup/cpu.max
test "$quota" -eq "$((16 * period))"
test "$(cat /sys/fs/cgroup/memory.max)" = 51539607552
test "$(cat /sys/fs/cgroup/memory.swap.max)" = 0
cat /sys/fs/cgroup/{cpu.max,memory.max,memory.swap.max,pids.max}

cd /project
install_snapshot_prerequisites /tmp/cpp-bootstrap-ca.crt
test -s /etc/ssl/certs/ca-certificates.crt
rm /tmp/cpp-bootstrap-ca.crt
read -r mise_version mise_digest < <(awk -F '[=" ]+' '
  $1 == "ARG" && $2 == "MISE_VER" { v = $3 }
  $1 == "ARG" && $2 == "MISE_SHA256_AMD64" { h = $3 }
  END { print v, h }
' docs/standard/ubuntu-cert.Dockerfile)
[[ "$mise_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$mise_digest" =~ ^[0-9a-f]{64}$ ]]
curl --fail --silent --show-error --location --retry 2 --max-time 180 \
  "https://github.com/jdx/mise/releases/download/v${mise_version}/mise-v${mise_version}-linux-x64.tar.gz" -o /tmp/mise.tar.gz
printf '%s  %s\n' "$mise_digest" /tmp/mise.tar.gz | sha256sum -c -
tar -C /tmp -xzf /tmp/mise.tar.gz mise/bin/mise
install -m 0755 /tmp/mise/bin/mise /usr/local/bin/mise
rm -rf /tmp/mise /tmp/mise.tar.gz
mise --version
bootstrap_compiler_project /project

# The cert tool profile has its own platform lock, independent of project tools.
cp -r docs/standard/ubuntu-cert-tools /opt/cpp-standard-tools
export MISE_GLOBAL_CONFIG_FILE=/opt/cpp-standard-tools/mise.toml
(cd /opt/cpp-standard-tools && mise install --locked && mise reshim)

# The image-ID-pinned addon donor supplies only these five /opt trees. The
# compiler packages and all p2996 files must come from this fresh build.
test "$(dpkg-query -W -f='${Version}' clang-23)" = \
  '1:23.1.6~++20261116013916+5b10d2d74929-1~exp1~20261116133927.96'
"$(command -v clang-23)" --version
gcc-16 --version
for tool in include-what-you-use iwyu_tool.py fix_includes.py; do
  ln -s "/opt/iwyu-llvm23/bin/$tool" "/usr/local/bin/$tool"
done
stock_iwyu_version="$(/opt/iwyu-llvm23/bin/include-what-you-use --version)"
printf 'T3 stock LLVM 23 IWYU: %s\n' "$stock_iwyu_version"
grep -F '0.27 (git:c9cbc83)' <<<"$stock_iwyu_version"
grep -F '5b10d2d74929' <<<"$stock_iwyu_version"
test -s /opt/llvm23-offload/lib/nvptx64-nvidia-cuda/libomptarget-nvptx.bc
ln -s /opt/llvm23-offload/lib/nvptx64-nvidia-cuda /usr/lib/llvm-23/lib/nvptx64-nvidia-cuda
for cuda in 12.9 13.2; do
  test -s "/opt/cuda-$cuda/nvvm/libdevice/libdevice.10.bc"
  "/opt/cuda-$cuda/bin/ptxas" --version
done
/opt/llvm-23.1.6/bin/clangd --version | grep -F 'clangd version 23.1.6'
sha256sum /opt/llvm-23.1.6/bin/clangd /opt/iwyu-llvm23/bin/include-what-you-use \
  /opt/llvm23-offload/lib/nvptx64-nvidia-cuda/libomptarget-nvptx.bc

apt_opts=(-o Dir::Etc::sourceparts=- -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources)
apt-get "${apt_opts[@]}" -o APT::Update::Error-Mode=any update
deps=(python3-dev swig libedit-dev libxml2-dev zlib1g-dev libzstd-dev libncurses-dev libffi-dev)
plan="$(apt-get "${apt_opts[@]}" -s --no-install-recommends install "${deps[@]}")"
printf '%s\n' "$plan"
if grep -Eq '^Remv |^Inst [^ ]+ \[' <<<"$plan"; then
  echo 'Build prerequisites would remove or upgrade installed packages' >&2
  exit 1
fi
apt-get "${apt_opts[@]}" -y --no-install-recommends install "${deps[@]}"
test ! -e /opt/p2996
test -z "$(ls -A /work)"
export FLANG_JOBS=1 SCCACHE_DIR=/work/sccache SCCACHE_CACHE_SIZE=2G
# Six Ninja workers fit the proven p2996 memory profile inside the 16/48 cap.
# This recipe builds P8's pinned IWYU from source in the p2996 LLVM tree.
build_p2996 /project/docs/standard/ubuntu-p2996/build-linux.sh /work /opt/p2996 6
/opt/p2996/bin/clang --version
p2996_head="$(git -C /work/src rev-parse HEAD)"
p2996_iwyu_head="$(git -C /work/iwyu rev-parse HEAD)"
printf 'clang-p2996 source: %s\nP8 IWYU source: %s\n' "$p2996_head" "$p2996_iwyu_head"
p2996_iwyu=/opt/p2996/bin/include-what-you-use
if [[ ! -f "$p2996_iwyu" || ! -x "$p2996_iwyu" || -L "$p2996_iwyu" ]]; then
  echo "P8: expected a freshly installed executable at $p2996_iwyu" >&2
  exit 1
fi
p2996_iwyu_version="$("$p2996_iwyu" --version)"
printf 'P8 clang-p2996 IWYU: %s\n' "$p2996_iwyu_version"
if [[ "$p2996_iwyu_version" != *"include-what-you-use 0.25 (git:${p2996_iwyu_head:0:7})"* ||
  "$p2996_iwyu_version" != *"clang version 21."* ||
  "$p2996_iwyu_version" != *"$p2996_head"* ]]; then
  echo 'P8: IWYU version does not match the pinned IWYU and clang-p2996 sources' >&2
  exit 1
fi
sha256sum "$p2996_iwyu"
find /opt/p2996 -type f -print0 | sort -z | xargs -0 -r sha256sum
