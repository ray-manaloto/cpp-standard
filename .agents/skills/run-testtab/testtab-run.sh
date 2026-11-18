#!/usr/bin/env bash
# Open one guarded live-test Claude tab with `mise run agents:testtab`, save what its screen shows, close the tab.
#
#   testtab-run.sh RUNDIR NAME [agents:testtab flags...]
#
# Defaults, each replaced by the same flag given after NAME: --space is the herdr-app space of this terminal
# ($HC_TERMINAL_ID), --folder is this checkout's root, --names is NAME, --tools is Read.
# Nothing is ever typed into the tab. On exit 0 the screen is read until the tab stops working (at most
# $TESTTAB_SETTLE seconds, default 60); on exit 4 it is read once. The screen goes to RUNDIR/screen_NAME.txt and
# the tab is closed whatever happened. The exit code is the task's: 0 ready, 1 refused flags, 2 usage, 3 refused, 4 for the owner.
set -uo pipefail
[[ $# -ge 2 ]] || {
  echo "usage: testtab-run.sh RUNDIR NAME [agents:testtab flags...]" >&2
  exit 2
}
run="$1" name="$2"
shift 2
root="$(git rev-parse --show-toplevel)" || exit 2
space="$(herdr-app ls | jq -r --arg t "${HC_TERMINAL_ID:-}" \
  '.spaces[] | select([.tabs[].terminals[].terminal] | index($t)) | .id')"
[[ -n "$space" ]] || {
  echo "testtab-run: no herdr-app space lists this terminal (HC_TERMINAL_ID)" >&2
  exit 2
}
mkdir -p "$run"
new="$run/tabnew_$name.json" screen="$run/screen_$name.txt"
rm -f "$new" "$screen"

mise run -q agents:testtab --space "$space" --run "$run" --folder "$root" --name "$name" --names "$name" \
  --tools Read "$@"
rc=$?
echo "testtab-run: agents:testtab exit $rc"
[[ -s "$new" ]] || {
  echo "testtab-run: no tab was opened"
  exit "$rc"
}

tab="$(jq -r .tab "$new")" terminal="$(jq -r .terminal "$new")"
echo "testtab-run: tab $name ($terminal), tab id $tab"
if [[ $rc -eq 0 ]]; then
  # A working tab shows "esc to interrupt"; two reads in a row without it mean the reply is finished.
  quiet=0 end=$((SECONDS + ${TESTTAB_SETTLE:-60}))
  while ((quiet < 2 && SECONDS < end)); do
    sleep 2
    hc read "$terminal" >"$screen" 2>&1
    if grep -q "esc to interrupt" "$screen"; then quiet=0; else quiet=$((quiet + 1)); fi
  done
  ((quiet >= 2)) || echo "testtab-run: still working after ${TESTTAB_SETTLE:-60}s; the screen is partial"
else
  hc read "$terminal" >"$screen" 2>&1
  echo "testtab-run: exit $rc is the owner's: report $name ($terminal) and $screen to the lead; nothing was sent"
fi
echo "testtab-run: screen saved to $screen"
herdr-app "do" tab.close --id "$tab" >/dev/null
if herdr-app ls | grep -q "$tab"; then
  echo "testtab-run: tab $name ($terminal) is STILL OPEN: herdr-app do tab.close --id $tab" >&2
else
  echo "testtab-run: closed $name ($terminal)"
fi
exit "$rc"
