# The PC's GitHub runner: one-job container slots

Owner decisions (2026-11-09): runner for one private repository, glaze, cpp-utilities and dotfiles (org
`ray-manaloto`); **public repos run in one-job containers (this directory)**, the private one in one-job libvirt VMs (later,
after the KVM packages land via dotfiles); GitHub App auth; every tuning value in one config file; Eco mode plus
per-slot CPU limits.

## Files (installed on the PC)

| Source here | On the PC | What |
|---|---|---|
| `gha-slot` | `/usr/local/sbin/gha-slot` | slot add / build / smoke / exec / warm / wipe / dry-run / once / run |
| `gha-slot@.service` | `/etc/systemd/system/` | one loop per slot: `systemctl enable --now gha-slot@glaze.service` |
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

## Adding a repository

Run these on the PC as root, in order. Slots register **org-scope** runners in the org's Default runner group, which
runs jobs only for the repositories it allows (owner decision 2026-11-18: the App has no Administration permission,
so repo-scope registration is not available). Labels are not access control: any repository the group allows can
send a job to any slot by naming its label, and that job gets the slot's writable sccache. Allow only trusted
repositories in the group.

1. Allow the repository in the org's Default runner group (GitHub: org settings > Actions > Runner groups > Default).
2. `gha-slot slot add <repo> [--name <slot>] [--cpus N] [--memory SIZE] [--scope org|repo] [--label L]...
   [--group-verified]` adds the slot to `runner.json` with scope `org` unless `--scope repo` is given. Slot names are
   lowercase letters, digits, `_` and `-` (no dots, so a name never ends in `.service`). Before writing it refuses an
   existing slot name, and refuses while a `gha-tools-<slot>` or `gha-sccache-<slot>` volume from an earlier slot of
   that name still exists. For org scope it asks GitHub, read-only with the App token, whether the Default runner
   group is set to selected repositories, lists the repo, and allows public repositories if the repo is public; it
   refuses if not, and it also refuses when it cannot ask (fail closed). After checking all of that by hand in the
   org's settings, rerun with `--group-verified` to skip the GitHub check. All of these checks run under one lock
   (a read-only descriptor on `/etc/gha-runner` itself), which it holds while it writes the new file to a temp file,
   checks that it is non-empty and parses, dry-runs the new slot against it in a fresh process, backs the old file
   up as `runner.json.bak-<sha256>` (verified), keeps the owner and mode, and replaces the file in one rename. Any
   failure leaves the file untouched. Never edit `runner.json` with an unchecked pipe: on 2026-11-18 a `jq … | tee`
   edit without `pipefail` wrote an empty file.
3. `gha-slot smoke <slot>` checks the job container's limits (no GitHub, no repo code).
4. **Run the repo's CI test commands in the runner image before any workflow moves.** For a public repo:
   `gha-slot exec <slot> 'git clone --depth 1 https://github.com/<owner>/<repo> r && cd r && mise trust -q -a &&
   mise install && <the CI test commands>'`. The image is Ubuntu 24.04 with a usr-merged `PATH`, so tests that pass
   on macOS can still fail here. One repository's ship-cleanup test did, and fixing it took a second pull request
   after its CI had already moved. `exec` gets no token, but it mounts the slot's tools volume read-only and its
   sccache volume **writable**, exactly like a job, so run only code you would let a job run. A private repo cannot
   be cloned without a token, so gha-slot cannot yet run this step for one.
5. `gha-slot warm <slot>`: a trusted step that gets an App installation token, clones the repo's **default branch**
   with it and installs its mise tools into the tools volume.
6. Switch the repo's workflows to `runs-on: [self-hosted, <pc-label>, container, <slot>]`, then
   `systemctl enable --now gha-slot@<slot>.service`.

**Retire a slot** (manual, as root; there is no `slot remove`). Replace `<slot>` in each line. The `flock` takes the
same directory lock as `slot add`; the edit backs up, checks and renames the same way.

```sh
systemctl disable --now gha-slot@<slot>.service
systemctl show gha-slot@<slot>.service -p UnitFileState -p ActiveState  # must say disabled and inactive
flock -n /etc/gha-runner sh -euc '
  cd /etc/gha-runner
  sum=$(sha256sum runner.json | cut -d" " -f1)
  cp -p runner.json "runner.json.bak-$sum"
  cmp runner.json "runner.json.bak-$sum"
  umask 077
  jq --arg n "<slot>" "del(.slots[\$n])" runner.json > runner.json.new
  test -s runner.json.new
  jq -e --arg n "<slot>" ".slots | has(\$n) | not" runner.json.new
  mv -T runner.json.new runner.json'
docker volume rm gha-tools-<slot> gha-sccache-<slot>
```

Remove the volumes before that slot name is used again (`slot add` refuses while they exist). Do not start the
slot while it is being retired.

**Offboard a repository:** retire each of its slots as above, then remove the repository from the org's Default
runner group (GitHub: org settings > Actions > Runner groups > Default) and check that it is no longer listed there.
Until then it can still send jobs to the other slots by their labels.

## Owner decisions 2026-11-10 (to build next)

- GitHub App: repo-level runners, App installed on the 4 repos only (Administration R/W). Keep runner.json
  flexible for org-level runners and a second App later (per-slot `scope` and `app`). **Superseded 2026-11-18:**
  org-scope runners, limited to the selected repositories of the org's Default runner group; the App has no
  Administration permission.
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

