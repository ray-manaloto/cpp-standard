---
status: accepted
---

# Machine bootstrap moves from dotfiles to cpp-standard (D139, D141)

The owner ruled that cpp-standard sets up the machines themselves, not only its project environments
(D139). This plan says what moves from dotfiles, what stays, the order, and how each step is checked
and undone. The owner approved it on 2026-11-16 ("Approve; start Phase 1"). Until Phase 3, dotfiles
keeps running what it runs today, and the PC keeps the files dotfiles installed.

The owner answered four scope questions on 2026-11-16 (D141):

1. **All of the PC moves**, including the self-hosted CI runner slots that serve other repositories.
2. **The open PC tickets are re-filed in cpp-standard**, not finished in dotfiles first.
3. **The PC's private values come from a PC-only Doppler config**, as dotfiles #637 designed it.
4. **Agent-hygiene checks stay in dotfiles:** `spotlight:check`, `herdr:doctor` and the nightly check.

## What exists today

dotfiles spec #633 began moving the PC's setup into dotfiles, and spec #729 added host guards to it.
On dotfiles `main` (bdff133) these are merged and live on the PC:

| Piece | dotfiles source | Tickets |
| --- | --- | --- |
| The `pc` mise config environment | `unix/home/.config/mise/config.pc.toml` | #634 |
| Runner slot unit template, runner directory and image Dockerfile, one slot per repository (glaze, cpp-utilities, dotfiles) | `config.pc.toml` | #636 |
| Job fence: `gha-fence.service` and its iptables rules files; host firewall (ufw) rules files | `config.pc.toml` | #636, #741 |
| GPU containers through NVIDIA's CDI refresh units | `config.pc.toml` | #732 |
| `pc:doctor`: bootstrap status and plan over ssh, plus the kernel, privileged, gpu-cdi, updates and fence-drops lines | `tasks/pc/doctor`, `python/home/src/hometools/pc*.py`, `data/pc-kernel.json` and their tests | #634, #730-#733, #741 |
| The models the `pc*.py` modules import, generated from JSON Schema | `python/home/schema/hometools.schema.json`, the generated `models.py` | #634, #730-#733 |
| PC smoke workflow on the self-hosted runner | `.github/workflows/pc-smoke.yml` | #636 |

`pc:doctor` also depends on two things outside these files:

- the `pc` ssh alias on the Mac, from dotfiles' ssh config;
- passwordless read-only `sudo -n` on the PC for the fence-drops line, which the owner approved.

The PC also renders two templates from dotfiles' global config:

- `unix/home/.ssh/config.d/tailnet.conf.tera`;
- `unix/home/.config/mise/conf.d/cloudflare.toml.tera`.

They need the fnox secrets `PC_HOST`, `PC_LAN_HOST` and `CF_ACCOUNT_ID`, which the PC cannot read
today. That is why a plain `mise bootstrap` on the PC fails, and the PC is applied with `--only files`
and then `--only services`.

Open, with no pull request:

| Ticket | What | State of the work |
| --- | --- | --- |
| #635 | Runner launcher as a Python CLI | 27 files, staged, not committed; needs a rebase onto bdff133 |
| #735 | apt cache as a declared PC service, checked by `pc:doctor` | 6 files, staged, not committed; the cache runs today as a hand-started container with a hand-added ufw route rule |
| #637 | PC secret inputs from a PC-only Doppler config | Not started |
| #638 | Host firewall policy and Mac-only LAN SSH in config | Not started |
| #639 | Runner slots switch to the new launcher | Not started |
| #640 | Reachability probes in the CLI and `pc:doctor` | Not started |
| #641 | The PC's hardware jobs as CLI subcommands | Not started |
| #642 | A `pc:doctor` skill, retiring the old recipe | Not started |
| #741 (closed) | Fence follow-ups: the probe under the unit, the slot restart check, and a reboot test that needs the owner at the console | Open steps |

dotfiles-lead saved the staged work of #635 and #735 as patches with their commit messages, in each
ticket's dotfiles plan folder, so the work survives a worktree cleanup.

The PC also holds files that no config manages. These are read-only findings by dotfiles-lead:

