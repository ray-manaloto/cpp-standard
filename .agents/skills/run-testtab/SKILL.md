---
name: run-testtab
description: Open, read and close one guarded live-test Claude Code tab in the current herdr-app space with `mise run agents:testtab`, through the driver `testtab-run.sh`. Use it whenever someone asks to run, open, launch, start or try a live test tab or test session, to check a hook, mod, plugin or setting in a real Claude tab, or to see what a fresh Claude session shows in this checkout. The tab's workspace-trust dialog is never answered - exit 4 goes to the owner through the lead.
---

# Run one guarded live-test Claude tab

`mise run agents:testtab` (`.mise/tasks/agents/testtab`, `python/agents/testtab.py`) opens a Claude Code tab in a
herdr-app space with a tool allowlist enforced by a PreToolUse guard (`python/agents/testguard.py`). It refuses a
folder the owner has not trusted, and it never answers a trust dialog. The driver
`.agents/skills/run-testtab/testtab-run.sh` adds the rest of one test: it finds the space, runs the task, saves
the tab's screen and closes the tab.

The guard hook carries `"onFailure": "block"`: a broken guard (it cannot start, crashes, times out, or cannot write
its log) now stops every tool call in the tab until it is fixed. Fix the guard or the run's log folder, not the tab.

Paths are relative to the checkout root. Run from a herdr terminal (`$HC_TERMINAL_ID` set) on the Mac.

## Rules

- Never type into, send keys to or answer a dialog in a test tab. Exit 4 is the owner's: report the tab as
  `name (terminal)` with the saved screen to the lead and stop.
- One test tab at a time, inside the slot the lead gave you. Every tab opened is closed; the driver does it.
- The first prompt goes in `--prompt`. Give one every time (see Gotchas).

## Run (agent path)

```bash
R=~/dev/tmp/run-testtab/run2      # the run directory, outside the checkout
.agents/skills/run-testtab/testtab-run.sh $R testtab-a \
  --prompt "Read the file AGENTS.md and reply with its first line only."
# -> {"name": "testtab-a", "terminal": "t355", "ready": true, "why": "ready"}
# -> testtab-run: agents:testtab exit 0
# -> testtab-run: tab testtab-a (t355), tab id tb69b1...
# -> testtab-run: screen saved to .../run2/screen_testtab-a.txt
# -> testtab-run: closed testtab-a (t355)
```

`testtab-run.sh RUNDIR NAME [agents:testtab flags...]`. Its defaults, each replaced by the same flag after NAME:
`--space` the space that lists this terminal, `--folder` the checkout root, `--names NAME`, `--tools Read`. Other
flags (`--model haiku`, `--effort low`, `--mode default|plan`, `--extra FILE`, `--no-tools-flag`, `--wait 20`)
are in the docstring of `python/agents/testtab.py`. The driver exits with the task's code.

Read the result from the run directory:

```bash
grep -v '^\s*$' $R/screen_testtab-a.txt | head -8   # the prompt, "Read 1 file", the reply
cat $R/log/testguard.jsonl                           # one line per tool call the guard allowed or denied
```

`$R` also holds `settings-NAME.json` (the tab's settings) and `tabnew_NAME.json` (space, tab id, terminal).

| Exit | Meaning | What to do |
|---|---|---|
| 0 | the tab was ready; screen saved after it stopped working | read the screen and the guard log |
| 1 | `--mode auto`, `bypassPermissions` or `dontAsk`, or a shell tool in `--tools`; no tab opened | fix the flags |
| 2 | usage error; no tab opened | fix the flags |
| 3 | the folder is untrusted, unknown or not in git; no tab opened | tell the lead; only the owner trusts a folder |
| 4 | a trust dialog, or no ready prompt within `--wait`; screen saved, tab closed, nothing sent | report to the lead |

## Run by hand

The same steps without the driver, when you need the tab to stay open while you look:

```bash
S="$(herdr-app ls | jq -r --arg t "$HC_TERMINAL_ID" \
  '.spaces[] | select([.tabs[].terminals[].terminal] | index($t)) | .id')"   # this terminal's space
mise run agents:testtab --space $S --run $R --folder "$PWD" --name testtab-live1 --names testtab-live1 \
  --tools Read --prompt "Read the file AGENTS.md and reply with its first line only."
cat $R/tabnew_testtab-live1.json       # "tab": the id to close, "terminal": the id to read
hc read "$(jq -r .terminal $R/tabnew_testtab-live1.json)"
herdr-app do tab.close --id "$(jq -r .tab $R/tabnew_testtab-live1.json)"   # -> {"ok": true}
```

## Test

```bash
mise run agents:testtab-check   # offline: stand-in herdr-app and hc, a scratch trust record; opens no tab
```

## Gotchas

- **No `--prompt` gives exit 4 on a healthy tab.** The launcher's ready markers are `? for shortcuts`,
  `shift+tab to cycle` and `esc to interrupt`. On Claude Code 2.1.327 with this machine's status line the idle
  screen shows none of them (`manual mode on` instead), so only a tab busy with its first prompt reads as ready.
  Without a prompt the task waits 20 s and exits 4 with `no ready prompt within 20s` and no dialog on screen.
  Read the saved screen before calling exit 4 a trust dialog.
- **The stdout JSON has the terminal, not the tab.** `tab.close --id` needs the `tab` value from
  `tabnew_NAME.json`.
- **Exit 1 is not in the task's docstring** (0/2/3/4): the mode and shell-tool refusals use it.
- **Trust is keyed by the main checkout.** A linked worktree is trusted when its main checkout is; a fresh
  `git init` folder is refused with exit 3 (`is not trusted`), a non-git one with `is not in a git checkout`.
- **The tab is done when `esc to interrupt` is gone.** The driver waits for two reads without it, at most
  `TESTTAB_SETTLE` seconds (default 60). A short reply finishes in about 3 s on haiku.
- **`mise run` adds `ERROR task failed`** after every non-zero exit; the task's own line above it is the reason.
