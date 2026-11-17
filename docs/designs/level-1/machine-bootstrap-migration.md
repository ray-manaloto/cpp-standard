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

Omarchy's own units (snapper, limine, btrfs-scrub) belong to the operating system and are not part of
this move. So does `/usr/local/bin/mkinitcpio`, which the first listing counted as unmanaged. It belongs to
the package `limine-mkinitcpio-hook` 1.40.0, which Omarchy installs as a dependency, and it matches the
package's copy (`pacman -Qkk`). It runs the real `mkinitcpio`. After a preset rebuild it warns that the
Limine boot entries were not updated and offers to run `limine-mkinitcpio`. The owner ruled on
2026-11-16 to leave it to Omarchy: "Leave it to Omarchy (Recommended)".

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
  machines. A third environment, `mise.ci.toml`, is loaded only by CI's lint job (`MISE_ENV=ci`). It
  pins Python and uv on Linux for the `pctools` gate, so `mise -E ubuntu bootstrap` never installs them.

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
`miserc.local.toml`. Both source questions are settled, from mise v2026.11.9 and a scratch run:

- **The override is `MISE_IGNORED_CONFIG_PATHS`, naming dotfiles' file through the global config
  folder:** `${XDG_CONFIG_HOME:-$HOME/.config}/mise/config.pc.toml`. Every config path, global ones
  included, passes the `ignored_config_paths` filter (`src/config/mod.rs:3179`, `:3714`). For global
  config the filter compares the path as written, without following links
  (`src/config/config_file/mod.rs:1167-1171`, `:1108-1111`). So the checkout's resolved path does not
  match, and a scratch run with that spelling kept the file. The variable replaces any
  `ignored_config_paths` in a miserc rather than adding to it (`src/env.rs:194-199`), so the PC's miserc
  is read first. `MISE_GLOBAL_CONFIG_FILE` would replace all global config with one file
  (`src/config/mod.rs:3743-3744`), and `MISE_CONFIG_DIR` would move the whole folder.
- **Two declarations of the same key:** within one config hierarchy, which here is the checkout plus the
  global config, the declaration with the highest precedence is kept whole and the other is ignored without
  an error. That holds for files (`crates/mise-system/src/managed_files.rs:404-406`, `:444`),
  directories (`:516`) and services (`crates/mise-system/src/services_common.rs:157-160`). Packages
  merge by key, the more local file winning each one (`crates/mise-system/src/lib.rs:506-508`). Between
  independent `[bootstrap].config_roots`, a different declaration makes mise refuse
  (`managed_files.rs:370-381`, `services_common.rs:127-137`).

How Phase 2 is checked and undone:

- *Check:* the plan from the checkout, with dotfiles' `pc` file left out, shows no change on the PC,
  and `mise -E pc config ls --json` lists the checkout's `mise.pc.toml` but not dotfiles' file. The
  plan alone could not show that the override took effect. When both files load, the checkout's
  declaration wins, so it names itself as each entry's `origin.config` either way. This is the
  no-op switchover that #633's user story 6 asks for. Like every mise run, it records the config
  files it loaded in mise's state folder (`src/config/mod.rs:4338`). It writes no trust state.
- *Undo:* remove the checkout.

**Phase 3: the switch.** Until it, dotfiles' `config.pc.toml` is still the one that applies, and nothing
compares it with `mise.pc.toml`. A dotfiles change made after the copy would be lost at the switch.
So the window starts by checking the copy again. `mise.pc.toml` is diffed against dotfiles main: every byte
after the header must match, and the parsed entries must be equal. The Phase 2 plan check is then rerun.
In one window:

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

**Phase 3, the link switch on the PC, 2026-11-17,** with the owner's go and chief-of-staff's slot. The switch is done; steps 2 and 3 and the `pc-smoke.yml` check are still open:

- *Before:* both SSH paths answered. `mise.pc.toml` matched dotfiles main `42f3d5a` byte for byte after the header, and the parsed entries were equal. The Phase 2 check from the checkout at `9d9b86f` showed no change for the 18 `pc` entries.
- *The switch is one link.* `$HOME/.config/mise/config.pc.toml` pointed at dotfiles' file. It now points at the checkout's `mise.pc.toml`. The selection, `env = ["pc"]` in `miserc.local.toml`, stays. Both doctors run mise from the home folder with no `-E`, so they read cpp-standard's file with no change to either doctor. Nothing was applied or pruned, no service was restarted, and the PC was not rebooted. This replaces steps 1 and 4 above.
- *After:* the plan from the home folder shows no change for the 18 `pc` entries, and Tailscale SSH answered at once. Both doctors exit 0. The kernel settings are unchanged. `gha-fence`, `ufw`, the three slots and `acu-trial` are active, and the Mac's fetch through the apt cache on port 3142 returns 200. chief-of-staff checked the PC afterwards.
- *Undo,* run on the PC:
  `ln -sfn "<dotfiles checkout>/unix/home/.config/mise/config.pc.toml" "$HOME/.config/mise/config.pc.toml"`
