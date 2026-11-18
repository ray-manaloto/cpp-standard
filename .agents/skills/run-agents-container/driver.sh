#!/usr/bin/env bash
# Driver for the cpp-standard agent container on the PC: build the image, start a project's container with
# the flags agents:up sets, run the checks inside, remove it. Run from the repository root.
#
#   driver.sh build                 build docs/standard/agents.Dockerfile on the PC as $TAG
#   driver.sh up <project>          mise run agents:up <project> --host pc --image $TAG
#   driver.sh check <project>       the checks: flags and mounts from the host, tools and logins inside
#   driver.sh down <project>        remove the container, its six volumes and its agent-secrets registration
#   driver.sh all <project>         build, up, check, down
#
# TAG defaults to cpp-standard-agents:runskill, a throwaway tag: the live containers use :dev.
# up and down refuse a project whose container does not run $TAG, so they cannot touch a live project container.
# all always runs down, also after a failed check, and exits with the check's status.
# RM_CLONE=1 also removes the PC clone ~/dev/containers/<project> when it has no local changes or commits.
# RM_IMAGE=1 also removes $TAG.
# ORPHANS=1 lets down remove the volumes and the registration when the container is already gone.
set -euo pipefail
TAG="${TAG:-cpp-standard-agents:runskill}"
# shellcheck disable=SC2032,SC2033 # the pc inside the function is the ssh host alias, not this function
pc() { ssh -o BatchMode=yes pc "$@"; }
die() {
  printf 'driver: %s\n' "$*" >&2
  exit 1
}
name_of() {
  [[ "${1:-}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || die "project name needed"
  printf '%s-agents' "$1"
}

build() { mise run agents:image --host pc --tag "$TAG"; }

# Sets image to what <name> runs, or to "" when there is no such container.
image_of() { image="$(pc docker inspect -f "'{{.Config.Image}}'" "$1" 2>/dev/null)" || image=""; }

# A project that already has a container on another image, or a registration with no container, is live or
# someone else's: agents:up would restart or recreate it, so stop before it runs.
mine_or_new() {
  local name image
  name="$(name_of "$1")"
  image_of "$name"
  if [[ -n "$image" ]]; then
    [[ "$image" == "$TAG" ]] || die "$name runs $image, not $TAG: not mine to touch"
  elif pc "test -e .local/state/agent-secrets/$name"; then
    die "$name is registered with agent-secrets but has no container: not mine to touch"
  fi
}

up() {
  mine_or_new "$1"
  mise run agents:up "$1" --host pc --image "$TAG"
}

check() {
  local name fails=0 got
  name="$(name_of "$1")"
  ok() { printf 'ok    %s\n' "$1"; }
  bad() {
    printf 'FAIL  %s: %s\n' "$1" "$2"
    fails=$((fails + 1))
  }
  want() { # want <label> <expected> <docker inspect format>
    got="$(pc docker inspect -f "'$3'" "$name")"
    if [[ "$got" == "$2" ]]; then ok "$1 = $2"; else bad "$1" "want $2, got $got"; fi
  }
  want running true '{{.State.Running}}'
  want image "$TAG" '{{.Config.Image}}'
  want privileged false '{{.HostConfig.Privileged}}'
  want cap-add '[]' '{{.HostConfig.CapAdd}}'
  want restart unless-stopped '{{.HostConfig.RestartPolicy.Name}}'
  want user dev '{{.Config.User}}'
  want hostname "$name" '{{.Config.Hostname}}'
  got="$(pc docker inspect -f "'{{range .Config.Env}}{{println .}}{{end}}'" "$name")"
  if grep -qx 'container=docker' <<<"$got"; then ok 'env container=docker'; else bad env 'no container=docker'; fi
  got="$(pc docker inspect -f "'{{range .Mounts}}{{.Type}} {{.Destination}} rw={{.RW}}{{println}}{{end}}'" "$name")"
  for m in 'bind /workspace rw=true' 'bind /run/agent-secrets rw=false' 'volume /home/dev/.claude rw=true' \
    'volume /home/dev/.codex rw=true' 'volume /home/dev/.gemini rw=true' \
    'volume /home/dev/.local/share/opencode rw=true' 'volume /home/dev/.config/opencode rw=true' \
    'volume /home/dev/.local/state/opencode rw=true'; do
    if grep -qx "$m" <<<"$got"; then ok "mount $m"; else bad mount "missing: $m"; fi
  done
  # Inside the container, as a login shell. The script goes in on stdin, so nothing needs quoting twice.
  # It never prints a file under /run/agent-secrets and never starts agy.
  if pc docker exec -i "$name" bash -l -s <<'INSIDE'
f=0
ok() { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; f=1; }
t() { local label="$1"; shift; if out="$("$@" 2>&1)"; then ok "$label: $(head -1 <<<"$out")"; else bad "$label: $(tail -1 <<<"$out")"; fi; }
[[ "$(id -un)" == dev ]] && ok 'whoami = dev' || bad "whoami = $(id -un)"
[[ "${container:-}" == docker ]] && ok 'container=docker in the shell' || bad 'container variable'
[[ "$PWD" == /workspace ]] && ok 'cwd = /workspace' || bad "cwd = $PWD"
t 'workspace origin' git -C /workspace remote get-url origin
t 'workspace head' git -C /workspace log -1 --format=%h\ %s
for s in gh-token git-identity claude-oauth-token; do
  [[ -s /run/agent-secrets/$s ]] && ok "secret file present: $s" || bad "secret file missing: $s"
done
if touch /run/agent-secrets/probe 2>/dev/null; then bad '/run/agent-secrets is writable'; else ok '/run/agent-secrets is read-only'; fi
t 'git user.name' git config --global user.name
t 'git user.email' git config --global user.email
t 'git reads origin with the App token' git -C /workspace ls-remote origin HEAD
# gh is a mise shim: inside /workspace it fails until the project's own tools are installed (mise install),
# so the login is checked from $HOME, and the missing tools are listed without failing the run.
slug="$(git -C /workspace remote get-url origin | sed -E 's#^https://github.com/##; s#\.git$##')"
t 'gh as the App' bash -c "cd \"\$HOME\" && gh repo view $slug --json nameWithOwner -q .nameWithOwner"
missing="$(mise ls --missing 2>/dev/null | awk '{print $1}' | paste -sd' ' -)"
[[ -z "$missing" ]] && ok 'workspace tools installed' || printf 'note  workspace tools not installed yet (mise install): %s\n' "$missing"
t 'claude' claude --version
t 'codex' codex --version
t 'opencode' opencode --version
t 'mise' mise --version
t 'agent versions file' cat "$HOME/.agent-versions"
exit $f
INSIDE
  then :; else fails=$((fails + 1)); fi
  if ((fails)); then die "$fails check group(s) failed"; fi
  printf 'driver: all checks passed for %s\n' "$name"
}

down() {
  local name image left
  name="$(name_of "$1")"
  image_of "$name"
  if [[ -n "$image" ]]; then
    [[ "$image" == "$TAG" ]] || die "$name runs $image, not $TAG: not mine to remove"
    pc docker rm -f "$name"
  elif [[ "${ORPHANS:-}" != 1 ]]; then
    die "no container $name: nothing removed (ORPHANS=1 removes its volumes and registration anyway)"
  fi
  for v in claude codex gemini opencode-data opencode-config opencode-state; do
    pc docker volume rm -f "$name-$v"
  done
  pc .local/bin/agent-secrets unregister "$name"
  if [[ "${RM_CLONE:-}" == 1 ]]; then
    pc "cd dev/containers/$1 && test -z \"\$(git status --porcelain)\" && test -z \"\$(git log --branches --not --remotes --oneline)\" && cd .. && rm -rf $1" ||
      die "the PC clone dev/containers/$1 has local work; left in place"
  fi
  if [[ "${RM_IMAGE:-}" == 1 ]]; then pc docker rmi "$TAG"; fi
  left="$(pc "docker ps -a --format '{{.Names}}' | grep -cx $name; docker volume ls -q | grep -c '^$name-'; ls .local/state/agent-secrets | grep -cx $name" | paste -sd' ' - || true)"
  printf 'driver: left on the PC for %s: %s (container, volumes, registration)\n' "$name" "$left"
  [[ "$left" == '0 0 0' ]] || die "removal is not complete for $name"
}

cmd="${1:-}"
shift || true
case "$cmd" in
  build) build ;;
  up | check | down)
    name_of "${1:-}" >/dev/null
    "$cmd" "$1"
    ;;
  all)
    name_of "${1:-}" >/dev/null
    mine_or_new "$1"
    build
    rc=0
    # check runs in a subshell so its exit does not skip down. After mine_or_new passed, whatever a failed
    # up left behind is this run's, so down may remove it without a container.
    if up "$1"; then (check "$1") || rc=$?; else
      rc=$?
      export ORPHANS=1
    fi
    down "$1"
    exit "$rc"
    ;;
  *)
    sed -n '2,16p' "$0"
    exit 2
    ;;
esac
