---
name: ubuntu-certify
description: Run the Ubuntu 26.10 amd64 C++ environment certification (docs/standard/ubuntu.md) in its container on the PC's Docker, read the PASS/FAIL/N/A report, and refresh the committed baseline. Use it whenever someone asks to certify, check, verify or re-run the Ubuntu or Linux playbook or checklist, asks "is the Linux container ready for C++", "is the container near native", "what is failing on Ubuntu", after any change to the image (ubuntu-cert.Dockerfile, its pins or tool lock), the p2996 build inputs (docs/standard/ubuntu-p2996/), the docker run flags, or the PC's Docker or kernel, and before calling the Linux environment done.
---

# Ubuntu certification

`docs/standard/ubuntu.md` is the playbook: one check per item (A1 to V6),
each with a probe and a PASS rule. It runs in an Ubuntu 26.10 amd64 container
on the PC's Docker; the PC's own OS is Omarchy, so kernel-dependent lines say
`[host kernel]`. Three mise tasks:

| Task | Runs on | Does |
|---|---|---|
| `certify:ubuntu-image` | the PC's Docker | builds `docs/standard/ubuntu-cert.Dockerfile` (the setup; exact apt pins, `mise install --locked` from `docs/standard/ubuntu-cert-tools/`) |
| `certify:ubuntu` | the Mac, reaching the PC over ssh | starts the container with the playbook's flags, runs the probes, prints the report |
| `certify:ubuntu-probes` | inside the container (hidden) | the checks themselves; `certify:ubuntu` copies it in |

The probe sources (refl.cpp, san.cpp, fuzz.cpp, dap.cpp, dap_probe.py,
bench.cpp, heavy.cpp, the CMake probe) are extracted from the playbook's
appendix at run time: edit them there. The certification installs nothing
and changes nothing on the PC host (playbook rule 4).

## Reaching the PC

Both tasks need `CERT_UBUNTU_SSH`, the ssh destination of the PC: its
tailnet name or an ssh alias for it, as in `ssh <destination>` from the Mac.
It is set per command, never committed (the repository is public):

```bash
export CERT_UBUNTU_SSH=<the PC's tailnet name or ssh alias>
```

Without it the tasks exit 2 with `certify: set CERT_UBUNTU_SSH to the ssh
destination of the Docker host (the PC)`. Docker commands go to the PC
through `DOCKER_HOST=ssh://$CERT_UBUNTU_SSH`; nothing builds or runs on the
Mac.

## Run it

From the repository root, on the Mac:

```bash
mise run certify:ubuntu-image                                  # once, or after an image change
MISE_AUTO_INSTALL=0 mise run certify:ubuntu --allow-fail                           # the full report, without V6
MISE_AUTO_INSTALL=0 mise run certify:ubuntu --allow-fail --ab                      # also V6, the host-vs-container A/B
MISE_AUTO_INSTALL=0 mise run certify:ubuntu --only DB,P4 --allow-fail              # one section or a few checks
MISE_AUTO_INSTALL=0 mise run certify:ubuntu --allow-fail --keep                    # keep the container and scratch dir
```

