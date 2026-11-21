# GLM workers

The lead may assign a scoped implementation to GLM-5.3-Flash through ZCode. The Codex driver owns the brief,
diff review, verification and handoff.

## Prepare and dispatch

- Confirm the approved watched launch route, provider admission, stop time and load limits with the coordinator.
- Give the writer a dedicated Git worktree and branch for implementation, and a brief with the issue, allowed files, tests
  to write and acceptance criteria. Supply only the scoped source and evidence. Keep private transcripts,
  login files and credentials out of the brief.
- Use a launch route that applies the filesystem fence before starting ZCode. Deny writes by default,
  explicitly allow the checkout and necessary runtime writes, and deny reads of sensitive paths such as
  credential stores, environment files and other agents' state. Keep the system keychain readable for
  ZCode sign-in.
- Configure the approved launcher to disable plugins, agent fan-out and general shell execution before
  starting ZCode. If the task needs a reply, expose only the fixed, attempt-scoped `hc` helper with
  its approved destination and payload. Start ZCode only after the fence and these restrictions are in effect.
- Run `herdr-app ls` and find the space whose tabs include the driver's `$HC_TERMINAL_ID`. Stop if the
  command fails or the space cannot be identified, and ask the owner. Open one watched ZCode TUI there with
  `herdr-app do tab.new` and the approved launcher, passing the writer's checkout as `--folder`. Use the
  approved offer model and guarded mode.
- Confirm the model in the TUI, send the task with `hc`, and use `hc read` on that terminal to verify that the
  task arrived. Verify provider acceptance and the matching acknowledgement. Record the tab, task scope,
  outcome and source of any usage figures. For CPP coordination between Codex peers, the owner requires
  `codex queue --thread <UUID> --message <text>`. Use the receiving Codex thread UUID.

## Review and hand back

- Track the writer and its child processes by attempt from launch through shutdown, including after the
  tab closes or the processes are reparented. At the agreed stop time, interrupt any active turn in its
  watched TUI. Capture the evidence, close the tab, and verify that the tracked processes have exited before
  reviewing any outcome. Confirm the identity of any survivor before terminating it and rechecking. Escalate
  to the coordinator if shutdown cannot be confirmed. Report local shutdown and report provider release
  separately when confirmed.
- Before retrying, reconcile any partial edits and confirm fresh provider admission with the coordinator,
  including current concurrency and quota. Local shutdown alone does not confirm provider release.
- Compare the diff with the issue and the brief's acceptance criteria, including after a timeout or an empty
  reply. The CPP owner requires native Codex `/review` for ZCode work under this runbook. Run it in a
  fresh watched read-only tab in the writer's worktree
  (`codex-hc -a never -s read-only`). Review the exact diff, including uncommitted changes, before accepting,
  staging or merging ZCode work.
- Get the applicable host grant before any heavy check, container run or commit whose hook runs heavy checks.
  Follow [the shipping checks](../../unix/home/.config/agents/workflow/ship.md) for testing, simplification,
  retesting and verification. After ZCode exits, the coordinator reassigns the worktree and branch to the
  Codex driver before the driver edits anything there. Perform the simplification pass in a
  writable Codex tab. Review the final diff again if it changes. Hand the coordinator or owner the verified
  diff, results and any pending live acceptance for staging by path. Credit the model that wrote the code.
  Get the owner's approval of the exact public text through the lead before any GitHub write. Renew approval
  if the text changes. Use the repository's App identity and merge flow.