| Path | What | Goes to |
| --- | --- | --- |
| `/etc/gha-runner/app.pem` | The runner GitHub App's private key | Stays on the PC, outside any repository; only the code that reads it moves |
| `/etc/gha-runner/runner.json` (and 2 `.bak` copies), `README.md` | Runner slot config | #635 |
| `/usr/local/sbin/gha-slot` (and 2 `.bak` copies) | The bash runner launcher | #635, #639 |
| `/usr/local/sbin/hw-watch`, `hw-heartbeat`, `hw-notify` and their timers and services | Hardware watch and alerts | #641 |
| `/usr/local/sbin/h1-pump-full`, `h1-radfan-curve` and their services | The cooling pump and radiator fan curves. Losing them is a thermal risk. | #641 |
| `/usr/local/bin/ntfy-qr` | Notification helper | #641 |
| `/usr/local/bin/mkinitcpio` | A wrapper that shadows the real `mkinitcpio`, which runs at every kernel update | The owner decides; see the open questions |

Omarchy's own units (snapper, limine, btrfs-scrub) belong to the operating system and are not part of
this move.

dotfiles also holds C++ toolchain parts that D17 already retires from dotfiles:

- the p2996 toolchain package (`python/toolchains/p2996`);
- the CMake toolchain files (`cmake/toolchains/`);
- the `cpp/` sample;
- the toolchain tasks.

## What moves and what stays

**Moves to cpp-standard:**

- The whole `pc` environment: every entry of `config.pc.toml`.
- The PC parts of `pc:doctor`:
  - the task;
  - the `pc*.py` modules and their tests;
  - `pc-kernel.json`;
  - the schema definitions those modules use, with a step that generates their models.
- `pc-smoke.yml`, once cpp-standard has its own runner slot (Phase 4).
- The eight open tickets above, re-filed in cpp-standard, each linking its dotfiles original. #635 and
  #735 start from the saved patches.
- The C++ toolchain parts listed above (D17). This plan sets their order only. Each one moves in its
  own reviewed pull request.
- Later, machine environments for the Mac and for Ubuntu amd64 and arm64. Today cpp-standard has
  project environments for Ubuntu (`mise.ubuntu.toml`, `mise.ubuntu-cache.toml`) and none for
  machines.

**Stays in dotfiles:**

- shell, git and agent configuration;
- the ssh config, including the `pc` alias;
- the global mise config's non-C++ tools, and its `[dotfiles]` templates, including the two the PC
  renders. #637's PC-only Doppler config feeds those templates, as well as cpp-standard's `pc`
  environment;
- secrets handling for the owner's main Doppler config;
- `spotlight:check`, `herdr:doctor` and the nightly check;
- the agent rules in `AGENTS.md`, including "No --privileged containers on the PC" and "Upgrading
  the PC". They stay where every agent reads them, and cpp-standard's docs link to them rather than
  copying them.

## Order

A phase that changes the PC waits for chief-of-staff's slot, and the PC's watched kernel settings are
read before and after it.

**Phase 0: approval.** dotfiles-lead has reviewed this plan, and the owner approves it. Until then no
ticket moves and no file on the PC changes.

**Phase 1: the doctor first.** cpp-standard gets the `pc:doctor` task with a Python package and test
gate of its own. cpp-standard has no Python package today. The package keeps dotfiles' rules:

- ruff and ty;
- 100% line and branch coverage;
- every model generated from JSON Schema by datamodel-codegen.

So the schema definitions and the generation step move together with the modules. The doctor only
reads, so it can run beside dotfiles' doctor.

- *Check:* both doctors give the same result on every line against the live PC.
- *Undo:* delete the package; the PC is untouched.

**Phase 2: the `pc` environment, as a copy.** cpp-standard gets `mise.pc.toml` with the entries of
`config.pc.toml` unchanged, and the PC gets a cpp-standard checkout.

The PC still selects dotfiles' `pc` environment, so a plain `mise -E pc` plan in the checkout would load
both files. It would then pass even if cpp-standard's copy left an entry out. The check therefore
leaves dotfiles' file out of that one command through an environment override, not an edit to
`miserc.local.toml`. Before Phase 2, settle from mise's source:

- which override does that;
- how mise merges two declarations of the same system file or service.

How Phase 2 is checked and undone:

- *Check:* the plan from the checkout, with dotfiles' `pc` file left out, shows no change on the PC.
  This is the no-op switchover that #633's user story 6 asks for.
