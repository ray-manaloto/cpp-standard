#!/usr/bin/env bash
# agent-secrets (cpp-standard D155): the PC side of zero-touch logins for project agent containers.
#
#   agent-secrets register <container> <owner/repo>   start serving a container and print its folder (agents:up)
#   agent-secrets unregister <container>              stop serving it and remove its files
#   agent-secrets refresh [<container>]               write the files now (all containers, or one)
#   agent-secrets guard <container> [--allow-unprotected]   decide and write its guard-mode (protected or client),
#                                                     or exit 3 for a public repository without rules (see guard)
#   agent-secrets serve                               the user service: refresh whatever is due, every 15 s
#
# Each container gets ~/.local/state/agent-secrets/<container>/ (0700), mounted read-only at /run/agent-secrets:
#   gh-token              a GitHub App installation token for <owner/repo> only, contents and pull requests
#                         write; GitHub makes it expire after one hour, and it is replaced after 30 minutes
#   claude-oauth-token    CLAUDE_CODE_OAUTH_TOKEN (the Antigravity CLI and Codex log in per container instead)
#   git-identity          the App bot's commit name and noreply email (not secret)
#   guard-mode            protected or client, written by `guard` (read by the image's gh wrapper)
# Every file is written to a temporary name in the same folder and renamed over the old one, so a reader in the
# container sees the old file or the new one, never half of one. The folder is on disk, not in /run/user: Docker
# restarts containers at boot, before the user manager could recreate a /run/user folder, and a missing bind-mount
# source fails the start.
#
# The secrets come from Doppler with the read-only service token in ~/.config/agent-secrets/doppler-token (0600;
# a token for Doppler project agent-containers, config prd, which holds only AGENTS_APP_PRIVATE_KEY,
# AGENTS_APP_CLIENT_ID and CLAUDE_CODE_OAUTH_TOKEN, plus an unused GEMINI_API_KEY; agents:pc-doppler puts it there).
# No secret is ever an argument (ps shows those) or printed: they pass in variables, pipes and /dev/fd.
# The JWT is the same openssl RS256 signing the runner launcher (gha-slot) uses for its App.
set -euo pipefail
umask 077
state="${AGENT_SECRETS_STATE:-$HOME/.local/state/agent-secrets}"
conf="${AGENT_SECRETS_CONF:-$HOME/.config/agent-secrets}"
api="https://api.github.com"
max_age=1800

log() { printf 'agent-secrets: %s\n' "$*" >&2; }
die() {
  log "$*"
  exit 1
}
b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

# The secrets JSON of the token's Doppler config. mise puts the pinned doppler CLI on PATH (mise.pc.toml [tools]).
secrets_json() {
  [[ -r "$conf/doppler-token" ]] || die "no Doppler token at $conf/doppler-token"
  DOPPLER_TOKEN="$(<"$conf/doppler-token")" mise exec doppler -- doppler secrets download --no-file --format json \
    --no-check-version
}

# GitHub REST call with a bearer token taken from the variable named by $1 (never from argv).
gh_api() { # <token var> <method> <path> [body on stdin]
  # A unique name: a nameref named like its target is circular.
  local -n _gh_api_tok="$1"
  curl -fsS --max-time 20 -X "$2" -H @<(printf 'Authorization: Bearer %s\n' "$_gh_api_tok") \
    -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" \
    ${STDIN_BODY:+--data-binary @-} "$api$3"
}

# A 9-minute App JWT; the issuer may be the App's client ID (GitHub's JWT docs).
app_jwt() { # <client id> <pem var>
  local -n _app_jwt_pem="$2"
  local now hdr pay sig
  now=$(date +%s)
  hdr=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  pay=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$1" | b64url)
  sig=$(printf '%s.%s' "$hdr" "$pay" | openssl dgst -sha256 -sign <(printf '%s\n' "$_app_jwt_pem") | b64url)
  printf '%s.%s.%s' "$hdr" "$pay" "$sig"
}

# Atomic write of stdin to <dir>/<name>, mode 0600.
put() { # <dir> <name>
  local tmp
  tmp=$(mktemp "$1/.$2.XXXXXX") || return 1
  # Explicit checks: set -e is off where callers test this function. A failed write never replaces the file.
  if ! cat >"$tmp"; then
    rm -f -- "$tmp"
    return 1
  fi
  mv -f "$tmp" "$1/$2"
}