## Dedicated amd64 compiler cache

The coordinator dispatches `pc-compiler.yml` from protected main to group 6 on
`nzxth1desktop`. The host launcher admits the assignment before opening its
private store under `/var/lib/gha-runner/cpp-standard-amd64`. Each workload
uses an unprivileged container. The root-owned store survives workload cleanup.
The listener can read the specific run's results and staged publication files.

| Layer | Reuse and invalidation | Evidence |
| --- | --- | --- |
| Installed p2996 and matching IWYU | Select the local package by the full SHA-256 of the actual compiler inputs. The key covers linux/amd64, base and donor image IDs, both source pins, recipe and patches, the bootstrap compilers, linker, CMake, Ninja, sccache and installed build dependencies. Project source can change independently. Verify the compressed archive digest and embedded full input identity before installation. | `compiler-inputs.json`, `compiler-cache.txt`, `compiler-package.json` and the Clang and IWYU version checks in `build.log`. |
| Compiler objects | The LLVM build and each fresh project container share a bounded 40 GB sccache on the PC. The top-level LLVM build and its nested C and C++ runtime builds inherit the locked launcher. Each project preset also configures sccache. The listener and the quiet certification windows have no persistent-cache mount. | On a cold compiler build retain `compiler-sccache.json`. For each native preset retain `sccache.json`, the CMake cache and compilation database. Report cache hits, misses and non-cacheable requests as measured. |
| mise downloads | The fresh bootstrap and locked cert profile share mise's 10 GiB content-addressed download store. The pinned mise release archive is also retained by SHA-256 and checked before each extraction. Project installs and cert shims remain separate. Locked installs verify the expected checksum. | Read the release hit/store line, digest check and before/after store sizes in `build.log`. Sizes show occupancy. An offline installation into a fresh data directory can demonstrate a download hit. |
| Python tool wheels | The locked gcovr graphs in the project and cert profiles use a shared, private uv cache. uv copies wheels into each fresh environment. | Compare the frozen inputs and installed versions. A second offline sync of the same lock into a fresh environment demonstrates reuse. [mise frozen install](https://github.com/jdx/mise/blob/v2026.11.9/src/backend/pipx/lock.rs#L910-L928) · [uv cache directory](https://docs.astral.sh/uv/concepts/cache/#cache-directory) |
| Package downloads | APT retains acquired archives and verifies signed repository metadata. vcpkg reuses its download directory and configures the dependencies for the actual preset triplet. The presets retain `VCPKG_BINARY_SOURCES=clear`. | See the signed APT bootstrap log, vcpkg package status and real project CTest reports. |

On a local compiler miss, the host looks up
`ghcr.io/ray-manaloto/cpp-standard/tools:p2996-pc-linux-amd64-<first-16-hex>`.
It verifies the immutable OCI digest against the protected publisher attestation,
checks the payload and compares the full embedded key before use. A service,
authentication, integrity or attestation error fails the attempt. A confirmed
miss asks for a verified prior compiler or the reason a new source build is needed.
[Verified mise downloads](https://github.com/jdx/mise/blob/v2026.11.9/docs/continuous-integration.md#L73-L105)

Use the ordinary `gha-slot compiler-once RUN MAIN_SHA --group-verified` launch
for a cache consumer. Append `--seed-run PRIOR_RUN` for migration from a retained
PC build. The host checks the prior build exit, assignment, exact image ID and
owner, archived recipe, original file hashes and its installed build inputs.
Append `--source-change "reason"` only for a necessary compiler input change
or diagnosed compiler defect. A valid existing package still takes precedence.
The host retains a verified package before the downstream checklist or project
verdict. A seeded or cold run stages the OCI payload. For an existing local
package, `--stage-package` stages it again for recovery of an expired upload.
The coordinator dispatches the existing protected `publish.yml` with that run's
ID. Record the package tag, digest and verified attestation after publication.

To check mise download reuse in isolation, select one HTTPS tool with its
platform checksum in the lockfile. Install it with `mise install --locked TOOL`
into an empty data directory and record the checksum and download-store entry.
Use a second empty data directory, the same download store and
`MISE_OFFLINE=1`. The install must succeed with identical bytes. An empty
store under the same offline conditions must fail. After eviction, an online
locked install can fetch the expected bytes again. If verification fails,
record the digest, isolate the bad entry and reacquire the pinned artifact
before retrying. Use scratch directories for these checks.

For a runtime reuse claim, retain the following in ordinary run receipts.

- Compare two distinct protected project checkouts with equal full compiler input and package digests. The consumer log identifies the source and skips the LLVM configure and Ninja build. Include the producer run or registry digest.
- For each checkout, record the project image ID, then configure, build and run CTest on each of `gcc16-coverage-amd64`, `clang23-coverage-amd64` and `p2996-coverage-amd64`. Each must execute both `standin_test` and `core_test` with zero skipped or failed. Preserve the compiler, triplet, stdlib, runtime and applicable hardening evidence.
- Check that a real patch, compiler or dependency input change selects a new key. Record the measured object-cache counters separately from the whole-package hit. Unsupported compile modes can produce non-cacheable requests. Retain the fresh quiet-window and teardown evidence for the run.