- *Undo:* remove the checkout.

**Phase 3: the switch.** In one window:

1. The PC stops selecting `pc` in dotfiles' untracked `miserc.local.toml`.
2. dotfiles removes `config.pc.toml` and the moved doctor parts.
3. A small dotfiles pull request points `AGENTS.md`'s two PC rules at cpp-standard's `pc:doctor`.
4. cpp-standard's environment becomes the one that applies.

When a config stops loading, mise leaves the system files and services it declared in place. It
removes a system file only for an entry that says `state = "absent"`. It has no removal of undeclared
services. dotfiles-lead checked this in mise v2026.11.9's source: `crates/mise-system/src/files.rs`,
`src/cli/bootstrap.rs`. Only the prune commands remove what is no longer declared. During the window
nobody runs any of these:

- `mise bootstrap --prune-dotfiles`;
- `mise dot apply --prune`;
- `mise bootstrap packages prune`.

How Phase 3 is checked and undone:

- *Check:* cpp-standard's `pc:doctor` passes, and dotfiles' `pc-smoke.yml` runs green on the dotfiles
  slot. That workflow tests the PC, wherever its file lives.
- *Undo:* select `pc` again in dotfiles, and revert dotfiles' removal pull request.

**Phase 4: the re-filed tickets.** These go in dependency order:

1. **#637, the Doppler config.** The owner creates it and places its token, the one human step.
2. **#638, the firewall.**
3. **#735, the apt cache.** Its switchover keeps the running cache's data volume and address.
4. **#635, then #639, the launcher.** They manage `runner.json` and replace the bash launcher.
5. **A cpp-standard runner slot.** cpp-standard gets a fourth slot, with the labels
   `[self-hosted, pc-x86, container, cpp-standard]`. The runner GitHub App gets access to
   cpp-standard. That is a GitHub setting, done through dotfiles-lead. Then `pc-smoke.yml` moves to
   cpp-standard.
6. **#640, #641 and #642.** #641 brings the hardware watch and cooling services under config.
7. **#741's open steps.** These include a fix to the first-apply comment in `config.pc.toml`. It says
   `--skip services` where it must say `--only files`, then `--only services`, and #636's two-run comment
   needs the same fix. dotfiles-lead makes that fix in dotfiles before Phase 2, so the copy carries it.

Each ticket follows the normal cross-review and merge flow, with its own check and undo.

**Phase 5: the C++ toolchain parts and other machines.** Phase 5 begins after Phase 3. It covers:

- the p2996 package, CMake toolchains and toolchain tasks;
- then machine environments for the Mac and for Ubuntu amd64 and arm64.

Each gets its own plan section, with checks and undo, when it starts.

## Constraints that carry over

- **Runners on public repositories.** cpp-standard is public, like the three repositories its runner
  slots serve. The PC workflows keep `pc-smoke.yml`'s rule: `workflow_dispatch` and pushes only, never
  `pull_request`, so fork code never reaches the PC.
- **Private values.** No address, host name or ID goes in a tracked file. Private values come from the
  PC-only Doppler config, or from an untracked `*.local.toml` on the PC.
- **Ubuntu 26.10 apt sources.** On Ubuntu 26.10, mise can create an apt source but not change it,
  because of the uutils `install` bug (see `docs/standard/ubuntu.md`). A machine environment for Ubuntu
  must delete a changed source's file first. The PC runs Omarchy, so this does not affect it.
- **Upgrades.** `mise bootstrap` installs and checks packages but never upgrades them. `omarchy update -y`
  stays the PC's one upgrade step, and it runs only with the owner's OK.

## Open questions

- **Runner slot names and labels.** *Recommended:* keep them (`pc-x86`, one slot per repository), so
  glaze, cpp-utilities and dotfiles need no workflow change. dotfiles-lead agrees.
- **The GitHub App key.** *Recommended:* it stays at `/etc/gha-runner/app.pem` on the PC, outside any
  repository, and only the code that reads it moves. dotfiles-lead agrees.
- **The `mkinitcpio` wrapper.** Does the wrapper that shadows the real `mkinitcpio` come under config
  (#641), or is it removed? This is the owner's call. Its source and purpose are read before it is
  asked.
