---
name: ubuntu-arm64-run
description: Build, launch and drive the certified Ubuntu 26.10 arm64 C++ container in this Mac's Docker Desktop (native Apple silicon, no emulation) with `mise run ubuntu:arm64`. Use it whenever someone asks to run, open, enter, shell into, smoke-test or try something in the arm64 / Apple-silicon / Mac Ubuntu container, to compile or run code with its p2996 (reflection), clang 23, GCC 16 or flang on Linux arm64, or to check that the arm64 image and its p2996 volume still work after a change. For the PASS/FAIL certification itself use ubuntu-certify.
---

# Run the Ubuntu 26.10 arm64 container

The container is the arm64 half of `docs/standard/ubuntu.md`: the image
`cpp-standard-cert-ubuntu:26.10`, built from
`docs/standard/ubuntu-cert.Dockerfile` in the Mac's Docker Desktop, plus the
p2996 install in the volume `cpp-standard-p2996-<commit12>-<inputs12>`,
mounted read-only at `/opt/p2996` (`$P2996` in the container). The harness is
`.mise/tasks/ubuntu/arm64`; every call starts a fresh `--rm` container with
the playbook's flags (`--privileged`, D137).

The Mac is shared by many agents. Launching and driving is light; building
the image or p2996 is heavy and runs only in a load window agreed with
chief-of-staff (cpp-standard-lead asks for it).

## Setup (once, heavy)

```bash
docker version -f '{{.Server.Arch}}'          # -> arm64 (Docker Desktop running)
mise run certify:ubuntu-image --local         # the image, natively, 4 ninja jobs: about 10 min
```

The p2996 volume: the playbook's "Appendix: p2996 build", in a container
capped at `--cpus 4 --memory 16g` with `build-linux.sh /work /opt/p2996 4`
(about 76 min cold). Without the image or the volume the harness exits 2 and
says which is missing.

## Launch and drive

Smoke test: one program per compiler, exit 1 if any fails:

```bash
mise run ubuntu:arm64 --smoke
# -> aarch64; Ubuntu clang version 23.1.6 (...); g++-16 (Ubuntu 16.2.0-3ubuntu1) 16.2.0; clang version 21.0.0git (.../clang-p2996 562409c...)
# -> ok   members=2     (p2996, -freflection-latest)
# -> ok   hello         (clang 23 with libstdc++, then with libc++)
# -> ok   hello         (GCC 16)
# -> ok   hello         (flang)
```

Run a command in the directory you called mise from, mounted read-write
at `/work` (pass the whole command as one quoted string; `-C` points mise at
the repository from elsewhere):

```bash
cd <your project> && mise -C <cpp-standard checkout> run ubuntu:arm64 'g++-16 -std=c++26 w.cpp -o w && ./w && uname -m'
# -> from /work
# -> aarch64
```

Interactive shell (needs a terminal; from an agent, drive it through a
herdr tab or `script -q /dev/null`):

```bash
mise run ubuntu:arm64 --shell
```

`CERT_P2996_VOL=<volume>` mounts another p2996 volume, as in
`certify:ubuntu`. `--image <ref>` picks another image.

## What differs from the PC (amd64)

- No NVIDIA GPU reaches Docker on the Mac: GPU offload compiles (the CUDA
  `linux-sbsa` toolkits are in the image) but does not run; GO1-GO3 are N/A.
- No hardware PMU in Docker Desktop's VM: `perf stat` hardware events fail;
  `perf record -e cpu-clock` works. Callgrind (R7) works.
- The VM hides the CPU model: `-mcpu=native` says `generic`. Name the target
  (`-mcpu=apple-m2`, `-march=armv8.6-a`).
- compiler-rt has no `memprof` or `nsan` on AArch64.
- A libc++ hardening trap ends with SIGTRAP (exit 133), not SIGILL (132).

## Clean up

The harness leaves nothing but what the command wrote to `/work`. Kept on
purpose: the image and the volumes `cpp-standard-p2996-…` and
`cpp-standard-sccache`. Never `docker system prune` on the shared Mac; list
what is labelled `org.cpp-standard.cert=1` and remove by name.
