# Hands-on: mise bootstrap on Ubuntu 26.10 (stonking), re-test of the 26.04 runs (2026-11-13)

Target (owner decision D25): base `ubuntu:26.10` (Stonking Stingray) pinned by digest, Linux GCC from the 26.10 archive, no conda, LLVM 23 from apt.llvm.org suite `llvm-toolchain-resolute-23`, valgrind from the archive, cmake 4.5.0 and ninja via mise. Experiment dir: `<research-cache>/experiments/bootstrap-2610/` (config `repo/`, scripts and all logs in `logs/`, test project in `proj/`). Host untouched; throwaway containers removed (`docker ps -a` empty); nothing pushed or posted.

- Image: `ubuntu:26.10@sha256:b5194b8e58989da0865ebc80078bf9f5f8742ec6a867c53f6ae699f6036756f7` (index digest; same for linux/arm64 and linux/amd64; amd64 manifest `sha256:8f52618638aaad6b239d47d734112b15757a22fe1a8e76ace2c402e33ed672c8`; image created 2026-11-05).
- mise: 2026.11.7 (still the latest release: `gh release list -R jdx/mise -L 3` shows v2026.11.7 on 2026-11-12), binary sha256-checked (arm64 `e4392a51...929af8`, x64 `8f5426d9...a1d`; same values as the 26.04 run).
- Config commit (local test repo): `61618e260f6f8ca034f043dd2c5f1421d12d44cc`.

## Pins (served versions, looked up 2026-11-13)

| Package | Version | Source |
|---|---|---|
| gcc-16, g++-16 | `16.2.0-3ubuntu1` | 26.10 archive, `stonking/universe` (apt-cache madison, arm64; amd64 installed the same) |
| valgrind | `1:3.27.1-0.2ubuntu2` | 26.10 archive, `stonking/main` |
| clang-23, libc++-23-dev, libc++abi-23-dev | `1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94` | apt.llvm.org `resolute` suite `llvm-toolchain-resolute-23`; Packages for arm64 and amd64 identical; Release dated 2026-11-08 22:14 UTC |
| cmake / ninja | 4.5.0 / 1.13.2 (`latest`) | mise |

