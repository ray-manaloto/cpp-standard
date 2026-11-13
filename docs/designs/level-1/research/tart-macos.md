# Tart for simulating a fresh-Mac bootstrap

Date: 2026-11-13. Read-only research. Nothing installed, no image pulled, no config changed.
Offline copies: `<research-cache>/docs/tart/` (docs, license, blog, Orchard, integrations, and the Packer templates in `macos-image-templates/`). Shallow clone: `<research-cache>/repos/tart` (HEAD c20da4f, 2026-11-06).

## 1. Current state

- Version: latest release 2.41.1 (2026-10-15); 2.41.0 on 2026-10-13; releases are frequent (2.38 on 09-24, 2.39 on 09-26, 2.40 on 09-28). Source: `gh release list -R openai/tart`, `mise ls-remote tart`. Last push to the repo 2026-11-12. About 7.9k stars.
- Owner: the repo is `openai/tart`. Cirrus Labs joined OpenAI on 2026-04-07 (MacStadium summary: https://macstadium.com/blog/cirrus-labs-is-joining-openai). That post says Cirrus CI shut down on 2026-06-01, Cirrus Runners closed to new customers, and the dedicated team moved on, so maintenance is by whoever contributes. The repo is still active (top committers edigaryev, fkorotkov, plus OpenAI staff such as yzhuang-oai), so this looks maintained at present. Long-term support is UNVERIFIED.
- License (changed 2026-06-05, PR https://github.com/openai/tart/pull/1238): `LICENSE` is "Functional Source License, Version 1.1, ALv2 Future License" (FSL-1.1-ALv2), copyright 2022-2026 OpenAI. The old Fair Source 100-core limits are gone; the repo's own docs say so: "As of June 5, 2026, Tart is maintained by OpenAI and licensed under FSL-1.1-ALv2. The usage limits, paid tiers, pricing, support commitments, and contact details described below no longer apply." (docs/blog/posts/2023-02-11-changing-tart-license.md).
  Key text: "A Permitted Purpose is any purpose other than a Competing Use. A Competing Use means making the Software available to others in a commercial product or service that: 1. substitutes for the Software; 2. substitutes for any other product or service we offer using the Software ...; or 3. offers the same or substantially similar functionality as the Software." "Permitted Purposes specifically include using the Software: 1. for your internal use and access; 2. for non-commercial education; 3. for non-commercial research; and 4. in connection with professional services...". Each release converts to Apache-2.0 "on the second anniversary of the date we make the Software available".
  Reading for us: using Tart internally to test a C++ bootstrap is a Permitted Purpose (internal use). No CPU-core or personal/org cap remains. I am not a lawyer; the owner can see the open clarification thread https://github.com/openai/tart/issues/1272 (Cirrus maintainer reply: you are fine "unless you are a large AI Lab working on SOTA models").
- Install routes:
  - Homebrew: `brew install openai/tools/tart` (README, quick-start). Formula in https://github.com/openai/homebrew-tools (Formula/tart.rb, v2.41.1, license "FSL-1.1-ALv2", depends on `openai/tools/softnet` and macOS Ventura+). It is NOT in homebrew-core or cask (`brew info tart` fails locally). The old tap `cirruslabs/cli/tart` is broken on current Homebrew (https://github.com/openai/tart/issues/1394, open); the openai tap works.
  - mise: `mise registry tart` gives `aqua:openai/tart` (checked locally, mise 2026.11.7). `mise ls-remote tart` lists up to 2.41.1. The aqua entry installs the asset `tart.tar.gz` and exposes `tart.app/Contents/MacOS/tart` with sha256 checksums. The docs warn the binary inside `tart.app` must be the one executed, because macOS picks up `tart.app/Contents/embedded.provisionprofile` for the entitlements Tart needs. Whether mise's shim/symlink keeps that working is UNVERIFIED (test it after approval). The Homebrew formula also pulls `softnet` (only needed for `--net-softnet`).
  - Manual: `curl -LO https://github.com/openai/tart/releases/latest/download/tart.tar.gz`.

## 2. Images

All from `ghcr.io/cirruslabs/...`, anonymous pull works. I read only registry manifests (no layers) with the ghcr token endpoint and `curl`.

- macOS versions: the quick-start page lists Tahoe (26), Sequoia (15), Sonoma (14), Ventura (13), Monterey (12) as vanilla/base/xcode. It does NOT list macOS 27, but the registry has it under the codename "golden gate": `macos-golden-gate-vanilla` with tags `latest`, `27.0`, `27.2`. The Packer template `vanilla-golden-gate.pkr.hcl` builds from `UniversalMac_27.2_26B123_Restore.ipsw`. An xcode image `macos-golden-gate-xcode:latest` exists (issue 1420). This Mac reports Darwin 27.2.0, so a 27.2 guest matches the host.
- Variants (macos-image-templates README, https://github.com/cirruslabs/macos-image-templates):
  - vanilla: "a vanilla macOS installation with helpful tweaks such as auto-login, but no additional software preinstalled".
  - base: vanilla plus Homebrew and tools: `brew install wget unzip zip ca-certificates cmake gcc git-lfs jq yq gh gitlab-runner`, mise, rbenv, node@24, awscli, Rosetta, GitHub Actions runner. NOT fresh for us: it already has Homebrew, cmake and gcc.
  - xcode: base plus Xcode (and Flutter).
- Is vanilla fresh? I read `templates/vanilla-tahoe.pkr.hcl` and `vanilla-golden-gate.pkr.hcl`: no `brew`, no `xcode-select`, no Command Line Tools install step. They only create the `admin`/`admin` user with passwordless sudo, enable auto-login and Remote Login (SSH), disable Gatekeeper (`spctl --global-disable`), disable sleep/screensaver, enable Screen Sharing, and run safaridriver. So Homebrew and CLT are absent (matches a fresh Mac), with two differences from a real fresh Mac: Gatekeeper is disabled, and the account is pre-created with auto-login. Vanilla images also have no Tart Guest Agent, so `tart exec` does not work there (the blog says the agent is in "all non-vanilla Cirrus Labs images"); use SSH. I did not boot one, so "no CLT" is from the template, not observed (UNVERIFIED).
- Sizes (manifest sums, compressed layers): golden-gate-vanilla 27.2 = 30.0 GB compressed, 68 layers, 35.1 GB uncompressed disk-size annotation; tahoe-vanilla latest = 24.0 GB compressed (50 GB disk); tahoe-base latest = 27.1 GB compressed (50 GB disk). The docs say "will download a 25 GB image". Plan roughly 30 GB download plus about 35-50 GB of disk per cached image, plus each clone.
- Pinning by digest: yes, OCI. Current digests (2026-11-13): `macos-golden-gate-vanilla:latest` sha256:b35695ce30453bcc1db961a476740be72a44c2a2e464b73ece1ff0fcac12a873 (same as tag 27.2); `macos-tahoe-vanilla:latest` sha256:eeec54bfe1f076e27786c5d92b89187a05b1d109b5071eb2dcdf02d596e34640; `macos-tahoe-base:latest` sha256:65c3133a633fda8753cf1f71f2d55727792d534a2125b0032466563dcc8e58fd. Use `tart clone ghcr.io/cirruslabs/macos-golden-gate-vanilla@sha256:...` (digest references are supported by Tart's OCI FQN parser per `Sources/tart/Commands/FQN.swift`; I did not run it, UNVERIFIED). The vanilla image is rebuilt monthly or per OS point release, so pin a tag like `:27.2` or the digest, never `:latest`.
- Tart caches pulled images in `~/.tart/cache/OCIs/`, local VMs in `~/.tart/vms/`; `TART_HOME` relocates it. Auto-prune of cached images is on by default (`TART_NO_AUTO_PRUNE` disables it).

## 3. Workflow to test our bootstrap

Commands from the docs (quick-start.md, faq.md); none executed.

1. `brew install openai/tools/tart` (or `mise use -g tart`).
2. `tart clone ghcr.io/cirruslabs/macos-golden-gate-vanilla:27.2 fresh-mac-27` then `tart set fresh-mac-27 --cpu 6 --memory 12288 --disk-size 80` (default is 2 CPU, 4 GB; the Packer templates use 4 CPU, 8 GB, 50 GB disk). A source build of gcc 16 and llvm needs more RAM and disk than defaults. Stacked clones (`tart clone --stacked`) work only on macOS 27+ hosts and only from a remote standalone OCI image; they keep the base read-only and write a small overlay, which would save disk (faq.md, "Stacked disk images"). It is new, so treat as UNVERIFIED.
3. Run headless: `tart run --no-graphics fresh-mac-27 &` (flag confirmed in `Sources/tart/Commands/Run.swift`). Headless hosts need an unlocked `login.keychain` or the VM will not start on macOS 15+; this Mac is a GUI session so that likely does not bite (faq.md "Headless machines").
4. Get in: `ssh admin@$(tart ip fresh-mac-27)` with password `admin` (use `sshpass`), or `tart exec` only on non-vanilla images with the guest agent. Mount the repo read-only instead of cloning: `tart run --dir=repo:/path/to/cpp-standard:ro` shows up at `/Volumes/My Shared Files/repo`. Better test: pull from the real git URL, as the owner's `mise bootstrap --from <repo>?ref=<sha>` would. Whether mise is available needs the install step itself (curl the mise installer), which is the thing under test.
5. Inside the guest: run the install script, then `mise bootstrap --from ...`. Expect the first `git` or `clang` call to trigger the Command Line Tools install prompt. A headless CLT install needs the `softwareupdate` trick (touch `/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress`, then `softwareupdate -i "Command Line Tools for Xcode ..."`) or Homebrew's own installer, which does this itself. The Tart docs say nothing about CLT; the vanilla templates keep the recovery partition "otherwise it's not possible to softwareupdate". UNVERIFIED in practice.
6. Reset: `tart stop`, `tart delete fresh-mac-27`, re-`tart clone` from the cached OCI image (seconds with APFS clone, no re-download). For a "fresh after prerequisites" snapshot, clone the VM into a second local VM (`tart clone fresh-mac-27 fresh-mac-27-clt`) after the slow step. `tart run --suspendable` plus `tart suspend` can freeze a running state (macOS 14+ host). No named snapshot command exists.
7. Time: image pull is dominated by about 30 GB download; boot of a VM from a clone is about a minute (first boot of a vanilla template waits 120 s for first-boot provisioning in the Packer build, not a clone). The bootstrap's own time (Homebrew gcc is a bottle, llvm is a bottle) is unknown. All UNVERIFIED.
- Limits: Apple's EULA allows two macOS VMs at a time per Apple host; Tart docs say "a single host which only allows a maximum of two virtual machines at a time" (blog 2023-04-25-orchard-ga.md) and "due to internal Apple EULA limit for macOS virtualization" (orchard/using-orchard-cli.md). Linux guests are not counted under that EULA rule (UNVERIFIED).
- Nested virtualization: only M3/M4 on macOS 15+ and only for Linux guests, via `--nested`; "macOS virtual machines do not support nested virtualization" (faq.md; https://github.com/openai/tart/discussions/701). So no Docker/Colima inside a macOS guest, which does not matter for our bootstrap.
- Guest account: `admin`/`admin` with passwordless sudo, matching how a fresh Mac user is an admin with a password prompt; our script should not assume passwordless sudo.

## 4. CI

- GitHub-hosted macOS arm64 runners cannot run Tart: GitHub's own page says "Limitations for arm64 macOS runners: Nested-virtualization is not supported due to the limitation of Apple's Virtualization Framework." (https://docs.github.com/en/actions/reference/runners/github-hosted-runners). The Intel `macos-15-intel`/`macos-26-intel` runners are not Apple Silicon, so Tart does not run there either. WarpBuild's macOS runners likewise "do not support nested virtualization".
- Option A: for CI on real hosted macOS, skip Tart; the hosted runner is already a clean, ephemeral Mac (but with Homebrew and Xcode pre-installed, so it is not "fresh"). Remove or ignore the preinstalled Homebrew-installed tools if that matters.
- Option B: self-hosted runner on this Mac (or another Apple Silicon Mac) that clones a pinned vanilla image per job. Tart docs have integrations for Buildkite, GitLab Runner, Cirrus CLI, Packer (docs/integrations). The cirruslabs templates install the GitHub Actions runner into `base`, which is how Cirrus Runners worked. Orchard (Tart's cluster orchestrator) is also under OpenAI now. Self-hosted runners on a personal Mac: GitHub warns against them for public repos (forks can run code) - owner decision.
- Cirrus Runners: closed to new customers after the OpenAI move (MacStadium post); previously $150 per concurrent runner per month (https://cirrus-runners.app/). Not an option. Alternative hosted macOS runners (WarpBuild, price about $0.08/min for 6 vCPU per its blog) do not nest Tart.
- Costs for Option B: no license fee; cost is hardware, 30-50 GB per image, and keeping the Mac awake and logged in.

## 5. Linux VMs in Tart

- Images: `ghcr.io/cirruslabs/ubuntu:latest` (and debian, fedora), minimal disk 20 GB, `admin`/`admin`, resize with `tart set ubuntu --disk-size 50`. Tags such as `ubuntu:22.04` exist; I did not check for 26.04 (UNVERIFIED; the quick-start page names Ubuntu only as `latest`). You can build your own from an ISO (`tart create --linux`) or via https://github.com/cirruslabs/linux-image-templates.
- These run arm64 only, natively on Apple Silicon, no Rosetta emulation for amd64 inside (Rosetta-for-Linux support in Tart is UNVERIFIED).
- Compared with Docker: the Linux side is already proven in Docker. A Tart Ubuntu VM adds a real systemd, a real `cloud-init`/user, real `sudo` and a real kernel, which Docker lacks, but gives only arm64 and costs a 20+ GB image. It is worth it only if we need to test systemd or package-manager behavior. `tart ip` is flaky with Ubuntu's DUID DHCP client ID (faq.md has the netplan fix: `dhcp-identifier: mac`).

## 6. Relevant issues and discussions (openai/tart)

- macOS 27 guests: #1261 "Tart fails to run macOS Golden Gate VM" (open; fixed for 27.0 final IPSW per comments; macOS bug in beta). #1420 Xcode/Apple Account sign-in fails in a 27.2 guest (open; irrelevant for CLT-only). #1427 `tart list` leaks kernel APFS objects on macOS 27.2 (open) - avoid frequent `tart list` loops. #1408 VirtioFS lacks `F_FULLFSYNC`, which breaks Rust tools on shared directories (open) - do not build on a `--dir` mount; copy the repo into the guest disk.
- Homebrew: #1394 `brew install cirruslabs/cli/tart` fails; use the `openai/tools` tap. #1029 (closed) Homebrew install failure in a guest with Xcode.
- Licensing: #1228 (closed) permissive license request; PR #1238 relicense to FSL; #1272 clarification (open).
- Stacked disks: #1269 (closed), #1403, #1376, #1352 (open) - features still moving.
- I did not find a Tart issue specifically about headless CLT installation; the CLT trick above comes from general macOS/Homebrew knowledge.

## 7. Recommended plan and what the owner must approve

Plan:
1. Keep Docker for the Ubuntu amd64/arm64 side.
2. Use Tart only for a "fresh Mac" check, using `macos-golden-gate-vanilla` (27.2, matches this Mac) pinned by digest.
3. One-time: pull, then `tart clone` into a working VM, resize, boot headless, SSH in. Run the real command: curl-install mise, `mise bootstrap --from <repo>?ref=<sha>`. Record wall time and failures. Re-clone from the cached image for every run.
4. Wrap steps in one script (`tart clone`, `set`, `run --no-graphics`, wait for `tart ip`, `sshpass ssh`, `tart stop`, `tart delete`). Put the image digest in the repo so the simulation is reproducible.
5. CI: hosted macOS runner for a quick check (no Tart); self-hosted Tart only if the owner accepts the runner risks. Keep both out of the first step.

Owner must approve before I do any of this:
- Installing Tart (brew tap `openai/tools` plus formula, or `mise use tart`; both are tool/config changes).
- The image download: about 30 GB compressed for golden-gate-vanilla 27.2, plus about 35-80 GB disk (one cached copy plus one working clone, more if resized). Check free space on `~/.tart`'s volume; set `TART_HOME` to a bigger disk if needed.
- Disabling macOS Gatekeeper is inside the guest only (image already does it); no host change. Running a VM needs no sudo on the host, but the `softnet` helper (installed by the formula) uses a privileged setup only if `--net-softnet` is used; we will not use it.
- Optional DHCP lease tweak (`sudo defaults write ...InternetSharing... DHCPLeaseTimeSecs`) from the Homebrew caveats; not required for a few runs.
- Whether to use a self-hosted runner on this Mac for CI.

## Tools used and failed

- Used: `git clone --depth 1` of openai/tart; `gh` (releases, repo view, api contents, issue/PR view and search); `mise registry`, `mise ls-remote`, `mise --version`; `brew info`/`brew search` (tart not in core/cask); `curl` to ghcr.io token and manifest endpoints (read only, no layer download); Firecrawl search (2 queries) and scrape (macstadium post).
- Failed or absent: `brew info tart` (no formula in core; only the openai tap has it); `tart` not installed locally; no Exa, Context7, Last30Days, or fnox needed or run; I did not fetch tart.run pages (docs came from the repo's `docs/` folder, which is the source of tart.run).
- UNVERIFIED items are flagged inline: mise-installed binary working with the provisioning profile, digest-pinned `tart clone`, stacked clone behavior, CLT headless install, boot and bootstrap timings, Rosetta in Linux guests, Ubuntu 26.04 image tag, long-term OpenAI maintenance.