- *The PC's checkout stays on `main`,* tracking `origin/main`. The link makes the checkout's `mise.pc.toml` the PC's declared config, so a checkout of another branch or commit changes that config without any warning. Test checkouts go in another folder.
- *Still open:* steps 2 and 3, which are dotfiles-lead's, and a green `pc-smoke.yml` run on the dotfiles slot, the check above. Until dotfiles drops `config.pc.toml`, a `mise dot apply` on the PC may point the link back at dotfiles' file. The two files are identical, so the PC would not change.

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

## The whole of dotfiles moves (D150)

On 2026-11-17 the owner widened D139: cpp-standard takes over the whole dotfiles project, not only the
PC, through a planned migration of the same kind as the PC's Phases 1-3. dotfiles-lead hands over its
in-flight work through chief-of-staff, marking each item finish-in-dotfiles, move, or drop. From then
on, new machine-setup changes land in cpp-standard. Until each switch below, dotfiles stays the one
that applies on the Mac.

### Inventory (dotfiles main `175add64`, 579 tracked files)

| Part | What it is | Goes to | Phase |
|---|---|---|---|
| `unix/home/.config/mise/` (88 files) | The Mac's global mise config: `config.toml` with 80 `[dotfiles]` entries, `conf.d/`, tasks, lock | cpp-standard `mise.mac.toml`, the Mac's counterpart of `mise.pc.toml` | M1 |
| `unix/home/.ssh/config.d/tailnet.conf.tera` | `pc` over the tailnet (the tailnet-only ruling of 2026-11-11), `pc-lan` break-glass, from Doppler `PC_HOST`/`PC_LAN_HOST` | `mise.mac.toml`, unchanged | M1 |
| `unix/home/.config/agents/` (25), `.agents/skills`, `.claude/`, `.codex/`, `.gemini/`, `.config/opencode/` | The global agent rules (`AGENTS.md`, workflow, skills) and each agent's settings | `mise.mac.toml` and `mise.pc.toml`; the agent rules as one shared source | M1 |
| `unix/home/.config/{zsh,git,fnox,jouet,herdr-app,dep-maps,starship.toml}`, `.local/bin`, `.local/share` | Shell, git, secrets and tool configs | `mise.mac.toml` (git settings with the owner's word, as before) | M1 |
| `python/repo` (`repotools`), `python/workflow` (`workflowtools`) | The PR and workflow tools every repository uses | cpp-standard `python/`, installed as uv tools from it | M2 |
| `python/home` (`hometools`), `python/guards`, `python/depmaps`, `python/cbm`, `python/lsp`, `python/jbctl`, `python/visualplan`, `swift/` (`jbax`) | Machine and agent helpers | Each is kept only if something still calls it: moved to `python/`, else dropped. `hometools`' herdr filter for macos-development-environment is dead (that project was sunset on 2026-11-17) | M2 |
| `python/toolchains/p2996`, `cmake/toolchains/` | The older p2996 build and toolchain files | Dropped: cpp-standard's toolchain work replaces them (D136) | M2 |
| `cpp/`, `typescript/`, `python/src`, `python/tests` greet samples | Hello-world samples | Dropped | M2 |
| `docs/` (86: ADRs, research, designs) | Reasoning behind the tools | Moved next to the code that keeps it, else left in the archive | M2 |
| Root `AGENTS.md`, `hk.pkl`, `mise.toml`, `*.bak-*`, `task_plan.md`, `progress.md` | Repository rules, checks and old plan files | Rules folded into cpp-standard's; the rest stays in the archive | M3 |

### Order

- **M1, the Mac's config.** Copy the entries unchanged into `mise.mac.toml`, check the plan shows no
  change, then switch the Mac as the PC was switched (one link, Phase 3 of this plan). The unmanaged
  LAN-address block for the PC in `~/.ssh/config`, from before the tailnet-only ruling, is removed in this
  step. Afterwards `mise -E mac bootstrap --from https://github.com/ray-manaloto/cpp-standard.git`
  sets up a Mac the way `-E pc` sets up the PC (tested on 2026-11-17: exit 0, no system change).
- **M2, the tools.** Move what is still used, point `mise run //repo:tools-install` and the agent
  rules at cpp-standard, drop the rest.
- **M3, the archive.** dotfiles becomes read-only on GitHub with a README pointing at cpp-standard.
  The owner archives it.

Each step is checked with the plan diff and both doctors, and undone by pointing the link back.
