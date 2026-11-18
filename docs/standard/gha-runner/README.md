# The PC's GitHub runner: one-job container slots

Owner decisions (2026-11-09): runner for one private repository, glaze, cpp-utilities and dotfiles (org
`ray-manaloto`); **public repos run in one-job containers (this directory)**, the private one in one-job libvirt VMs (later,
after the KVM packages land via dotfiles); GitHub App auth; every tuning value in one config file; Eco mode plus
per-slot CPU limits.

## Files (installed on the PC)

| Source here | On the PC | What |
|---|---|---|
| `gha-slot` | `/usr/local/sbin/gha-slot` | build / smoke / exec / dry-run / once / run |
| `gha-slot@.service` | `/etc/systemd/system/` | one loop per slot: `systemctl enable --now gha-slot@glaze` |
| `runner.json` | `/etc/gha-runner/runner.json` (root, 600) | owner, App ids, image, defaults, slots |
| `Dockerfile` | `/etc/gha-runner/Dockerfile` | `local/gha-runner:latest` = official runner 2.338.2 + mise 2026.11.5 + sccache + uv |
| (owner) | `/etc/gha-runner/app.pem` (root, 600) | the GitHub App private key; the one secret at rest |

## How a job runs

1. Between jobs, the slot's volumes are wiped once older than `cache_max_age_days` (default 7), so a wipe never
   hits a running job.
2. **Trusted warm step:** the loop gets an App installation token, shallow-clones the repo's **default branch**
   (token via `GIT_CONFIG_*` env, never on a command line) in a throwaway container, and runs `mise install` there
   with the tools volume writable. Only this step ever writes the tools.
3. It asks GitHub for a single-use runner (`generate-jitconfig`, repo or org scope per slot) with the slot's labels.
4. It starts a **new job container**: user `runner` (uid 1001), all capabilities dropped, no-new-privileges, no
   sudo, no Docker socket, CPU quota / memory / pids limits, logs to the journal (`journalctl
   CONTAINER_TAG=gha-slot-<slot>`). Mounts:
   - `gha-tools-<slot>` at `/cache/mise` **read-only** (mise data dir);
   - a 64 MB tmpfs at `/cache/mise/shims`, seeded from the volume's shims at start (mise rebuilds shims during
     `mise install`, which needs a writable shims dir);
   - `gha-sccache-<slot>` at `/cache/sccache`, writable; `CMAKE_C/CXX_COMPILER_LAUNCHER=sccache` and
     `SCCACHE_CACHE_SIZE` are set.
5. The runner takes exactly one job and exits; the container is deleted, a runner entry that never got a job is
   removed, and the loop goes again. Jobs over `max_job_minutes` are killed. A failed warm step does not block
   the job (it then fails visibly in GitHub if a tool is missing).

Build tools see the slot's parallelism (`CMAKE_BUILD_PARALLEL_LEVEL`, `CTEST_PARALLEL_LEVEL`, `MAKEFLAGS`,
`GHA_SLOT_JOBS`), because `--cpus` is a quota and `nproc` still reports 24; set `cpuset` in a slot to pin it.

The image (official runner 2.338.2 + mise 2026.11.5) bakes in **sccache 0.19.0** and **uv 0.13.7**, both
installed by `mise install-into` at build time; uv is what mise's `pipx:` backend uses (cpp-utilities pins
`pipx:check-jsonschema`). A tool a feature branch adds before it is merged is not in the read-only volume, so
that job's `mise install` fails until the change reaches the default branch.

## Tested on the PC (2026-11-10 00:30–00:50, not registered with GitHub)

- `gha-slot smoke cpp-utilities|glaze`: uid 1001, CapEff 0, NoNewPrivs 1, sudo denied, no Docker socket, memory
  limit applied, **tools volume read-only, sccache volume writable**, mise 2026.11.5, sccache 0.19.0, runner 2.338.2.
- `gha-slot warm cpp-utilities <checkout>`: installed cmake 4.4.5, ninja 1.13.2, pkl 0.33.0, vcpkg-tool
  2026-10-29, pipx:check-jsonschema 0.38.2 (first try failed without uv; uv added to the image).
- Job-shaped run (`gha-slot exec`): fresh clone, `mise trust && mise install` exits 0 ("all tools are
  installed"), cmake/vcpkg/check-jsonschema work, writing to `/cache/mise` fails, a second identical compile is
  an sccache hit.
- `gha-slot wipe glaze` removes both volumes and the age stamp; `dry-run` shows repo scope and app `main`.

## Owner decisions 2026-11-10 (to build next)

- GitHub App: repo-level runners, App installed on the 4 repos only (Administration R/W). Keep runner.json
  flexible for org-level runners and a second App later (per-slot `scope` and `app`).
- Cache: tools read-only to jobs (a trusted pre-job step installs the repo's mise tools from the default branch),
  **sccache** (not ccache) as the only writable cache, weekly wipe.

## Open before registering

- Cache tamper risk: **decided and built** (read-only tools from a trusted step, writable sccache only, weekly
  wipe). Remaining, accepted: a bad job can still poison sccache objects for that repo until the next wipe.
- **GitHub App permissions** (owner creates the App): repo-level runners need the repository permission
  *Administration: read & write* (broad: repo settings); org-level runners need only the organization permission
  *Self-hosted runners: read & write*, but on the Free plan every org runner sits in the default group, so public
  repos must be allowed into it. To choose with the owner.
- H1 recall serial/riser check (owner), workflows: `runs-on: [self-hosted, <pc-label>, container, <repo>]`, only on
  `push` / `workflow_dispatch` / `schedule`, `permissions: contents: read`, never `pull_request_target`.
- Weekly image rebuild timer; the private repository's VM slot.

## Job containers: no --privileged

No job container on this PC runs with `--privileged`: a privileged container that runs `apt` can apply its image's
kernel settings to the PC itself (it happened on 2026-11-16). A job that needs a device or a capability gets that one
thing: `--device <path>`, a CDI device such as `--device nvidia.com/gpu=all`, or `--cap-add <capability>`. A
container that runs `apt` also sets `-e container=docker`, which makes procps' post-install script skip its
`sysctl --system`. `mise run pc:doctor` fails while a privileged container is running and names it and its image.