`https://apt.llvm.org/stonking/dists/llvm-toolchain-stonking-23/Release` returns HTTP 404: apt.llvm.org has no suite for 26.10, so the 26.04 `resolute` suite is used on a 26.10 base (works; libc++/clang resolve against 26.10's libs).

## Commands (all in `ubuntu:26.10` containers; `/src` = read-only bind mount of `repo/`)

```sh
. logs/common.sh        # apt install curl ca-certificates git; download mise v2026.11.7, sha256sum -c; safe.directory
mise lock --platform linux-arm64,linux-x64,macos-arm64          # in a copy of mise.toml (logs/s1.sh)
mise bootstrap --from "file:///src?ref=61618e26..." --yes       # as root (logs/s3.sh)
mise bootstrap --from "file:///neg/fp?ref=..." --yes --skip tools   # negative checks (logs/s4.sh)
mise bootstrap --skip tools --yes                               # in /etc/mise with mise.toml + mise.lock (logs/s5.sh)
MISE_DATA_DIR=/tmp/fresh mise install --system --locked && mise reshim --system     # arm64
mise install --system --locked && mise reshim --system                              # amd64 (no data-dir override)
chmod 644 /etc/mise/mise.lock
su dev -c 'PATH=/usr/local/share/mise/shims:$PATH ...'          # cmake/ninja/g++-16/clang++-23/C++23/import std (logs/run.sh in s5.sh)
MISE_EXPERIMENTAL=1 mise oci build                              # logs/s6.sh, s6b.sh
```

Test project (`proj/`): `CMakeLists.txt` with `cmake_minimum_required(VERSION 4.2)`, `CMAKE_CXX_STANDARD 23`, `CMAKE_CXX_MODULE_STD ON`, `main.cpp` (`import std; import hello;`), `hello.cppm` (`export module hello; import std;`); clang-23 configured with `-DCMAKE_CXX_FLAGS=-stdlib=libc++`, g++-16 with no flags, `-G Ninja`.

## Results

| # | Step | arm64 (native) | amd64 (QEMU) |
|---|---|---|---|
| 1 | Pins looked up | OK (table above) | Packages identical; archive versions installed identically |
| 2 | `mise lock --platform linux-arm64,linux-x64,macos-arm64` | OK, 0.4 s, **49 lines**, 2 tools (cmake 4.5.0, ninja 1.13.2), no apt/brew/bootstrap content; file written mode 600 | not re-run (same lock used) |
| 3 | `bootstrap --from file:///src?ref=<sha> --yes`, root | rc 0, 1m27s | rc 0, 2m11s (ran concurrently with other work) |
| 3a | apt source | `/etc/apt/sources.list.d/mise-llvm.sources` written ("Written by mise for [bootstrap.apt.sources.llvm]"), `mise apt: added source llvm (https://apt.llvm.org/resolute/)` | same |
| 3b | apt pins | ONE call: `apt-get install -y -- gcc-16=16.2.0-3ubuntu1 g++-16=... clang-23=... libc++-23-dev=... libc++abi-23-dev=... valgrind=1:3.27.1-0.2ubuntu2`; no apt preferences file written (pins are `name=version` only); dpkg shows exactly the pinned versions | same |
| 3c | `brew:jq` os=macos | skipped silently, no brew output | same |
| 3d | tools phase | ninja 1.13.2, cmake 4.5.0 installed to root's data dir; `mise ls` lists both | same |
| 4 | Negative: wrong fingerprint | rc 1 (see below) | not run |
| 4 | Negative: wrong version | rc 1 (see below) | not run |
| 5 | `--skip tools` then `install --system --locked` + `reshim --system` | OK; with `MISE_DATA_DIR=/tmp/fresh` install 10.4 s | OK **without** data-dir override, install 17.2 s |
| 5 | non-root `dev`: `cmake --version` | 4.5.0, ninja 1.13.2, cmake resolves to `/usr/local/share/mise/shims/cmake` | same |
| 5 | g++-16 / clang++-23 versions | `g++-16 (Ubuntu 16.2.0-3ubuntu1) 16.2.0`; `Ubuntu clang version 23.1.6 (++20261108033809+c47d7823685a-1~exp1~20261108153913.94)` | same |
| 5 | C++23 `<print>`/`<expected>` | g++-16 and clang++-23 `-stdlib=libc++` both print `hi 42 202302`; clang binary links libc++.so, no libstdc++ | same |
| 5 | CMake 4.5 `import std` + Ninja | clang-23+libc++: OK `hello module 42 202302`; g++-16 (libstdc++): OK `hello module 42 202302`. No module errors, no experimental flag | same, both OK |
| 6 | `MISE_EXPERIMENTAL=1 mise oci build` | fails (see below) | not run |

Module manifests found (arm64): `/usr/lib/aarch64-linux-gnu/libc++.modules.json`, `/usr/lib/llvm-23/lib/libc++.modules.json`, `/usr/lib/gcc/aarch64-linux-gnu/16/libstdc++.modules.json` (and a 15 one).

## Verbatim messages

- Wrong fingerprint (`6084 F3CE...`), exit 1:
  `mise ERROR apt source llvm (https://apt.llvm.org/resolute/)` / `mise ERROR llvm: the key at https://apt.llvm.org/llvm-snapshot.gpg.key does not have fingerprint 6084F3CE814B57C1CF12EFD515CF4D18AF4F7421 (found: 6084F3CF814B57C1CF12EFD515CF4D18AF4F7421)` / `mise ERROR bootstrap from repository failed with exit status: 1`
- Wrong version (`ubuntu9`, `...153913.95`), exit 1: `E: Version '16.2.0-3ubuntu9' for 'gcc-16' was not found`, `E: Version '1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.95' for 'clang-23' was not found` (and the same for g++-16, libc++-23-dev, libc++abi-23-dev), then `mise ERROR apt-get exited with non-zero status: exit code 100`, `mise ERROR bootstrap from repository failed with exit status: 1`. Note valgrind (unchanged pin) was reported as `mise apt: 1 package(s) already installed`.
- Re-using `~/.local/share/mise/bootstrap-repo` for a different `--from` repo: `mise ERROR ~/.local/share/mise/bootstrap-repo has origin "file:///src", expected "file:///neg/fp"` (my test needed `rm -rf` of that dir between runs).
- Lockfile permissions, as `dev` when `/etc/mise/mise.lock` is mode 600 (the mode `mise lock` writes): `mise WARN  failed to read lockfile /etc/mise/mise.lock (possible corruption): ... Permission denied (os error 13)` on each shim call; commands still ran. After `chmod 644` (both arches) no warning.
- `oci build` without experimental: `mise ERROR mise oci build is experimental. Enable it with \`mise settings experimental=true\``.
- `oci build` config: apt.sources llvm + `"apt:clang-23" = "<pinned>"`, `[tools] ninja = "1.13.2"`, `[oci] from = "ubuntu:26.10"`. First run with MISE_EXPERIMENTAL=1 and ninja not yet installed: `mise ERROR ninja@1.13.2 install path does not exist: /root/.local/share/mise/installs/ninja/1.13.2. Run \`mise install\` first.` After `mise install ninja`: `mise pulling base image: ubuntu:26.10`, two `apt-get -c .../mise-oci.conf -o Dir=/tmp/mise-oci-apt-rootfs-XXXX/rootfs ...` lines, then `mise ERROR apt-get failed while installing OCI system packages: exit status: 100` / `E: Unable to locate package clang-23`. Same failure as on 26.04.

## What changed vs the 26.04 runs

- Base 26.10 (digest above); GCC is now apt `g++-16`/`gcc-16` 16.2.0-3ubuntu1 (libstdc++-16-dev, with `libstdc++.modules.json`), conda removed; system-default gcc is still 15 (pulled as dependency) but `g++-16` is called explicitly.
- apt.llvm.org has no 26.10 suite: cross-release `resolute` suite works. Same clang build string as the 26.04 run (1:23.1.6~...94; the snapshot had not rotated since 11-08).
- valgrind 1:3.27.1-0.2ubuntu2 (was 1:3.26.0-0ubuntu1).
- Lock shrank 465 -> 49 lines (no conda packages).
- Bootstrap 1m27s arm64 (was 1m46s), 2m11s amd64 (was 2m28s).
- `--skip tools` + plain `install --system --locked` WORKS without a fresh `MISE_DATA_DIR` (amd64; was untested). The mode-600 `mise.lock` warning was re-confirmed and is now explained: `mise lock` writes mode 600.
- `import std` with CMake 4.5 works with `CMAKE_CXX_MODULE_STD ON` for both clang-23+libc++ and g++-16+libstdc++ (apt libstdc++, not conda).
- `mise oci build` failure identical; additionally it requires tools to be installed first.

## Untested

- amd64: lock generation, negative checks, `oci build`. arm64: `--skip tools` + plain `--system` install without data-dir override (done on amd64 only).
- "Already installed / empty shims dir" trap (bootstrap installing tools to root first, then `install --system`) not repeated on 26.10; remains from the 26.04 run. Non-root access to root-installed tools not repeated (`/root` is mode 700 on 26.10, checked with stat).
- Why oci build omits the source (rootfs not inspected); `--copy`/custom base image workaround.
- macOS bootstrap, `--update`, idempotency (a second `--skip tools` bootstrap printed `mise apt: 6 package(s) already installed`), HTTPS git URL, valgrind run, mixing libc++ and libstdc++ objects.
- Native amd64 timing; image size.

## Tools

Ran: docker 29.9.3, gh (release list), curl/zcat inside containers, mise 2026.11.7 in containers only, git (inside containers). Not used: Exa, Firecrawl, Context7. No failed tool routes except my own script slips (unbound `PLAIN` under `set -u`, a `sed -i` BSD syntax error, cwd of `su dev`), fixed and re-run; logs `arm-s5-system.log` (aborted) and `arm-s5b-system.log` kept.
