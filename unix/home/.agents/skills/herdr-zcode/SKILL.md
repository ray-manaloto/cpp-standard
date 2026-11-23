---
name: herdr-zcode
description: Open and coordinate watched ZCode TUI workers (npm:zcode-app-cli) in Herdr using hc and ZCode's user/global configuration. Use for a single ZCode task, parallel ZCode workers (such as automating OpenWiki repo and docs mapping), or a Herdr-to-ZCode transport check.
---

# ZCode workers in Herdr

Load the `herdr-core` skill and run `hc --skill` and `herdr-app --skill`. This workflow uses the caller's local Herdr space, the user mise `npm:zcode-app-cli` and `node` installs, and ZCode's own user/global configuration (`~/.zcode/cli/setting.json`, `~/.zcode/v2/provider_config.json`) without wrapper restrictions.

## Launch and dispatch

1. Choose a working folder and a unique tab name for each lane. Give concurrent writers disjoint worktrees or output directories; when automating OpenWiki mapping, keep one single owner per OpenWiki MCP page queue (`openwiki_next_page` can otherwise hand the same job to competing callers). Size parallel batches to the provider account's concurrency limit (historically ~3 in-flight requests including subagents).
2. Run the launcher from the calling Herdr terminal. Its JSON lines identify each opened tab, including tabs opened before any partial failure. Pass `-- <zcode-args...>` only when forwarding explicit ZCode CLI flags such as `-- --resume <session_id>`.

   ```sh
   python3 ~/.agents/skills/herdr-zcode/scripts/launch.py --folder "$PWD" 'ZCode map 1' 'ZCode map 2'
   ```

3. Inspect each UI with `hc read <terminal> --lines 0` until the footer shows the expected model, mode, and effort and the input prompt is empty. Stop and resolve any sign-in, trust, or Keychain dialog before sending tasks. For a zero-spend local transport check, send `/status`.
4. Send one task at a time per ready worker using `hc send -- <terminal> "$task"`. Include the task scope, target paths, agreed result path or identifier, and `Report with hc send $HC_TERMINAL_ID '<status and result path>' when done or stuck`. Verify delivery with `hc read`. `zcode-app-cli` does not emit `herdr-core` OSC 7501 turn markers (its bundled Herdr plugin targets legacy `herdr 0.9.5`), so `hc send --wait` is unsuitable for completion tracking. Treat `hc wait <terminal> --output <text>` as a wake-up only (it can match echoed prompt text before any model reply arrives) and verify the actual reply or result file with `hc read <terminal> --lines 100`.
5. Give each worker a new task only after its previous task finishes. Report tab names and terminal IDs together (`name (tN)`). Close finished tabs with `herdr-app do tab.close --id <tab>`.

For a durable receipt, inspect ZCode's local SQLite telemetry (with `~/.zcode/cli/rollout/model-io-<session>.jsonl` fallback) using the read-only receipt helper; add `--include-reply` to recover final assistant text when terminal output was cleared or missed:

```sh
python3 ~/.agents/skills/herdr-zcode/scripts/receipt.py --dir "$PWD" --since <epoch_ms>
```

If ZCode needs authorization, run `mise exec -- zcode login --no-browser` in a dedicated watched tab, open the emitted link, and retry once sign-in completes. On HTTP 429 or quota/concurrency errors (`3008`, `1113`, `exceed quota limit` — reported in `receipt.py` `error_codes`/`error_messages`, and not retried automatically by `zcode`), stop submitting new turns, let in-flight workers finish, and resume with lower concurrency or an active quota window.
