# run-skill-auto

Runs `/run-skill-generator` automatically. When this session's own reply (its final answer, or the text of a
SendMessage or SendUserMessage call) contains a line `/run-skill-generator <unit>: <what to drive>` in backticks,
the mod runs that command once, as if the owner typed it. Each line runs once ever: a store key is claimed before
the run, so a resume, a reload or a second session never repeats it. Each run is logged to
~/.local/state/run-skill-auto/log.jsonl and shown as a toast. Subagent output is ignored.

The record is set when the run is handed off, not when the skill finishes: the mod cannot see a skill run's end. A
run Claude Code refuses is not recorded. To run a line again after a run that stopped partway, type
`/run-skill-forget <unit>: <what>`; the next reply that ends with the line runs it once more.

Tests: `claude plugin test unix/home/.local/share/claude-mods/run-skill-auto`.
