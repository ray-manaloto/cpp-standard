---
name: agy-context
description: "Show what fills an Antigravity CLI (agy) session's context: the /context panel (capacity, percentage, tokens by category) and a live list of the files and commands taking up context. Use when asked how much context an agy session uses, what is in it, or which files fill it."
disable-model-invocation: false
---

agy has no command or export for its `/context` panel. There are two ways to see what is in an agy session's
context: open the panel in a fresh agy tab, or list the files with `agy:context-files`.

## Files in context, live

```sh
mise -C <cpp-standard checkout> run agy:context-files -- --capacity 1000000 --follow
```

- `--conversation <id>` picks a conversation (default: the newest transcript). `--json` prints JSON.
- **Auto-loaded files:** the rule and skill files agy finds from the session's folder (`--cwd`, default the
  current folder) up to the repository root, plus `~/.gemini` and plugins. Skills count only their frontmatter.
- **Tool results:** each tool call in the transcript, with its file path or command and the size of its result.
  `--follow` prints new results and each new turn's context as the transcript grows.
- **Measured vs estimated:** "Context now" is measured (input + cache-read tokens of the last turn). Every
  per-file and per-result size is an estimate (bytes / 4). agy never records how much each file costs.

## The /context panel

1. Find the current space: the one in `herdr-app ls` whose tabs list `$HC_TERMINAL_ID`.
2. `herdr-app do tab.new --space <id> --name agy-context-probe --folder <workspace> --argv '["agy"]' --focus false`
3. `hc wait <t> --timeout 30`, then `hc read --lines 0 <t>` until the prompt shows.
4. Type the command as keys: `hc keys <t> / c o n t e x t`, then `hc keys <t> enter`. **Never `hc send`:** it
   wraps text in `<hc from=...>` tags, so agy reads it as a prompt and starts a model turn.
5. `hc read --lines 0 <t>`: the total and capacity, tokens per category (system prompt, system tools, rules,
   skills, subagents, MCP tools, messages) and the auto-loaded folders.
6. `hc keys <t> esc`, then `herdr-app do tab.close --id <tab id>`.

The probe is a fresh session: it measures that folder's baseline, not another live conversation.

## Other sources

- The status-line script's JSON (`statusLine` in `~/.gemini/antigravity-cli/settings.json`) carries
  `context_window.{context_window_size,used_percentage,current_usage}` on every refresh. It has no file list.
- agy has no native OpenTelemetry export (google-antigravity/antigravity-cli#366).
