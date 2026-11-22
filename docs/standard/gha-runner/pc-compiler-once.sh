#!/usr/bin/env bash
# Sourced only by the host gha-slot launcher. Never mounted into a runner.
compiler_once() {
  # Bash can unwind function locals before calling EXIT on an errexit. Keep
  # closeout state at launcher scope. This process runs exactly one attempt.
  run="${1:-}" rid='' worker='' phase=preflight execution_rc=0
  prepare_compiler "$@"
}

prepare_compiler() {
  local sha="${2:-}" trusted=/etc/gha-runner/cpp-compiler
  local repo=ray-manaloto/cpp-standard wf=.github/workflows/pc-compiler.yml
  local base_ref base_digest base_id donor=sha256:31a18ff1d600fcbc3eb860105f499ee290f03ef6a747a1bb63745a38e1ef6f04
  local image_ref hooked policy runner_img live head job job_id jit resp
  local refresh_at=0 seed_run='' cold_reason='' stage_package=0
  local p slot
  local began status=FAIL timing=unverified deadline path
  local passes=0 fails=0 na=0 total=0
  # The App may be unable to read group policy. Require operator confirmation
  # of group 6's exact CPP repository and protected-main workflow allowlist.
  [[ "$run" =~ ^[1-9][0-9]*$ && "$sha" =~ ^[0-9a-f]{40}$ && ($# == 3 || $# == 4 || $# == 5) &&
    "${3:-}" == --group-verified ]] ||
    die 'usage: gha-slot compiler-once <run-id> <main-sha> --group-verified [--seed-run ID | --source-change REASON | --stage-package]'
  if (($# == 4)); then
    [[ "$4" == --stage-package ]] || die 'unknown compiler publication option'
    stage_package=1
  fi
  if (($# == 5)); then
    case "$4" in
      --seed-run)
        [[ "$5" =~ ^[1-9][0-9]*$ ]] || die 'invalid seed run'
        seed_run="$5"
        ;;
      --source-change)
        [[ -n "$5" ]] || die 'missing compiler change or defect'
        cold_reason="$5"
        ;;
      *) die 'invalid compiler recovery option' ;;
    esac
  fi
  [[ $EUID == 0 && "$(hostname -s)" == nzxth1desktop && "$(uname -m)" == x86_64 ]] ||
    die 'compiler-once requires root on nzxth1desktop'
  unset DOCKER_CONTEXT
  export DOCKER_HOST=unix:///var/run/docker.sock
  [[ "$(cfg .github.api)" == https://api.github.com ]] || die 'unexpected GitHub API URL'
  [[ "$(cfg .github.owner)" == ray-manaloto ]] || die 'unexpected App owner'
  # shellcheck disable=SC2034 # app_token in gha-slot reads this selector
  APP="$(jq -er '[.apps | to_entries[] | select((.value.installation_id|tostring) == "180565088") | .key] |
    if length == 1 then .[0] else error("expected exactly one CPP App configuration") end' "$CONF")"
  export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
  # The installation pins its own source tree and runner image before JIT.
  [[ "$(stat -c '%u:%a' "$trusted")" == 0:755 && ! -L "$trusted" ]] ||
    die 'trusted compiler deployment missing or writable by a non-owner'
  hooked="$trusted/admission.sh"
  policy="$(stat -c '%u:%a' "$hooked")"
  [[ "$policy" == 0:555 && -f "$hooked" && ! -L "$hooked" ]] || die 'admission hook is not root-owned and read-only'
  [[ "$(stat -c '%u:%a' "$trusted/runner-image")" == 0:444 && ! -L "$trusted/runner-image" ]] ||
    die 'trusted runner image pin missing'
  runner_img="$(cat "$trusted/runner-image")"
  [[ "$runner_img" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'runner image pin must be a complete ID'
  [[ "$(docker image inspect -f '{{.Os}}/{{.Architecture}}' "$runner_img")" == linux/amd64 ]] ||
    die 'pinned Linux amd64 JIT image unavailable'
  [[ "$(docker version -f '{{.Server.Version}}')" == 29.9.2 ]] ||
    die 'Docker release must match the pinned certification seccomp profile'
  for p in bwrap jq flock timeout python3 nvidia-smi; do command -v "$p" >/dev/null; done
  # Check the installed fence. Do not repair the shared network in this lane.
  [[ "$(docker network inspect -f '{{index .Options "com.docker.network.bridge.name"}}' "$NET")" == br-gha ]]
  iptables -t mangle -C FORWARD -i br-gha -o tailscale0 -j DROP
  [[ "$(iptables -S DOCKER-USER | grep -c -- '-i br-gha .*ufw-docker-logging-deny')" -ge 6 ]]
  iptables -S ufw-before-input | grep -- '-i br-gha .*-j DROP' >/dev/null
  [[ "$(awk '$1=="MemAvailable:" {print $2}' /proc/meminfo)" -ge 58720256 ]] ||
    die 'less than 56 GiB host memory available for the 48-GiB build and incumbents'
  [[ "$(df -BG --output=avail "$(docker info -f '{{.DockerRootDir}}')" | awk 'NR==2 {sub(/G$/,"");print}')" -ge 120 ]] ||
    die 'less than 120 GiB in the Docker store'
  [[ "$(nproc)" -ge 16 ]] || die 'fewer than 16 host logical CPUs'
  [[ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]] || die 'NVIDIA compute device is in use'

  refresh_compiler_token() {
    if ((SECONDS >= refresh_at)); then
      # The installation token lasts an hour. Renew before it can expire
      # during the multi-hour build and checklist.
      TOKEN="$(app_token)" || die 'could not refresh the compiler GitHub App token'
      refresh_at=$((SECONDS + 45 * 60))
    fi
  }
  refresh_compiler_token
  live="$(api GET "/repos/$repo/actions/runs/$run")"
  jq -e --arg repo "$repo" --arg wf "$wf" --arg sha "$sha" '
    .event=="workflow_dispatch" and .head_branch=="main" and
    .head_sha==$sha and .head_repository.full_name==$repo and .repository.full_name==$repo and
    .path==$wf and .run_attempt==1 and (.status=="queued" or .status=="in_progress")
  ' <<<"$live" >/dev/null || die 'workflow run does not match the qualification'
  head="$(api GET "/repos/$repo/branches/main")"
  jq -e --arg sha "$sha" '.protected and .commit.sha==$sha' <<<"$head" >/dev/null ||
    die 'the requested SHA is not current protected main'
  # The checkout is prepared and sealed by the deployment operator. It is read
  # by git archive on the host and is never writable from the Actions job.
  local git_dir="$trusted/source.git"
  [[ "$(stat -c '%u:%a' "$git_dir")" == 0:755 && ! -L "$git_dir" ]] ||
    die 'sealed CPP source mirror missing'
  sha256sum --status -c <(
    printf '%s  %s\n' "$(git --git-dir="$git_dir" show "$sha:docs/standard/gha-runner/pc-compiler-admission.sh" | sha256sum | cut -d' ' -f1)" "$hooked"
  ) || die 'installed admission does not match the exact protected-main bytes'
  # shellcheck disable=SC2153 # STATE is the base directory defined by gha-slot
  install -d -m 0700 "$STATE"
  exec 8<"$STATE"
  flock -n 8 || die 'another one-time CPP compiler launch is active'
  # Only the protected build and project containers see the persistent object cache.
  compiler_store="$STATE/cpp-standard-amd64"
  install -d -m 0700 "$compiler_store" "$compiler_store"/{sccache,packages,mise-downloads,mise-release,uv,apt-archives,vcpkg-downloads}
  state="$(mktemp -d "$STATE/cpp-compiler.${run}.XXXXXXXX")"
  transfer="$state/transfer"
  install -d -m 0700 "$transfer"
  result="$state/result"
  source="$state/source"
  install -d -m 0755 "$result" "$source" "$state/publish"
  owner_name="cpp-compiler-$run-${state##*.}"
  owner_name="${owner_name,,}"
  runner="$owner_name-runner"
  build="$owner_name-build"
  donor_name="$owner_name-donor"
  check="$owner_name-check"
  work_volume="$build-work"
  cert_volume="$check-build"
  deadline=$((SECONDS + 19440))
  began="$(date -u +%FT%TZ)"

  supervise_compiler
}

seed_compiler_ca() {
  docker cp "$donor_name:/etc/ssl/certs/ca-certificates.crt" "$state/bootstrap-ca.crt" || return "$?"
  [[ -f "$state/bootstrap-ca.crt" && ! -L "$state/bootstrap-ca.crt" && -s "$state/bootstrap-ca.crt" ]] || return 1
  docker cp "$state/bootstrap-ca.crt" "$build:/tmp/cpp-bootstrap-ca.crt"
}

wait_compiler_build() {
  local name="$1" container_rc wait_rc=0
  container_rc="$(timeout --kill-after=30s 270m docker wait "$name")" || wait_rc=$?
  if ((wait_rc != 0)) || [[ ! "$container_rc" =~ ^(0|[1-9][0-9]{0,2})$ ]] || ((container_rc > 255)); then
    printf 'wait_exit=%s container_exit=unknown\n' "$wait_rc" >"$result/build-exit.txt"
    ((wait_rc != 0)) || return 1
    return "$wait_rc"
  fi
  printf 'wait_exit=0 container_exit=%s\n' "$container_rc" >"$result/build-exit.txt"
  return "$container_rc"
}

capture_compiler_build() {
  local cid
  [[ -s "$state/build.cid" && ! -f "$result/build.log" ]] || return 0
  [[ ! -e "$result/build-log-attempt.txt" ]] || return 1
  read -r cid <"$state/build.cid" || return 1
  [[ "$cid" =~ ^[a-f0-9]{64}$ &&
    "$(docker inspect -f '{{index .Config.Labels "org.cpp-standard.compiler"}}' "$cid")" == "$owner_name" ]] || return 1
  # Keep partial output and the Docker error if log retrieval itself fails.
  if docker logs "$cid" >"$result/build-log-attempt.txt" 2>&1; then
    mv "$result/build-log-attempt.txt" "$result/build.log"
  else
    return 1
  fi
}

check_compiler_rows() {
  local performance="$1" doc="$source/docs/standard/ubuntu.md"
  case "$performance" in verified | failed | unverified) ;; *) return 1 ;; esac
  awk -v performance="$performance" '
    FILENAME==ARGV[1] {
      if (match($0, /^\*\*[A-Z]+[0-9]+\./)) {
        expected[substr($0, 3, RLENGTH-3)]=1
        count++
      }
      next
    }
    !($1 in expected) || seen[$1]++ { bad=1 }
    $1=="P8" && $2=="PASS" { p2996_iwyu++ }
    $1=="T3" && $2=="PASS" { stock_iwyu++ }
    $2=="FAIL" && $1=="V6" && /^V6 +FAIL +\[timing: overhead limit exceeded\] / { overhead++; next }
    $2=="N/A" && (NF<3 || $1~/^(GO[123]|R2|V[12346])$/ || /timing untrusted/) { bad=1 }
    $2!="PASS" && $2!="N/A" { bad=1 }
    END {
      exit (bad || FNR!=count || p2996_iwyu!=1 || stock_iwyu!=1 ||
            (performance=="verified" && overhead) || (performance=="failed" && overhead!=1))
    }' "$doc" "$result/body.txt"
}

certify_compiler_project() {
  local candidate="$1" name="$check-project" tag="cpp-standard-qualified:run-$run" rc=0
  # Only the built image survives the first teardown. Launch a fresh project
  # container by local tag and compare its immutable ID before running it.
  release_compiler_workload keep-image
  docker image tag "$candidate" "$tag"
  # Run after the quiet checklist windows, with a private writable layer.
  docker create --name "$name" --platform linux/amd64 --privileged=false \
    --label "org.cpp-standard.compiler=$owner_name" --network "$NET" --dns 1.1.1.1 --dns 9.9.9.9 \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 32768 --cpus 16 --memory 48g --memory-swap 48g \
    --mount "type=bind,src=$compiler_store/sccache,dst=/cache/sccache" \
    --mount "type=bind,src=$compiler_store/vcpkg-downloads,dst=/cache/vcpkg-downloads" \
    -e VCPKG_DOWNLOADS=/cache/vcpkg-downloads -e SCCACHE_DIR=/cache/sccache -e SCCACHE_CACHE_SIZE=40G \
    --mount "type=bind,src=$source,dst=/project,readonly" --workdir /tmp \
    -e container=docker -e MISE_AUTO_INSTALL=0 -e MISE_TRUSTED_CONFIG_PATHS=/opt/cpp-standard-tools \
    --entrypoint /usr/local/bin/mise "$tag" -C /opt/cpp-standard-tools exec -- \
    /usr/bin/python3 -I -B /project/docs/standard/gha-runner/pc-compiler-project.py >"$state/project.cid"
  [[ "$(docker inspect -f '{{.Image}}' "$name")" == "$candidate" ]]
  printf 'image=%s checkout=%s run=%s job=%s host=%s\n' "$candidate" "$sha" "$run" "$job_id" "$(hostname -s)" >"$result/project-assignment.txt"
  timeout --kill-after=10s 25m docker start -a "$name" >"$result/project.log" 2>&1 || rc=$?
  if ((rc == 0)); then
    [[ "$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$name")" == 'exited 0' ]] || rc=1
  fi
  docker cp "$name:/tmp/project-evidence" "$result/project" || { ((rc != 0)) || rc=1; }
  return "$rc"
}

release_compiler_workload() {
  local failure=0 item built
  for item in "$check" "$build" "$donor_name"; do
    remove_compiler_container "$item" || failure=1
  done
  for item in "$work_volume" "$cert_volume"; do remove_compiler_volume "$item" || failure=1; done
  remove_compiler_container "$check-project" || failure=1
  remove_compiler_container "$check-seed" || failure=1
  if [[ "${1:-}" != keep-image && -s "$state/compiled-image" ]]; then
    built="$(cat "$state/compiled-image")"
    if [[ "$built" =~ ^sha256:[a-f0-9]{64}$ &&
      "$(docker image inspect -f '{{index .Config.Labels "org.cpp-standard.compiler"}}' "$built")" == "$owner_name" ]] &&
      docker image rm "$built" >/dev/null; then
      rm -f "$state/compiled-image" || failure=1
    else
      failure=1
    fi
  fi
  return "$failure"
}

remove_compiler_container() {
  local name="$1" matching
  matching="$(docker ps -aq --no-trunc --filter "name=^/${name}$")" || return 1
  [[ -n "$matching" ]] || return 0
  [[ "$matching" =~ ^[a-f0-9]{64}$ &&
    "$(docker inspect -f '{{index .Config.Labels "org.cpp-standard.compiler"}}' "$matching")" == "$owner_name" ]] || return 1
  docker rm -f "$matching" >/dev/null
}
remove_compiler_volume() {
  local name="$1" matching
  matching="$(docker volume ls -q --filter "name=^${name}$")" || return 1
  [[ -n "$matching" ]] || return 0
  [[ "$matching" == "$name" && "$(docker volume inspect -f '{{index .Labels "org.cpp-standard.compiler"}}' "$name")" == "$owner_name" ]] || return 1
  docker volume rm "$name" >/dev/null
}
compiler_cleanup() {
  local rc="$1" failure=0 code=""
  ((execution_rc == 0)) || rc="$execution_rc"
  set +e
  trap - EXIT
  trap '' INT TERM
  if [[ -n "$worker" ]]; then
    kill -TERM -- "-$worker" 2>/dev/null || true
    local stop=$((SECONDS + 30))
    while kill -0 -- "-$worker" 2>/dev/null && ((SECONDS < stop)); do sleep 1; done
    kill -KILL -- "-$worker" 2>/dev/null || true
    wait "$worker" || true
    kill -0 -- "-$worker" 2>/dev/null && failure=1
  fi
  capture_compiler_build || failure=1
  release_compiler_workload || failure=1
  remove_compiler_container "$runner" || failure=1
  if [[ -n "$rid" ]]; then
    TOKEN="$(app_token)" && code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 -X DELETE \
      -H @- -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' \
      "https://api.github.com/orgs/ray-manaloto/actions/runners/$rid" <<<"Authorization: Bearer $TOKEN")"
    [[ "$code" == 204 || "$code" == 404 ]] || failure=1
  fi
  rm -rf -- "$source" "$state/transfer" "$state/seed-source" "$state/oci" "$state/publish" || failure=1
  printf 'phase=%s exit=%s cleanup=%s completed=%s\n' "$phase" "$rc" "$failure" "$(date -u +%FT%TZ)" >"$state/closeout"
  printf 'CPP compiler run %s runner %s (%s): phase %s; receipts %s; cleanup %s\n' \
    "$run" "$runner" "${rid:-unregistered}" "$phase" "$result" "$failure"
  ((rc != 0 || failure == 0)) || exit 1
  exit "$rc"
}
finish_compiler_workload() {
  phase=teardown
  local cleanup_rc=0 checklist=not_run
  [[ ! -f "$result/checklist.txt" ]] || checklist=attempted
  capture_compiler_build || cleanup_rc=1
  release_compiler_workload >"$result/workload-cleanup.log" 2>&1 || cleanup_rc=1
  ((cleanup_rc == 0)) || status=FAIL
  phase=artifact
  jq -n --arg run "$run" --arg job "$job_id" --arg runner "$runner" --arg sha "$sha" --arg status "$status" \
    --argjson execution_exit "$execution_rc" --argjson cleanup_exit "$cleanup_rc" \
    --arg checklist "$checklist" --arg timing "$timing" --argjson pass "$passes" --argjson fail "$fails" --argjson na "$na" --argjson total "$total" \
    '{run:$run, job:$job, attempt:"1", runner:$runner, commit:$sha, status:$status, timing:$timing, pass:$pass,
      fail:$fail, na:$na, total:$total, checklist:$checklist, execution_exit:$execution_exit, cleanup_exit:$cleanup_exit}' >"$result/.final.json"
  chmod -R a+rX "$result"
  mv "$result/.final.json" "$result/final.json"
}

supervise_compiler() {
  trap 'compiler_cleanup "$?"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  git --git-dir="$git_dir" archive "$sha" | tar -C "$source" -xf -
  base_ref="$(sed -nE 's/^image = "(ubuntu:26\.10@sha256:[a-f0-9]{64})"$/\1/p' "$source/image/base.inputs.toml")"
  [[ "$base_ref" =~ ^ubuntu:26\.10@sha256:[a-f0-9]{64}$ ]] || die 'Ubuntu base pin missing'
  base_digest="${base_ref#*@}"
  # A pull is limited to the exact base index. The compatible addon donor is a
  # retained image by full ID, and is never used as a pre-provisioned base.
  [[ "$(docker image inspect -f '{{.Os}}/{{.Architecture}} {{index .Config.Labels "org.opencontainers.image.base.digest"}}' "$donor")" == "linux/amd64 $base_digest" ]] || die 'retained addon donor missing or no longer matches the pinned base'
  timeout --kill-after=10s 300s docker pull --platform linux/amd64 "$base_ref" >"$result/base.log" 2>&1
  base_id="$(docker image inspect -f '{{.Id}}' "$base_ref")"
  [[ "$(docker image inspect -f '{{.Os}}/{{.Architecture}}' "$base_id")" == linux/amd64 ]] ||
    die 'base image platform mismatch'

  # Require only the reviewed, CPP-specific job waiting for registration.
  runner_job() {
    api GET "/repos/$repo/actions/runs/$run/attempts/1/jobs" | jq -ce --arg sha "$sha" '
      if .total_count==1 and (.jobs|length)==1 and .jobs[0].head_sha==$sha and
          .jobs[0].name=="Build and certify Ubuntu amd64" then .jobs[0]
      else error("unexpected job inventory") end'
  }
  job="$(runner_job)"
  jq -e '.status=="queued" and (.runner_id==null or .runner_id==0)' <<<"$job" >/dev/null ||
    die 'another runner already owns this job or it is not queued'
  job_id="$(jq -er .id <<<"$job")"
  # The candidate-specific RO tools mount is empty. All build-time tool
  # installations and the persistent object cache are inaccessible to the listener.
  install -d -m 0555 "$state/tools"
  phase=registration
  resp="$(api POST /orgs/ray-manaloto/actions/runners/generate-jitconfig "$(jq -nc --arg n "$runner" '
    {name:$n, runner_group_id:6, labels:["self-hosted","pc-x86","container","cpp-standard","compiler"], work_folder:"_work"}')")"
  rid="$(jq -er '.runner.id | select(type=="number" and .>0)' <<<"$resp")"
  jit="$(jq -er '.encoded_jit_config | strings | select(length>0)' <<<"$resp")"
  unset resp
  image_ref="$(docker image inspect -f '{{.Id}}' "$runner_img")"
  local -a hardening=(--cap-drop ALL --security-opt no-new-privileges --pids-limit 32768)
  ACTIONS_RUNNER_INPUT_JITCONFIG="$jit" docker run -d --name "$runner" \
    --label "org.cpp-standard.compiler=$owner_name" --network "$NET" --dns 1.1.1.1 --dns 9.9.9.9 \
    --user 1001:1001 "${hardening[@]}" --cpus 2 --memory 2g --memory-swap 2g \
    --mount "type=bind,src=$hooked,dst=/etc/gha-cpp-compiler-admission.sh,readonly" \
    --mount "type=bind,src=$result,dst=/cpp-result,readonly" \
    --mount "type=bind,src=$state/publish,dst=/cpp-package,readonly" \
    --mount "type=bind,src=$state/tools,dst=/cache/mise,readonly" \
    -e ACTIONS_RUNNER_INPUT_JITCONFIG -e GHA_SLOT=cpp-standard -e SCCACHE_DIR=/tmp/gha-cpp-sccache \
    -e "CPP_EXPECTED_RUN=$run" -e "CPP_EXPECTED_SHA=$sha" \
    -e ACTIONS_RUNNER_HOOK_JOB_STARTED=/etc/gha-cpp-compiler-admission.sh \
    --log-driver local --entrypoint ./run.sh "$image_ref" >"$state/runner.cid"
  unset jit
  phase=assignment
  assigned() {
    jq -e --argjson job "$job_id" --argjson rid "$rid" --arg n "$runner" '
      .id==$job and .runner_id==$rid and .runner_name==$n and .status=="in_progress" and
      any(.steps[]?; .name=="Verify admitted runner and isolated mounts" and .conclusion=="success") and
      any(.steps[]?; .name=="Wait for compiler result" and .status=="in_progress")
    ' >/dev/null
  }
  slot=$((SECONDS + 300))
  while ! runner_job | assigned; do
    ((SECONDS < slot)) || die 'exact job did not reach the admitted wait step'
    sleep 5
  done
  jq -n --arg run "$run" --arg job "$job_id" --arg rid "$rid" --arg runner "$runner" --arg sha "$sha" \
    --arg base "$base_id" --arg digest "$base_digest" --arg donor "$donor" --arg began "$began" \
    '{run:$run, job:$job, runner_id:$rid, runner:$runner, commit:$sha, base:$base, base_digest:$digest, addon_donor:$donor, started:$began}' \
    >"$result/assignment.json"
  printf 'START https://github.com/%s/actions/runs/%s/job/%s runner=%s id=%s\n' "$repo" "$run" "$job_id" "$runner" "$rid"

  run_compiler_phases() {
    set -euo pipefail
    docker volume create --label "org.cpp-standard.compiler=$owner_name" "$work_volume" >/dev/null
    docker volume create --label "org.cpp-standard.compiler=$owner_name" "$cert_volume" >/dev/null
    docker create --platform linux/amd64 --name "$donor_name" --network none --privileged=false \
      --label "org.cpp-standard.compiler=$owner_name" "$donor" >/dev/null
    docker create --platform linux/amd64 --name "$build" --init --privileged=false \
      --label "org.cpp-standard.compiler=$owner_name" --network "$NET" --dns 1.1.1.1 --dns 9.9.9.9 \
      --cpus 16 --memory 48g --memory-swap 48g --pids-limit 32768 --security-opt no-new-privileges \
      -e "CPP_BASE_ID=$base_id" -e "CPP_DONOR_ID=$donor" \
      -e container=docker -e MISE_GLOBAL_CONFIG_FILE=/opt/cpp-standard-tools/mise.toml \
      -e "PATH=/root/.local/share/mise/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
      --mount "type=bind,src=$source,dst=/project,readonly" \
      --mount "type=bind,src=$compiler_store/apt-archives,dst=/cache/apt-archives" \
      --mount "type=bind,src=$compiler_store/packages,dst=/cache/compiler,readonly" \
      --mount "type=bind,src=$transfer,dst=/run/cpp-compiler-transfer" \
      --mount "type=bind,src=$compiler_store/mise-downloads,dst=/root/.cache/mise/downloads-cas" \
      --mount "type=bind,src=$compiler_store/mise-release,dst=/cache/mise-release" \
      --mount "type=bind,src=$compiler_store/uv,dst=/cache/uv" \
      --mount "type=bind,src=$compiler_store/sccache,dst=/cache/sccache" \
      --mount "type=volume,src=$work_volume,dst=/work" --workdir /root --log-driver local --entrypoint /bin/bash \
      "$base_id" /project/docs/standard/gha-runner/pc-compiler-bootstrap.sh >"$state/build.cid"
    seed_compiler_ca
    for path in cuda-12.9 cuda-13.2 llvm-23.1.6 llvm23-offload iwyu-llvm23; do
      docker cp "$donor_name:/opt/$path" - | docker cp - "$build:/opt/"
    done
    remove_compiler_container "$donor_name"
    docker start "$build" >/dev/null
    # shellcheck source=docs/standard/gha-runner/pc-compiler-store.sh
    source "$source/docs/standard/gha-runner/pc-compiler-store.sh"
    resolve_compiler_package
    wait_compiler_build "$build"
    retain_compiler_package
    capture_compiler_build
    [[ "$(docker inspect -f '{{.State.Status}}' "$build")" == exited ]]
    docker commit --change 'ENTRYPOINT ["/usr/bin/env"]' --change "LABEL org.opencontainers.image.base.digest=$base_digest" \
      --change "LABEL org.cpp-standard.compiler=$owner_name" "$build" >"$state/compiled-image"
    local candidate
    candidate="$(cat "$state/compiled-image")"
    [[ "$candidate" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    printf '%s\n' "$candidate" >"$result/built-image"
    remove_compiler_container "$build"
    # No build quota, swap quota, CPU affinity or toolchain mount is inherited.
    # --ab enables the pinned V6 comparison. Routine Actions accept a complete
    # busy window or excess overhead as advisory. The driver still fails on
    # incomplete evidence and required functional checks (including V1/V3).
    timeout --kill-after=30s 35m env -i PATH="$PATH" HOME=/root TMPDIR="$state" \
      MISE_AUTO_INSTALL=0 CERT_CPP_ACTIONS_HOST=1 CERT_CPP_TIMING_ADVISORY=1 "CERT_CPP_SOURCE=$source" \
      "CERT_CPP_CONTAINER=$check" "CERT_CPP_EVIDENCE=$result" \
      "usage_image=$candidate" usage_ab=true usage_name=nzxth1desktop \
      "CERT_CPP_OWNER=$owner_name" bash "$source/.mise/tasks/certify/ubuntu" >"$result/checklist.txt" 2>"$result/checklist.stderr"
    check_compiler_rows "$(<"$result/timing-verdict.txt")"
    certify_compiler_project "$candidate"
  }
  phase=compile-and-certify
  # Reset errexit context in the child (an if/while caller would mask failures).
  set -m
  run_compiler_phases >"$result/worker.log" 2>&1 &
  worker=$!
  set +m
  local monitor_ok=1
  while kill -0 "$worker" 2>/dev/null; do
    refresh_compiler_token
    if ((SECONDS >= deadline)) || ! runner_job | assigned; then
      monitor_ok=0
      break
    fi
    sleep 15
  done
  if ((monitor_ok == 1)); then
    wait "$worker" || execution_rc=$?
    worker=''
  else
    die 'workflow ended, lost assignment, or passed its host deadline'
  fi
  if [[ -s "$result/timing-verdict.txt" ]]; then
    timing="$(<"$result/timing-verdict.txt")"
  fi
  if [[ -s "$result/body.txt" ]]; then
    read -r passes fails na total < <(awk '
      $2=="PASS" {pass++} $2=="FAIL" {fail++} $2=="N/A" {na++}
      END {print pass+0,fail+0,na+0,NR}
    ' "$result/body.txt")
    if ((execution_rc == 0)) && [[ -s "$result/timing-verdict.txt" ]]; then
      status=PASS
    fi
  fi

  # Finish the build/checklist cleanup before waking the upload step, so a
  # green job cannot conceal leaked workload resources.
  if [[ "$status" == PASS ]]; then
    local tag="cpp-standard-qualified:run-$run" image
    image="$(cat "$state/compiled-image")"
    [[ "$(docker image inspect -f '{{.Id}}' "$tag")" == "$image" ]]
    # Transfer the verified image out of transient cleanup ownership. Keep a
    # durable ID and the launch reference next to the uploaded project results.
    printf 'tag=%s\nid=%s\ncheckout=%s\n' "$tag" "$image" "$sha" >"$result/retained-image.txt"
    mv "$state/compiled-image" "$state/retained-image"
  fi
  finish_compiler_workload
  phase=actions-finalize
  slot=$((SECONDS + 600))
  if [[ -s "$state/publish/tag" ]]; then slot=$((SECONDS + 1800)); fi
  while ((SECONDS < slot)); do
    refresh_compiler_token
    live="$(runner_job)" || die 'could not verify the completed Actions job'
    if [[ "$(jq -r .status <<<"$live")" == completed ]]; then
      printf '%s\n' "$live" | jq '{id,run_id,head_sha,status,conclusion,html_url,runner_id,runner_name}' >"$state/github-job.json"
      if [[ "$status" == PASS ]] &&
        jq -e --argjson rid "$rid" '.runner_id==$rid and .conclusion=="success"' <<<"$live" >/dev/null; then
        compiler_cleanup 0
      else
        compiler_cleanup 1
      fi
    fi
    sleep 10
  done
  die 'Actions did not finalize after the evidence was delivered'
}