Without `--allow-fail` the task exits 1 when any check fails. `--only` takes
ids or prefixes (`DB` is DB1 to DB5). A full run with `--ab` takes about 15
minutes; most of it is the timing checks. Other exit codes: 2 for a run
without `MISE_AUTO_INSTALL=0` (a plain `mise run` can install a missing tool
on the Mac before the task starts), an unset `CERT_UBUNTU_SSH`, an image that is not on the PC (`--image`), or an `--only`
that matches no check; 3 when the Mac's mise installs changed during the run
(the report's `mise installs (this Mac):` line names the change), even with
`--allow-fail`.

## Refresh the baseline

```bash
MISE_AUTO_INSTALL=0 mise run certify:ubuntu --allow-fail --ab --out docs/standard/reports/ubuntu-pc-$(date +%F).txt
git diff --no-index docs/standard/reports/ubuntu-pc-2026-11-15.txt docs/standard/reports/ubuntu-pc-$(date +%F).txt
```

The report masks the Mac's home as `~`, the account as `<user>` and the ssh
destination as `<pc>`, and labels the machine `pc`. A PASS that turns FAIL
is a regression; a FAIL that turns PASS needs the playbook's "Usable today"
table and the check's text updated in the same change.

## What it leaves on the PC

Kept on purpose, labelled `org.cpp-standard.cert=1`:

- image `cpp-standard-cert-ubuntu:26.10`. apt.llvm.org deletes its old
  snapshots within days (D12), so this image is the record of what was
  certified and may not rebuild from the same pins. Do not prune it until a
  rebuild with fresh pins exists.
- volume `cpp-standard-cert-build`: build trees (V4).
- volume `cpp-standard-p2996-<commit12>-<inputs12>`: the p2996 install,
  named after its build inputs (playbook, "Appendix: p2996 amd64 build").
  A new commit or changed input gets a new volume; an old one is never
  overwritten.
- volume `cpp-standard-sccache`: the p2996 build's sccache cache
  (`build-linux.sh`). With it, a rebuild after an input change that leaves
  the sources alone took 93 s (all 6134 compiles hit), not 45 minutes.

Everything else is removed: the run's container on exit (unless `--keep`),
and V6's `/var/tmp/cpp-standard-cert-ab` right after the A/B. List and remove
the kept ones (removing the p2996 volume means rebuilding p2996: about 2
minutes from `cpp-standard-sccache`, about 45 without it):

```bash
DOCKER_HOST=ssh://$CERT_UBUNTU_SSH docker image ls --filter label=org.cpp-standard.cert=1
DOCKER_HOST=ssh://$CERT_UBUNTU_SSH docker volume ls --filter label=org.cpp-standard.cert=1
DOCKER_HOST=ssh://$CERT_UBUNTU_SSH docker image rm cpp-standard-cert-ubuntu:26.10
DOCKER_HOST=ssh://$CERT_UBUNTU_SSH docker volume rm cpp-standard-cert-build cpp-standard-sccache cpp-standard-p2996-562409c79426-f3fb14942dd6
```

## Reading the report

- **N/A is not PASS.** G5, H1 and T1 are rules; K1 and E1 need a C++ project;
  A4, U2 and V5 are recorded facts; T6 is tier 2; U3 and U4 are timings that
  inform D137.
- **Timing lines** (`[timing]`: U3, U4, V4, V6) count only when the PC's
  other containers (the self-hosted runners) were idle. The header's
  "Timing pass" line gives their CPU time during the pass; over one
  CPU-second, a container that started or stopped during the pass, or one
  whose CPU time could not be read turns the lines into N/A `timing
  untrusted`. Rerun later; never
  stop the runners, they belong to other repositories.
- **`[host kernel]`** results are this container on the PC's Omarchy kernel,
  not Ubuntu's kernel.
- **MSan is recorded, not required** (C6): it needs an MSan-built libc++.
- The container runs `--privileged` (D137). V2 lists what narrower flags
  give, if the flags are tuned down later.

## Gotchas

- `san.cpp` and `fuzz.cpp` are the same files as in `macos.md`; change both
  playbooks together. The race in `san.cpp` loops because a one-increment
  race was caught in only some runs (C6 has the counts).
- `apt-get install iwyu` pulls in the archive clang 22 and repoints `cc`,
  `c++` and `clang++` (B2). Never add it to the image.
- GCC names a `-fprofile-generate` profile after the output file; the
  `-fprofile-use` build must use the same `-o` (U5).
- `g++-16 -fuse-ld=lld` looks for an unversioned `ld.lld`, which LLVM 23's
  packages do not install; U4 links through `clang++-23`.
- hyperfine 2.0's JSON keeps times under
  `results[].measurements[].time_wall_clock`; `hf_best.py` (written by the
  launcher) reads it.
- The image's tools come from `/opt/cpp-standard-tools` via
  `MISE_GLOBAL_CONFIG_FILE`; it never runs `mise use -g`. To change a tool,
  edit `docs/standard/ubuntu-cert-tools/mise.toml` and regenerate its lock
  inside the image with `mise lock --platform linux-x64`.
