---
name: run-herdr-tab
description: Open, read and close a watched Claude or Codex agent tab in the current herdr-app space with `mise run agents:tab` and `mise run agents:tab-close`. Use it whenever someone asks to open, launch, start, spawn or run a peer agent, reviewer, worker or watched tab, to run a task in another Claude or Codex tab, or to close one. It replaces the hand-written `herdr-app do tab.new` line and never falls back to `hc run`.
---

# Open and close a watched agent tab

`mise run agents:tab` (`.mise/tasks/agents/tab`, `python/agents/herdrtab.py`) finds the space whose tabs list
`$HC_TERMINAL_ID`, opens the tab there with `tab.new` (Claude as `claude`, Codex as `codex-hc`, the task as the last
argv word) and reads the new terminal with `hc read` until the start of the task text is on its screen.
`agents:testtab` shares that code and adds a guard; use `run-testtab` for a guarded test tab.

Paths are relative to the checkout root. Run from a herdr terminal (`$HC_TERMINAL_ID` set).

## Run (agent path)

```bash
out=$(mise run -q agents:tab --agent codex --name herdrtab-live --task "Reply with the single word ok and stop.")
echo "$out"
# -> {"name": "herdrtab-live", "space": "sp69a4...", "tab": "tb3c7d...", "terminal": "t3c2"}
# -> herdrtab-live (t3c2)          <- the last line: name first, id in brackets; use it when naming the tab to the owner
hc read t3c2 | grep -v '^\s*$' | tail -5          # what the tab shows now
mise run -q agents:tab-close --id "$(echo "$out" | head -1 | jq -r .tab)"
# -> {"closed": "tb3c7d...", "space": "sp69a4..."}
```

Flags: `--agent claude|codex`, `--name`, `--task` (all required), `--folder` (default: the current directory),
`--wait` (seconds, default 30). Close every tab you open when you are done.

| Exit | Meaning | What to do |
|---|---|---|
| 0 | the start of the task text was on the tab's screen | read the tab with `hc read` as it works |
| 2 | usage error, `herdr-app` failed, or no space lists this terminal; nothing opened | fix it or ask the user; never use `hc run` |
| 4 | a tab opened but a trust dialog is open or the task never showed; the screen is on stderr; the tab stays open | report `name (terminal)` to the owner; send nothing to the tab; close it when told |

`agents:tab-close` exits 2 for a tab id that is in another space or in none.

## Test

```bash
mise run agents:tab-check       # offline: stand-in herdr-app and hc; opens no tab
mise run agents:testtab-check   # the shared code under the guarded launcher
```

## Gotchas

- **The task is the first message.** A Claude tab started without one opens the agents dashboard, so `--task` is
  required. A task starting with `-` is refused (the agent would read it as a flag).
- **The JSON line has the tab id, the last line the terminal.** `tab-close` takes the `tab` value, `hc read` the
  terminal.
- **Arrival is the first 30 non-space characters of the task on the screen.** A long task that the tab's screen
  truncates or re-wraps inside those characters would wait out `--wait` and exit 4; read the screen on stderr first.
- **Exit 4 is not a failed launch.** The terminal exists and is still open; close it with `agents:tab-close`.
- **Codex needs `codex-hc`,** which the task uses itself: a tab's PATH has no mise wrappers, so plain `codex`
  would run without the fnox proxy.
