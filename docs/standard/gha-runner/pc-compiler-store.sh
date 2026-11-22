# shellcheck shell=bash
# shellcheck disable=SC2154 # The sourcing host worker owns the attempt variables.
# Sourced by the protected host worker after assignment. The listener has no store access.
compiler_cache() {
  python3 -I -B "$source/docs/standard/gha-runner/pc-compiler-cache.py" "$@"
}

seed_retained_compiler() {
  local prior previous id old_sha name old_base old_donor
  local -a attempts=("$STATE/cpp-compiler.$seed_run."*)
  [[ ${#attempts[@]} == 1 ]] || return 1
  prior="${attempts[0]}/result"
  [[ "$(stat -c '%u:%a' "${attempts[0]}")" == 0:700 && ! -L "${attempts[0]}" ]]
  [[ "$(cat "$prior/build-exit.txt")" == 'wait_exit=0 container_exit=0' ]]
  previous="$(jq -ce --arg run "$seed_run" 'select(.run==$run)' "$prior/assignment.json")"
  old_sha="$(jq -er .commit <<<"$previous")"
  old_base="$(jq -er .base <<<"$previous")"
  old_donor="$(jq -er .addon_donor <<<"$previous")"
  name="$(jq -er .runner <<<"$previous")"
  id="$(cat "$prior/built-image")"
  [[ "$id" =~ ^sha256:[0-9a-f]{64}$ && "$old_sha" =~ ^[0-9a-f]{40}$ ]]
  [[ "$old_base" == "$base_id" && "$old_donor" == "$donor" ]]
  git --git-dir="$git_dir" merge-base --is-ancestor "$old_sha" "$sha"
  [[ "$(docker image inspect -f '{{.Id}} {{.Os}}/{{.Architecture}} {{index .Config.Labels "org.cpp-standard.compiler"}}' "$id")" == "$id linux/amd64 ${name%-runner}" ]]
  install -d -m 0700 "$state/seed-source" "$transfer/seed"
  git --git-dir="$git_dir" archive "$old_sha" docs/standard/ubuntu-p2996 | tar -C "$state/seed-source" -xf -
  awk '/^[0-9a-f]{64}  \/opt\/p2996\// {print}' "$prior/build.log" | LC_ALL=C sort -u >"$transfer/seed/expected"
  test -s "$transfer/seed/expected"
  # Check the old image using its own installed compilers and original recipe. Only the
  # prefix passes to the new image. The historical checklist status is independent.
  docker run --rm --name "$check-seed" --platform linux/amd64 --privileged=false \
    --label "org.cpp-standard.compiler=$owner_name" --network none --cap-drop ALL \
    --security-opt no-new-privileges --pids-limit 512 --cpus 2 --memory 4g --memory-swap 4g \
    --mount "type=bind,src=$state/seed-source,dst=/prior-source,readonly" \
    --mount "type=bind,src=$source/docs/standard/gha-runner/pc-compiler-cache.py,dst=/cache-source/docs/standard/gha-runner/pc-compiler-cache.py,readonly" \
    --mount "type=bind,src=$transfer/inputs.json,dst=/expected-inputs,readonly" \
    --mount "type=bind,src=$transfer/seed,dst=/seed" -e MISE_AUTO_INSTALL=0 \
    --entrypoint /usr/local/bin/mise "$id" -C /opt/cpp-standard-tools exec -- bash -euo pipefail -c '
      /usr/bin/python3 -I -B /cache-source/docs/standard/gha-runner/pc-compiler-cache.py identity /prior-source "$1" "$2" >/seed/old-inputs
      cmp /expected-inputs /seed/old-inputs
      find /opt/p2996 -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum | LC_ALL=C sort -u >/seed/actual
      cmp /seed/expected /seed/actual
      cp -a /opt/p2996 /seed/p2996
    ' _ "$old_base" "$old_donor"
  compiler_cache pack "$transfer/inputs.json" "$transfer/seed/p2996" "$transfer/package"
  rm -rf -- "$transfer/seed/p2996"
  printf 'producer_run=%s\nproducer_image=%s\nproducer_sha=%s\n' "$seed_run" "$id" "$old_sha" >"$result/compiler-seed.txt"
}

resolve_compiler_package() {
  local mode existing
  while [[ ! -f "$transfer/inputs.json" ]]; do
    [[ "$(docker inspect -f '{{.State.Running}}' "$build")" == true ]] || return 0
    sleep 2
  done
  cp "$transfer/inputs.json" "$result/compiler-inputs.json"
  key="$(sha256sum "$result/compiler-inputs.json" | cut -d' ' -f1)"
  [[ "$key" =~ ^[0-9a-f]{64}$ ]]
  if [[ -e "$compiler_store/packages/$key" ]]; then
    mode=local
  elif [[ -n "$seed_run" ]]; then
    seed_retained_compiler
    mode=retained
  else
    # Only this host-side read can use the App credential. The public blobs are
    # pulled by digest; the publisher identity is verified before acceptance.
    GH_TOKEN="$TOKEN" compiler_cache remote "$result/compiler-inputs.json" "$compiler_store/packages" >"$result/compiler-registry.log"
    existing="$(tail -1 "$result/compiler-registry.log")"
    if [[ "$existing" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      mode=registry
    elif [[ "$existing" == absent && -n "$cold_reason" ]]; then
      mode=cold
      printf '%s\n' "$cold_reason" >"$result/compiler-source-change.txt"
    elif [[ "$existing" == absent ]]; then
      echo "No verified compiler for $key; recover a retained build with --seed-run or identify the necessary source change." >&2
      mode=unavailable
    else
      echo "Invalid registry result for $key" >&2
      return 1
    fi
  fi
  printf '%s\n' "$mode" >"$transfer/decision.tmp"
  mv "$transfer/decision.tmp" "$transfer/decision"
  printf 'inputs_sha256=%s\nsource=%s\n' "$key" "$mode" >"$result/compiler-cache.txt"
}

retain_compiler_package() {
  local mode entry
  mode="$(cat "$transfer/decision")"
  entry="$compiler_store/packages/$key"
  if [[ "$mode" == cold || "$mode" == retained ]]; then
    compiler_cache verify "$result/compiler-inputs.json" "$transfer/package"
    if [[ "$mode" == retained ]]; then
      cp "$result/compiler-seed.txt" "$transfer/package/producer.txt"
    else
      printf 'producer_run=%s\nproducer_sha=%s\n' "$run" "$sha" >"$transfer/package/producer.txt"
    fi
    test ! -e "$entry"
    mv -T "$transfer/package" "$entry"
  fi
  if [[ "$mode" == cold ]]; then cp "$transfer/compiler-sccache.json" "$result/compiler-sccache.json"; fi
  cp "$entry/package.json" "$result/compiler-package.json"
  if [[ -f "$entry/producer.txt" ]]; then cp "$entry/producer.txt" "$result/compiler-producer.txt"; fi
  if [[ -e "$entry/registry-digest" ]]; then cp "$entry/registry-digest" "$result/compiler-registry-digest"; fi
  if [[ "$mode" == cold || "$mode" == retained || "$stage_package" == 1 ]]; then
    compiler_cache publish-files "$result/compiler-inputs.json" "$entry" "$state/oci"
    chmod a+r "$state/oci/"*
    mv "$state/oci/"* "$state/publish/"
    printf '%s\n' "p2996-pc-linux-amd64-${key:0:16}" >"$state/publish/tag"
    chmod 0444 "$state/publish/tag"
  fi
}
