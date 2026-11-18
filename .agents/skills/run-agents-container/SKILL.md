---
name: run-agents-container
description: Build, start, check and remove a throwaway cpp-standard Linux agent container on the PC with `.agents/skills/run-agents-container/driver.sh`. Use it whenever someone asks to run, start, launch, build, test, smoke-test or verify the agent container or the agents image (`docs/standard/agents.Dockerfile`, `mise run agents:image`, `mise run agents:up`), or to confirm that a change to them still gives a container with the right flags, mounts, tools and logins.
---

# Run the cpp-standard agent container

The agent container (D155) is one project's clone plus the coding agents, on the PC's Docker. The image is
`docs/standard/agents.Dockerfile`; `mise run agents:up` registers the container with agent-secrets, clones the
project to `~/dev/containers/<project>` on the PC and starts `<project>-agents`.

The driver wraps those tasks for a throwaway run under its own image tag, `cpp-standard-agents:runskill`. The
live containers (`cpp-standard-agents`, `cpp-core-agents`) run `:dev`, and the driver refuses any project whose
container runs another tag. Paths are relative to the repository root; run every command from there, on the Mac.

## Prerequisites

- `ssh -o BatchMode=yes pc true` works.
- This checkout's HEAD commit is on GitHub (`git branch -r --contains HEAD` prints a branch). The image is built
  from that commit as GitHub serves it, so `build` stops on an unpushed commit: push the branch first.
- The PC Docker slot, from chief-of-staff. `build` and `up` stop without it. `check` and `down` do not ask for
  it, so run them only inside your own grant too. Give the slot back as soon as `down` has finished:

  ```bash
  mise run slot:release --holder <your tab id>
  ```

- A project with no agent container yet. `cpp-utilities` is the one this skill was run with.

## Run (agent path)

Four steps, in order. `down` runs even when `check` fails. When `build` or `up` fails there is no container:
run `down` with `ORPHANS=1` added, which removes whatever a failed `up` left and skips what is not there.

```bash
.agents/skills/run-agents-container/driver.sh build
```

About 13 minutes cold (786 s measured), which is longer than one foreground command may take: start it in the
background and wait for it to exit.

```bash
.agents/skills/run-agents-container/driver.sh up cpp-utilities
.agents/skills/run-agents-container/driver.sh check cpp-utilities
RM_CLONE=1 RM_IMAGE=1 .agents/skills/run-agents-container/driver.sh down cpp-utilities
```

`check` prints one `ok` or `FAIL` line per fact and exits 1 on any `FAIL`:

- From the host: running, image tag, not privileged, no added capabilities, restart `unless-stopped`, user
  `dev`, hostname, `container=docker`, the `/workspace` and read-only `/run/agent-secrets` bind mounts, and the
  six named volumes.
- Inside, as a login shell: user and working directory, the workspace's origin and head, the three secret files
  are present and the mount is read-only, the git identity, `git ls-remote` and `gh repo view` as the agent App,
  and the versions of `claude`, `codex`, `opencode` and `mise`.

`down` removes the container, its six volumes and its registration, then prints what is left and fails unless
that is `0 0 0`. `RM_CLONE=1` also removes the PC clone when it has no local changes or commits; `RM_IMAGE=1`
also removes the 8 GB image. Leave both out to keep them for the next run.

`driver.sh all <project>` chains the four steps and exits with the status of `check`. It needs a caller with
no time limit, because of the build.

To drive the container yourself between `up` and `down`, send the commands on stdin:

```bash
ssh -o BatchMode=yes pc docker exec -i cpp-utilities-agents bash -l -s <<'EOF'
mise --version
git -C /workspace log -1 --format='%h %s'
EOF
```

## Gotchas

- **`gh` fails inside `/workspace` of a new container.** `gh` is a mise shim, and the project's `mise.toml` is not
  usable until its tools are installed. Run `gh` from `$HOME` with `--repo`, or run `mise install` in `/workspace`
  first. `check` does the former and prints a `note` line listing the tools not installed yet.
- **`mise install` in `/workspace` exits 1 on the `pipx:` tools.** The image sets no default `uv`, so
  `pipx:check-jsonschema` stops with `No version is set for shim: uv`. The other tools install. Not fixed yet.
- **Quotes do not survive `ssh pc docker exec … bash -lc '…'`.** Use the stdin form above.
- **`agents:up` on an existing container only starts it.** It does not apply `--image`, and it registers the
  name again first. That is why the driver refuses a project whose container runs another tag, and a project
  that is registered but has no container.
- **Never print a file under `/run/agent-secrets`.** `check` tests that the files are present, nothing more.

## Troubleshooting

- `agents:image: HEAD <commit> is not on GitHub yet; push it first`: the second prerequisite. Nothing was built.
- `slot: refused: the slot is granted to <tab>, not <you>`: you do not hold the slot. Ask chief-of-staff.
- `driver: <name> runs cpp-standard-agents:dev, not cpp-standard-agents:runskill: not mine to touch`: the project
  has a live container. Pick a project without one.
- `driver: no container <name>: nothing removed`: `down` found nothing to remove. If an earlier `up` of yours
  failed half way and left volumes or a registration, run `ORPHANS=1 … driver.sh down <project>`.
- `Field 'path' is not defined … tools['github:microsoft/vcpkg-tool'].path` from `gh`: the first gotcha.
