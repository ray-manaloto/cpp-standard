# cpp-standard agent notes

EGM artifact directory: docs/designs/level-1/

The design is `docs/designs/environment-standard.md`; its decisions are in
`docs/designs/level-1/decisions-log.md`. Run the `egm-check` project skill
(`.agents/skills/egm-check/`) to see where the work stands against the EGM
workflow.

## Agent skills

### Issue tracker

GitHub Issues on ray-manaloto/cpp-standard, through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles, each label named as its role: `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. Decisions are the D-rows of `docs/designs/level-1/decisions-log.md` (there is no `docs/adr/`); the
design is `docs/designs/environment-standard.md`. See `docs/agents/domain.md`.

## Workflow facts

- Check: `hk check` runs the hk steps on the changed files; it passes before each commit. `mise run check` runs
  them on every file (`hk check --all`) and is a heavy run.
- Gate: `mise run ci` configures, builds, tests and measures coverage for each gate preset. CI runs it in the
  `gate-linux-arm64` job; on the owner's Mac it is a heavy run.
- Must-fail: `mise run ci-must-fail` runs every fixture in `fixtures/must-fail/` (listed in its `expected.toml`) and
  fails when a check accepts its planted fault. CI runs it in the `must-fail` job in the tools image; outside Actions
  it runs in that image as a container run, which waits for the coordinator's go-ahead. The toolchain fixture needs
  gh, a GitHub token in `GH_TOKEN` (or a gh login) and the network; without them it reports "could not run".
- Toolchain: `mise run toolchain:fetch` installs clang-p2996 by its artifact tag: `main`'s attested release, else a
  rebuild (outside Actions it never takes a staged copy, and it stops, without rebuilding, when it cannot ask
  GitHub, e.g. no token); `--release-only` takes the release or fails.
- Shipping: a branch and a pull request into `main`, opened with
  `repotools pr-create --title <title> --body-file <body file>`. The merge is
  `mise run //repo:pr-merge <number> <title> <body file>`, run alone: the local hk gate is not run (D169,
  `repotools.toml`); it checks the other gates, waits for the required checks to pass, then puts the pull request
  in the merge queue. The command returns once the pull request is queued. The queue's required checks gate the
  squash merge (`.github/rulesets/main.json`). `jouet wait pr <number> --until merged` waits for the merge.
  Never `--admin`, never past the queue.
- Worktrees: one worktree and one branch per agent (D23). An agent works only in its own worktree, never in the
  main checkout or another agent's worktree.
- Identity: an agent's pushes and pull requests carry the agent App, not the owner's login. On the Mac host that
  is `cpp-standard-agents` (D40): `GH_TOKEN="$(mise run -q agent:token)" gh ...` for `gh`, and for git:

  ```sh
  git -c credential.https://github.com.helper= \
    -c credential.https://github.com.helper='!mise run -q agent:token' push ...
  ```

  The empty helper comes first: without it the global `gh` helper answers before the App, as the owner. In a
  project container it is `ray-manaloto-agents`, whose token is mounted at `/run/agent-secrets` (D155).
- Apt pins: `mise run pins:apt-bump` (skill `pins-apt-bump`) moves them to the newest indexed version; `--check`
  reports pins gone from their index. Not a heavy run; the daily `apt-bump` workflow runs it (D165).
- Heavy runs: one at a time on the owner's Mac, and only with the coordinator's go-ahead. Heavy are
  `mise run check`, `mise run ci`, any other build, `pytest -n auto`, image builds and pushes, and any job over
  10,000 files. Every container run on the Mac waits for the coordinator's go-ahead, however small. Jobs on the
  Linux machine ask for their own slot and never run a privileged container. Each ticket says whether it needs a
  heavy run.
- Hand-offs: an implementing agent never dispatches a workflow on `main`, creates a ticket or changes a live
  repository setting. It hands each to the coordinator: the coordinator dispatches workflows and creates tickets,
  and the repository's settings owner applies a setting or ruleset change on the owner's word. The ticket that
  needed it records who did it.
- Review: none required; a lead may ask Codex for one by choice.
- Content guard: the author reads the exact bytes of public text for private content before publishing. The
  home-path scan is not the content guard.
