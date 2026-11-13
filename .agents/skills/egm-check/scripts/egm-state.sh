#!/usr/bin/env bash
# Gather the facts egm-check needs, as plain "key: value" lines and short
# lists. It reads the repository only; it never writes. Run from anywhere
# inside the repository:
#
#   egm-state.sh [design_dir] [artifact_dir]
#
# design_dir defaults to docs/designs. artifact_dir defaults to the path on
# an "EGM artifact directory: <path>" line in AGENTS.md or CLAUDE.md, else
# the first (alphabetical) design subdirectory holding *_report.md files.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"
design_dir="${1:-docs/designs}"
if [[ ! -d "$design_dir" ]]; then
  echo "egm-state: design dir '$design_dir' not found under $root" >&2
  exit 2
fi

artifact_dir="${2:-}"
artifact_line_found=no
for f in AGENTS.md CLAUDE.md; do
  [[ -f "$f" ]] || continue
  line="$(grep -m1 -E '^EGM artifact directory: ' "$f" || true)"
  if [[ -n "$line" ]]; then
    artifact_line_found="yes ($f)"
    [[ -n "$artifact_dir" ]] || artifact_dir="${line#EGM artifact directory: }"
  fi
done
if [[ -z "$artifact_dir" ]]; then
  artifact_dir="$(find "$design_dir" -name '*_report.md' -exec dirname {} \; 2>/dev/null | sort -u | head -1)"
fi

last_commit() { git log -1 --format='%cs %h' -- "$1" 2>/dev/null || true; }
status_line() { grep -m1 -E '^([-*] +)?\**Status:?\**' "$1" 2>/dev/null | sed -E -e 's/^[-* ]+//' -e 's/[*]//g' | head -c 120 || true; }

echo "== setup"
echo "repo: $root"
echo "today: $(date -u +%Y-%m-%d)"
echo "head: $(git log -1 --format='%cs %h %s')"
echo "design_dir: $design_dir"
echo "artifact_dir: ${artifact_dir:-<none found>}"
echo "artifact_dir_line_in_agent_docs: $artifact_line_found"

echo
echo "== design docs (docs in design_dir, top level)"
sitemap="$design_dir/SITEMAP.md"
for d in "$design_dir"/*.md; do
  [[ -e "$d" ]] || continue
  b="$(basename "$d")"
  [[ "$b" == SITEMAP.md ]] && continue
  in_sitemap=no
  [[ -f "$sitemap" ]] && grep -qF "$b" "$sitemap" && in_sitemap=yes
  echo "- $d | last commit: $(last_commit "$d") | lines: $(wc -l <"$d" | tr -d ' ') | in SITEMAP: $in_sitemap | $(status_line "$d")"
done
[[ -f "$sitemap" ]] && echo "sitemap: $sitemap, last commit $(last_commit "$sitemap")" || echo "sitemap: missing"

echo
echo "== EGM artifacts in artifact_dir"
if [[ -n "${artifact_dir:-}" && -d "$artifact_dir" ]]; then
  for a in concepts_brief.md design_draft.md zoom_out_report.md comprehension_report.md \
    critic_report.md intermediate_zoom_out_report.md implementation_readiness_report.md \
    consolidated_review_report.md goldfish_review_report.md; do
    p="$artifact_dir/$a"
    if [[ -f "$p" ]]; then
      echo "- $a: present | last commit: $(last_commit "$p") | lines: $(wc -l <"$p" | tr -d ' ') | $(status_line "$p")"
    else
      echo "- $a: MISSING"
    fi
  done
  others="$(find "$artifact_dir" -maxdepth 1 -name '*_report.md' | sort)"
  echo "all report files:"
  printf '%s\n' "${others:-(none)}" | sed 's/^/  /'
fi

echo
echo "== decisions"
log="$(find "$design_dir" -name 'decisions-log.md' | head -1)"
if [[ -n "$log" ]]; then
  # tr, not a second grep: grep exits 1 on empty input and pipefail would stop the script.
  max_d="$({ grep -oE '^\| D[0-9]+ ' "$log" || true; } | tr -dc '0-9\n' | sort -n | tail -1)"
  echo "decisions_log: $log | last commit: $(last_commit "$log") | highest decision: D${max_d:-?}"
  reviewed=0
  if [[ -n "${artifact_dir:-}" && -d "$artifact_dir" ]]; then
    reviewed="$({ cat "$artifact_dir"/*_report.md 2>/dev/null || true; } | { grep -oE '(^|[^A-Za-z0-9_])D[0-9]+' || true; } | tr -dc '0-9\n' | sort -n | tail -1)"
  fi
  reviewed=$((10#${reviewed:-0}))
  echo "highest decision cited by any review report: D$reviewed"
  if [[ -n "${max_d:-}" ]] && ((reviewed < 10#$max_d)); then
    echo "decisions_never_reviewed: D$((reviewed + 1))..D$((10#$max_d))"
  fi
else
  echo "decisions_log: none found"
fi

echo
echo "== changes since the last review artifact was committed"
since_ref="$(git log -1 --format=%H -- "${artifact_dir:-$design_dir}"/*_report.md 2>/dev/null || true)"
if [[ -n "$since_ref" ]]; then
  echo "last_review_commit: $(git log -1 --format='%cs %h %s' "$since_ref")"
  echo "commits since:"
  git log --format='  %cs %h %s' "$since_ref"..HEAD
  echo "paths outside design_dir changed since:"
  git diff --name-only "$since_ref" HEAD -- . ":(exclude)$design_dir" | sed 's/^/  /'
  echo "design docs changed since:"
  git diff --stat "$since_ref" HEAD -- "$design_dir"/*.md | tail -20 | sed 's/^/  /'
else
  echo "last_review_commit: none (no review report committed)"
fi

echo
echo "== drift reports"
drift="$(git ls-files | { grep -E '_DRIFT_REPORT\.md$' || true; } | sort | tail -1)"
if [[ -n "$drift" ]]; then
  echo "latest: $drift ($(last_commit "$drift"))"
  echo "commits since it: $(git rev-list --count "$(git log -1 --format=%H -- "$drift")"..HEAD)"
else
  echo "latest: none ever"
fi

echo
echo "== bootstrap contracts (egm-bootstrap, optional)"
echo "code-bearing directories without README.md or EGM.md:"
git ls-files | { grep -E '\.(sh|bash|py|cpp|cc|cxx|hpp|h|cmake|pkl|ya?ml|toml)$|^\.mise/tasks/' || true; } |
  { grep -v -E "^$design_dir/|/\.mise/locks/" || true; } |
  while IFS= read -r f; do dirname "$f"; done | sort -u |
  while read -r dir; do
    [[ -f "$dir/README.md" || -f "$dir/EGM.md" ]] || echo "  $dir"
  done

echo
echo "== open branches and worktrees"
git worktree list | sed 's/^/  /'
echo "unmerged remote branches touching the design dir:"
git for-each-ref --format='%(refname:short)' refs/remotes/origin |
  { grep -vE 'origin/(HEAD|main)$' || true; } |
  while read -r br; do
    git merge-base --is-ancestor "$br" HEAD 2>/dev/null && continue
    # Design files the branch changed since it forked from HEAD.
    touched=()
    while IFS= read -r p; do touched+=("$p"); done < <(git diff --name-only HEAD..."$br" -- "$design_dir" 2>/dev/null || true)
    ((${#touched[@]})) || continue
    # A squash-merged branch has the same content as HEAD there: skip it.
    git diff --quiet HEAD "$br" -- "${touched[@]}" 2>/dev/null && continue
    echo "  $br"
  done