due() { # <dir>: whether its files need writing
  local f="$1/gh-token"
  [[ ! -s "$f" ]] || (($(date +%s) - $(stat -c %Y "$f") > max_age)) || [[ ! -s "$1/claude-oauth-token" ]]
}

# Write the files of the given container folders, with one Doppler read for all of them.
refresh_dirs() { # <dir>...
  (($#)) || return 0
  local json pem client claude jwt d repo owner name inst body tok slug uid
  json=$(secrets_json) || die "the Doppler read failed"
  # shellcheck disable=SC2034 # app_jwt reads it by name
  pem=$(jq -er .AGENTS_APP_PRIVATE_KEY <<<"$json") || die "Doppler has no AGENTS_APP_PRIVATE_KEY"
  client=$(jq -er .AGENTS_APP_CLIENT_ID <<<"$json") || die "Doppler has no AGENTS_APP_CLIENT_ID"
  # Every value is read and checked before any file is written: jq prints "null" for a missing name.
  claude=$(jq -er .CLAUDE_CODE_OAUTH_TOKEN <<<"$json") || die "Doppler has no CLAUDE_CODE_OAUTH_TOKEN"
  # shellcheck disable=SC2034 # gh_api reads it by name
  jwt=$(app_jwt "$client" pem)
  slug=$(gh_api jwt GET /app | jq -er .slug) || die "GET /app failed: is the App key current?"
  uid=$(curl -fsS --max-time 20 "$api/users/${slug}%5Bbot%5D" | jq -er .id) || die "cannot read ${slug}[bot]'s id"
  for d in "$@"; do
    repo=$(<"$d/repo")
    owner=${repo%%/*} name=${repo#*/}
    if ! inst=$(gh_api jwt GET "/repos/$owner/$name/installation" | jq -er .id); then
      log "$(basename "$d"): the App is not installed on $repo; skipped"
      continue
    fi
    body=$(jq -nc --arg r "$name" '{repositories: [$r], permissions: {contents: "write", pull_requests: "write"}}')
    if ! tok=$(STDIN_BODY=1 gh_api jwt POST "/app/installations/$inst/access_tokens" <<<"$body" | jq -er .token) ||
      [[ "$tok" != ghs_* ]]; then
      log "$(basename "$d"): minting a token for $repo failed; skipped"
      continue
    fi
    printf '%s' "$tok" | put "$d" gh-token
    printf '%s' "$claude" | put "$d" claude-oauth-token
    rm -f -- "$d/gemini-api-key" # written before D155 dropped the Gemini key
    printf '%s[bot]\n%s+%s[bot]@users.noreply.github.com\n' "$slug" "$uid" "$slug" | put "$d" git-identity
    log "$(basename "$d"): wrote a token for $repo"
  done
}

# One writer at a time: register, unregister, refresh and each serve round hold this lock, so a round in flight
# cannot publish a token for a binding that register is changing.
lock() {
  mkdir -p "$state"
  exec 9>"$state/.lock"
  flock 9
}

valid_name() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "bad container name: $1"; }

case "${1:-}" in
  register)
    [[ $# -eq 3 ]] || die "usage: agent-secrets register <container> <owner/repo>"
    valid_name "$2"
    [[ "$3" =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]] || die "bad repository: $3"
    lock
    # A binding never changes while it exists: the container's checkout would get a token for another repository.
    if [[ -s "$state/$2/repo" && "$(<"$state/$2/repo")" != "$3" ]]; then
      die "$2 is registered for $(<"$state/$2/repo"); remove the container and run unregister first"
    fi
    mkdir -p "$state/$2" # 0700 by the umask
    chmod 700 "$state" "$state/$2"
    printf '%s\n' "$3" | put "$state/$2" repo
    refresh_dirs "$state/$2"
    [[ -s "$state/$2/gh-token" ]] || die "no token was written for $2"
    printf '%s\n' "$state/$2" # the folder to mount, for agents:up
    ;;
  unregister)
    [[ $# -eq 2 ]] || die "usage: agent-secrets unregister <container>"
    valid_name "$2"
    lock
    rm -rf -- "${state:?}/$2"
    ;;
  guard)
    # The App may write contents on every repository, so a container gets a token only where pushes to the default
    # branch are refused. Writes the container's guard-mode file and prints one line:
    #   protected  a ruleset with a pull_request, merge_queue or update rule, or classic protection;
    #   client     a private repository that GitHub refuses rules on (403 "Upgrade to GitHub Pro": free plan), or
    #              a public one without rules when --allow-unprotected is given: the image's pre-push hook and gh
    #              wrapper refuse pushes to the default branch, force pushes and merges (D155, accepted risk).
    # Exit 3: a public repository without rules (agents:up offers --allow-unprotected). Any other failed read:
    # exit 1, fail closed. Every read needs only the App's metadata read permission.
    [[ $# -eq 2 || ($# -eq 3 && "$3" == --allow-unprotected) ]] ||
      die "usage: agent-secrets guard <container> [--allow-unprotected]"
    valid_name "$2"
    lock
    d="$state/$2"
    repo=$(<"$d/repo")
    # shellcheck disable=SC2034 # gh_api reads it by name
    tok=$(<"$d/gh-token")
    info=$(gh_api tok GET "/repos/$repo") || die "cannot read $repo"
    branch=$(jq -er .default_branch <<<"$info") || die "no default branch for $repo"
    private=$(jq -r .private <<<"$info")
    classic=$(gh_api tok GET "/repos/$repo/branches/$branch" | jq -er .protected) || die "cannot read $repo $branch"
    # Not gh_api: the body of a refusal says why.
    resp=$(curl -sS --max-time 20 -H @<(printf 'Authorization: Bearer %s\n' "$tok") \
      -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" \
      -w '\n%{http_code}' "$api/repos/$repo/rules/branches/$branch") || die "cannot reach GitHub for $repo's rules"
    code=${resp##*$'\n'} body=${resp%$'\n'*}
    mode=""
    if [[ "$code" == 200 ]]; then
      types=$(jq -r '.[].type' <<<"$body") || die "unreadable rules for $repo $branch"
      if grep -qxE 'pull_request|merge_queue|update' <<<"$types" || [[ "$classic" == true ]]; then
        mode=protected
        why="rules: $(tr '\n' ' ' <<<"$types")classic protection: $classic"
      elif [[ "$private" == false && $# -eq 3 ]]; then
        mode=client why="public, no rules, --allow-unprotected"
      elif [[ "$private" == false ]]; then
        log "$repo $branch is public and takes direct pushes (no pull_request, merge_queue or update rule)"
        exit 3
      fi
    elif [[ "$code" == 403 && "$private" == true ]] &&
      jq -e '.message | startswith("Upgrade to GitHub Pro")' <<<"$body" >/dev/null 2>&1; then
      mode=client why="private on a free plan: GitHub keeps rulesets for paid plans"
    fi
    [[ -n "$mode" ]] || die "cannot tell whether $repo $branch takes direct pushes (rules read: HTTP $code)"
    printf '%s\n' "$mode" | put "$d" guard-mode
    echo "agent-secrets: $repo $branch: $mode ($why)"
    ;;
  refresh)
    lock
    if [[ $# -eq 2 ]]; then
      valid_name "$2"
      refresh_dirs "$state/$2"
    else
      shopt -s nullglob
      dirs=("$state"/*/)
      refresh_dirs "${dirs[@]%/}"
    fi
    ;;
  serve)
    mkdir -p "$state"
    chmod 700 "$state"
    exec 9>"$state/.lock"
    shopt -s nullglob
    start=1 # the first round rewrites every folder: after a reboot a token may have expired
    while :; do
      flock 9 # the whole round, from choosing folders to writing them
      todo=()
      for d in "$state"/*/; do
        [[ -f "$d/repo" ]] && { ((start)) || due "${d%/}"; } && todo+=("${d%/}")
      done
      start=0
      # A failed round (Doppler or GitHub down) is logged and retried on the next tick.
      (refresh_dirs "${todo[@]}") || log "refresh failed; retrying in 15 s"
      flock -u 9
      sleep 15
    done
    ;;
  *) die "usage: agent-secrets register|unregister|refresh|serve (see the header of this script)" ;;
esac
