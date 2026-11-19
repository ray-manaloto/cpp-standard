# GLM workers

The lead may route a scoped implementation to GLM-5.3-Flash through ZCode. The Codex driver writes the task,
reviews the complete diff, and coordinates verification and shipping with the lead. Use this route when the
lead has approved a writer run and the fenced launcher is available.

## Prepare and run

- Give the writer one linked worktree and a short brief with the issue text, allowed files, focused tests to
  write, and acceptance criteria. Supply only the source and evidence needed for that ticket. Keep private
  transcripts, login files and credentials out of its inputs.
- Use the approved ZCode writer launcher with CLI plugins disabled. The filesystem profile allows reads by
  default and explicitly denies reads of credential stores, other agent state, and environment files.
  The system keychain stays readable for ZCode sign-in.
- The profile denies writes by default and allows them to the worktree, the output directory, ZCode state,
  caches, mise paths, temporary directories, and device paths. ZCode's current directory and tool flags
  alone do not enforce these rules.
- Keep shell execution and agent fan-out disabled for the writer. The driver runs checks after review. Follow
  the lead's concurrency, load and quota limits, and keep the launcher stable while a run uses it.

## Review and hand back

- Check the actual worktree diff against the issue, including changes after a timeout or empty response. An exit
  status and a model summary are insufficient evidence of completion. Record the checks that ran and any
  acceptance that still needs a live run.
- Run targeted checks on the changed files and stage by name. Get the applicable slot before a heavy check or
  a commit whose hook runs heavy checks. Credit the model that wrote the code.
- Send the lead the staged changes, evidence and remaining gates. The owner approves exact public text through
  the lead before any GitHub write. Use the repository's App identity and merge flow when authorized.
