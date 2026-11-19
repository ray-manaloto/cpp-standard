# agy workers

Some tickets go to an agy worker (Antigravity CLI) instead of a Claude session. The lead starts it with one task and
stays the author of everything that leaves the machine.

## Which tickets go to agy

- **Goes to agy:** a ticket of documentation, comments, a lint or typo sweep, or a small mechanical change whose
  checks are `hk check` on the changed files, `typos`, `rumdl`, `ruff`, `ty`, `pytest` or `mise run pins:validate`,
  and whose brief fits in one file.
- **Stays with a Claude session:** a ticket that needs a design choice, a container, ssh, the network, or a live check
  of agy itself.
- **Heavy runs** (`hk check --all`, `mise run check`, `mise run ci`, builds, `pytest -n auto`, image builds) need a
  slot from the coordinator, as for a Claude worker. agy asks before them; the lead approves only after the slot
  is granted.

## Same privileges as a Claude worker (D178)

The owner ruled on 2026-11-19: "update agy's global settings so ty, hk check, pytest and typos run without asking;
keep docker, ssh, gh and git push/commit as ask / it should have the same privileges as claude models/agents". The
rules file `.agents/agy-worker-settings.json` follows it:

- **Allow:** `hk check` on the changed files, `ty`, `pytest`, `typos`, `ruff`, `rumdl`, `git add` by name, the read
  commands and the mise check tasks.
- **Ask:** `docker`, `ssh`, `scp`, `gh`, `git commit`, `git push`, `repotools pr-create`,
  `mise run //repo:pr-merge`, and the heavy runs. A Claude worker also waits for a go-ahead on these.
- **Deny:** `sudo`; `fnox get`, `fnox exec`, `fnox export`, `fnox set`; `git stash`; `git add -A`, `git add --all`
  and `git add .`; `--no-verify`; `--admin`; a force push without lease.

agy's rules are `action(target)` entries that match literal word prefixes or a `regex:` pattern; deny beats ask
beats allow. A flag anywhere in a command (`--no-verify`, `--admin`, `-f`) needs a regex rule. Not expressed:
`fnox proxy run` is neither allowed nor denied (a prompt), because a rule cannot allow it and deny `fnox get`
without also listing each; a command with substitution or one agy cannot parse needs a full-line match, so a deny
prefix may not catch it.

## What the lead still does

The worker edits, runs the checks and stages files in its worktree. Commit, push, the pull request and the merge
are asks, so the worker's prompt waits for the lead. The lead reviews the diff, then approves the prompts that ship
it (commit, push as the App, `repotools pr-create`, `mise run //repo:pr-merge`) or ships the ticket itself, and
runs /verify. Widening `git commit`, `git push`, `gh` or the merge from ask to allow is a separate owner decision.
Every brief carries the Claude brief's lines: heavy runs wait for a slot, docker and ssh wait for a go-ahead.

## Start a worker

```sh
mise run agents:agy-worker <worktree> <brief> [--plan <PLAN_ID>] [--model <model>] [--dry-run]
```

- The worktree is a folder directly under `cpp-standard.worktrees/`; the brief is a file. The task adds three folders
  with `--add-dir`: the worktree, the brief's folder and the ticket's plan folder
  (`cpp-standard.plans/.planning/<PLAN_ID>`, `PLAN_ID` from `--plan` or the environment). It refuses a worktree
  elsewhere, a missing brief and a missing plan folder.
- The rules are `.agents/agy-worker-settings.json`, passed with `--settings`: session only, never saved to the
  owner's agy settings. They match command prefixes word by word, so a command wrapped in `bash -c`, `env` or a
  script can get past a deny rule. The real limit is the brief and the lead's review of every diff before it is
  pushed.
- Rules the owner once answered "always allow" for stay in agy's shared store and apply to the worker too; agy's
  `/permissions` lists them as `shared` beside the file's rules. A deny rule in the file still wins.
- agy may print "--mode auto is not available for this account" and continue in its default mode; the rules file
  then decides what runs without a prompt.
