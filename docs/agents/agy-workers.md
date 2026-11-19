# agy workers

Some tickets go to an agy worker (Antigravity CLI) instead of a Claude session. The lead starts it with one task and
stays the author of everything that leaves the machine.

## Which tickets go to agy

- **Goes to agy:** a ticket of documentation, comments, a lint or typo sweep, or a small mechanical change whose whole
  check is `typos`, `rumdl`, `ruff` or `mise run pins:validate`, and whose brief fits in one file.
- **Stays with a Claude session:** a ticket that needs a design choice, a heavy run (`hk check`, the full test
  suite, a build, an image), a container, ssh, the network, or a live check of agy itself. No slot grant applies to
  agy, so heavy runs stay out of agy briefs.

## What the lead still does

The worker edits and stages files in its worktree. The lead runs `hk check`, commits, pushes, opens the pull request,
merges and runs /verify. agy's rules deny `hk`, `git commit`, `git push`, `git stash`, `gh`, `fnox`, `sudo`, `ssh`,
`scp` and `docker`.

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

## While a worker runs

- Read its tab (`hc read`) at least every 10 minutes, or watch `hc ls` for "blocked". Answer a prompt by these rules;
  never choose "always allow" for a broad prefix.
- Answer "no" to a prompt for docker, ssh, scp, gh, or git push, commit and stash, unless the brief allows it. Any
  docker also needs the coordinator's slot grant first.
- Never approve a command whose full text is hidden ("⋯ (N lines hidden)"). Expand it first with agy's ctrl+g
  (edit or expand command) and read all of it, or answer No and ask the worker to put the script in a file in its
  worktree and run that file. Approving hidden `python -c` text approves code nobody reviewed.
- Every brief tells the worker to run each command on its own from the worktree: no `cd … &&` chains and no
  `git -C <path>`. A chain or `-C` turns an allowed prefix into a prompt, and "always allow" on a `git -C` prefix
  would also allow commit and push.
