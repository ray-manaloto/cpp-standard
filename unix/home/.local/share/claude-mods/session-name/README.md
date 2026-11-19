# session-name

A Claude Code mod that gives each session the name of the herdr tab it runs in, so one `<base>-<stamp>` string names
both the tab and the session and resumes by it (#303, with `python/agents/tabname.py` and `herdrtab.py tab`, which
open the tab under that name and pass it to `claude -n`).

- **At startup, resume and fork** the session takes its title from the tab: a tab name that already carries the stamp
  is kept as is; an unstamped one gains a stamp (`/bin/date +%Y%m%dT%H%M%S.%N%z`, its offset cut to the hour, e.g.
  `w1-20261119T120850.005365000-06`) and the tab is renamed to it (`herdr-app do tab.rename`), so tab and session
  never drift apart.
- **The session id is stored as the terminal's `session` label** (`hc label <terminal> session=<id>`), so a later
  resume can go by id instead of by exact name.
- **`/clear` and compact are skipped**: the session keeps the name it already has (a title on clear is ignored, and
  compact already has one).
- **Every step is bounded and best-effort**: each process call has a `timeoutMs`, any failure is logged to the debug
  log once, and the session goes on unnamed. The mod never throws.

The tab is found through the terminal: `HC_TERMINAL_ID` → `hc get <terminal> --json` → the `herdr.tab` label →
`herdr-app ls` → that tab's name. Outside herdr (no `HC_TERMINAL_ID`) the mod does nothing.

Run it for one session with `claude --plugin-dir <this folder>`. Tests: `claude plugin test <this folder>`.