- Offline check of the launcher: `mise run agents:agy-worker-check` (a stand-in agy; it starts nothing).

## Sign-in preflight

Before it starts the worker, the task runs agy in a scratch folder with the prompt "Reply with only the word ok. Do
not run any tool." and reads the reply. It refuses to launch when agy shows "Sign-in update needed", says it is not
signed in, or does not answer ok. The fix: type `/logout` in agy, then sign in with Google again. The owner does any
password, passkey or 2FA step. `agents:agy-login --step status` is not this check: it only sees that a login file
exists.

The banner "Sign-in update needed" is a TUI warning that `agy -p` never prints, so the probe's reply cannot show it.
The task therefore also reads the log the probe just wrote (`~/.gemini/antigravity-cli/log/cli-*.log`) and refuses
when it holds `OAuth token lacks .../auth/aicode`: `owner: run /logout in any agy tab, then sign in with Google
again`. The Antigravity IDE app shares agy's one keychain entry (upstream antigravity-cli #1610), so when it runs the
refusal names it; whether the IDE is what drops the scope is not proven yet. `mise run doctor` prints the same
check from the newest log without running agy (`python/agents/agy_worker.py --health`). Neither reads a token or
login file, only log text.

## Antigravity.app and agy share one sign-in

Antigravity.app (`com.google.antigravity`, 2.33.0) and agy keep one keychain entry, so a running app can overwrite
agy's sign-in. `agents:agy-worker` therefore refuses to launch while it runs, with "Antigravity.app is running and
shares agy's sign-in; run `mise run agy:ide-stop` (owner OK) and retry." Three repo tasks, run from anywhere with
`mise -C <cpp-standard checkout> run <task>` (repo tasks, not global ones, because the live global mise config still
links into dotfiles until cutover): `agy:ide-status` (the app and any `language_server` left over; exit 0 only when
both are gone), `agy:ide-stop` (quits the app, waits until it and its `language_server` are gone, fails with a clear
message on `--timeout`) and `agy:ide-start` (`open -g -b`). `--app ide` takes `Antigravity IDE.app`
(`com.google.antigravity-ide`, 2.1.1) instead. Stop closes the owner's open windows, so nothing runs it
automatically: only the owner or an explicit task run does. Whether the older IDE app shares the entry is not known,
so the launch guard and the doctor line look at Antigravity.app only.

## One launcher for every project

`agents:agy-worker` is the one way to start an agy worker, for cpp-standard and for kb. kb today runs
`~/.local/bin/agy` directly (`--add-dir <worktree> -i <task>`, with and without `--model gemini-pro-orchestrator-neon
--mode auto`), so it gets no rules file and no sign-in check. What kb changes: start its agy tabs through
`mise run agents:agy-worker <worktree> <brief> --plan <PLAN_ID>` from a cpp-standard checkout (it needs a worktree
under a `cpp-standard.worktrees`-style folder and a plan folder, so kb either keeps that layout or asks for the two
path checks to become options), and stop starting agy by hand.

## While a worker runs

- Read its tab (`hc read`) at least every 10 minutes, or watch `hc ls` for "blocked". Answer a prompt by these rules;
  never choose "always allow" for a broad prefix.
- A prompt for `gh`, `git commit`, `git push`, `repotools pr-create` or the merge is the shipping step: approve it
  when the diff is reviewed and the brief says to ship. Answer "no" to docker, ssh and scp unless the brief allows
  them; any docker also needs the coordinator's go-ahead first. Deny rules never prompt.
- Never approve a command whose full text is hidden ("⋯ (N lines hidden)"). Expand it first with agy's ctrl+g
  (edit or expand command) and read all of it, or answer No and ask the worker to put the script in a file in its
  worktree and run that file. Approving hidden `python -c` text approves code nobody reviewed.
- Every brief tells the worker to run each command on its own from the worktree: no `cd … &&` chains and no
  `git -C <path>`. A chain or `-C` turns an allowed prefix into a prompt, and "always allow" on a `git -C` prefix
  would also allow commit and push.
