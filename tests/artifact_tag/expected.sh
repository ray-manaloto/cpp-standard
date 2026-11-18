#!/usr/bin/env bash
# Computes the expected tags of tests/artifact_tag/vectors.toml from environment-standard.md
# section 2 alone, with git hash-object, yq, jq and shasum, so the golden vectors do not come
# from python/pins/pins.py. Prints "<vector name><TAB><tag>" for each vector. Rerun it by hand
# only when the hash-input table or the vectors change; bash 3.2 (macOS) is enough.
set -euo pipefail

vectors="${1:-$(dirname "$0")/vectors.toml}"
spec="$(yq -p toml -o json '.' "$vectors")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Write tree + change - remove of vector $1 under $2.
materialize() {
  local i="$1" dir="$2" path
  rm -rf "$dir"
  mkdir -p "$dir"
  while IFS= read -r path; do
    mkdir -p "$dir/$(dirname "$path")"
    jq -j --arg p "$path" --argjson i "$i" '(.tree + (.vector[$i].change // {}))[$p]' <<<"$spec" >"$dir/$path"
  done < <(jq -r --argjson i "$i" '(.tree + (.vector[$i].change // {})) | keys[]' <<<"$spec")
  while IFS= read -r path; do
    rm -f "$dir/$path"
  done < <(jq -r --argjson i "$i" '.vector[$i].remove // [] | .[]' <<<"$spec")
}

# Lines are "key<TAB>value" in $lines; the hash input is "schema = 1\n" and then each
# "key\0value\n", sorted by key.
lines=""
add() { lines+="$1"$'\t'"$2"$'\n'; }
add_file() {
  [[ -f "$dir/$1" ]] || {
    echo "missing $1" >&2
    exit 1
  }
  add "$1" "$(git hash-object --no-filters "$dir/$1")"
}
add_slice() { # <platform> <tool>...
  local platform="$1"
  shift
  local tools json
  tools="$(printf '%s\n' "$@" | LC_ALL=C sort | paste -sd, -)"
  json="$(yq -p toml -o json '.' "$dir/.mise/mise.lock" | jq -cS --arg p "platforms.$platform" --arg t "$tools" '
    .tools as $all
    | [($t | split(",") | map(select(. != ""))[]) as $n
      | {key: $n, value: [$all[$n][] | (with_entries(select(.key | startswith("platforms.") | not)) + {platform: .[$p]})]}]
    | from_entries')"
  add ".mise/mise.lock#$platform:$tools" "$(printf '%s' "$json" | shasum -a 256 | cut -c1-64)"
}
digest() {
  {
    printf 'schema = 1\n'
    printf '%s' "$lines" | LC_ALL=C sort -t $'\t' -k1,1 | while IFS=$'\t' read -r k v; do printf '%s\0%s\n' "$k" "$v"; done
  } | shasum -a 256 | cut -c1-16
}

base() { # <arch>
  lines=""
  local f
  for f in image/base.Dockerfile image/base.inputs.toml .mise/conf.d/apt.toml \
    .mise/conf.d/apt-toolchain-host.toml .mise/conf.d/apt-sources.toml .mise/tasks/artifact/build; do
    add_file "$f"
  done
  echo "base-$1-$(digest)"
}

tools() { # <arch>
  local b platform names sidecar f
  b="$(base "$1")"
  platform="linux-$([[ $1 == amd64 ]] && echo x64 || echo "$1")"
  lines=""
  add base-tag "$b"
  for f in image/tools.Dockerfile .mise/conf.d/tools.toml .mise/tasks/artifact/build; do add_file "$f"; done
  names=()
  while IFS= read -r f; do names+=("$f"); done < <(yq -p toml -o json '.tools | keys | .[]' "$dir/.mise/conf.d/tools.toml" | jq -r .)
  add_slice "$platform" "${names[@]}"
  local tool
  while IFS=$'\t' read -r tool sidecar; do
    # git keeps no empty directory, so a sidecar without files is missing.
    if [[ -z "$(find "$dir/.mise/$sidecar" -type f 2>/dev/null)" ]]; then
      echo "error: sidecar .mise/$sidecar of $tool is not in the commit"
      return
    fi
    while IFS= read -r f; do add_file "${f#"$dir"/}"; done < <(find "$dir/.mise/$sidecar" -type f)
  done < <(yq -p toml -o json '.' "$dir/.mise/mise.lock" | jq -r --argjson n "$(printf '%s\n' "${names[@]}" | jq -R . | jq -s .)" \
    '.tools | to_entries[] | select(.key as $k | $n | index($k)) | .key as $k | .value[] | select(.uv.path) | "\($k)\t\(.uv.path)"')
  echo "tools-$1-$(digest)"
}

# Every file under a directory of the tree, if there is one.
add_dir() {
  local f
  [[ -d "$dir/$1" ]] || return 0
  while IFS= read -r f; do add_file "${f#"$dir"/}"; done < <(find "$dir/$1" -type f)
}

toolchain() { # <name> <os> <arch>
  local t="toolchains/$1" f host apt platform
  lines=""
  apt="$(yq -p toml -o json '.apt_compiler' "$dir/$t/pins.toml" | jq -r 'if type == "boolean" then . else "invalid" end')"
  if [[ $apt == invalid ]]; then
    echo "error: $t/pins.toml: apt_compiler is not true or false"
    return
  fi
  for f in "$t/pins.toml" "$t/build.sh" .mise/tasks/artifact/build; do add_file "$f"; done
  if [[ $2 == linux ]]; then
    platform="linux-$([[ $3 == amd64 ]] && echo x64 || echo "$3")"
    add_file .mise/conf.d/apt-toolchain-host.toml
    add_file .mise/conf.d/apt-sources.toml
    add_dir "$t/linux"
  else
    if [[ $3 != arm64 ]]; then
      echo "error: macOS toolchains are built for arm64 only"
      return
    fi
    platform=macos-arm64
    add_file vm/inputs.toml
    add_dir "$t/macos"
  fi
  [[ $apt == true ]] && add_file .mise/conf.d/apt.toml
  host=()
  while IFS= read -r f; do host+=("$f"); done < <(yq -p toml -o json '.host_tools[]' "$dir/$t/pins.toml" | jq -r .)
  add_slice "$platform" ${host[@]+"${host[@]}"}
  echo "$1-$2-$3-$(digest)"
}

count="$(jq '.vector | length' <<<"$spec")"
for ((i = 0; i < count; i++)); do
  name="$(jq -r --argjson i "$i" '.vector[$i].name' <<<"$spec")"
  artifact="$(jq -r --argjson i "$i" '.vector[$i].artifact' <<<"$spec")"
  arch="$(jq -r --argjson i "$i" '.vector[$i].arch // "arm64"' <<<"$spec")"
  dir="$work/$i"
  materialize "$i" "$dir"
  case "$artifact" in
    base) tag="$(base "$arch")" ;;
    tools) tag="$(tools "$arch")" ;;
    runner-pc) tag="error: runner-pc: the actions/runner version input has no defined file or form in the design (section 2)" ;;
    golden) tag="error: golden: the actions/runner version input and the tag name are not defined in the design (section 2)" ;;
    *-linux-*) tag="$(toolchain "${artifact%-linux-*}" linux "${artifact##*-linux-}")" ;;
    *-macos-*) tag="$(toolchain "${artifact%-macos-*}" macos "${artifact##*-macos-}")" ;;
  esac
  printf '%s\t%s\n' "$name" "$tag"
done
