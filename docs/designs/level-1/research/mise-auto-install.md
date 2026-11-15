# When mise installs tools on its own (2026-11-15)

Every behaviour below was observed on a Mac with mise 2026.11.8 macos-arm64.
The source citations below are `file:line` in mise at tag v2026.11.8 (commit
a4a1996). They were found through an OpenWiki of that source, then read
directly in the full source tree.

## Why this matters

The macOS playbook says certifying installs nothing (rule 4). On 2026-11-15 a
`mise run check` in a cpp-standard worktree installed the LLVM 23 tarball
(`github:llvm/llvm-project` 23.1.5). It did this because the worktree's config
listed that tool and the tool was missing. On a fresh Tart VM, the same
mechanism would let `mise run certify:macos` install a missing tool first. A
check would then PASS on a tool that the image does not have.

## Settings in effect (observed)

`mise settings ls --all` and the TRACE settings dump show these values. None of
them is set in any config file:

| Setting | Value | Env var |
|---|---|---|
| `auto_install` | true | `MISE_AUTO_INSTALL` |
| `exec_auto_install` | true | `MISE_EXEC_AUTO_INSTALL` |
| `not_found_auto_install` | true | `MISE_NOT_FOUND_AUTO_INSTALL` |
| `task.run_auto_install` | true (`task_run_auto_install` is the unset old name) | `MISE_TASK_RUN_AUTO_INSTALL` |

When mise finishes loading settings, `auto_install = false` sets the other
three to false (src/config/settings.rs:1826-1830). The old `task_*` names are
moved to `task.*` before that step (src/config/settings.rs:1785, 1800-1803), so
an old `task_run_auto_install = true` cannot turn installs back on.

## Method

The test project was a throwaway folder with `[tools] jq = "1.8.2"` and one
file task. Each run set `MISE_DATA_DIR`, `MISE_CACHE_DIR`, `MISE_STATE_DIR` and
`MISE_GLOBAL_CONFIG_FILE` to scratch folders, so every install went into a
scratch folder that was deleted afterwards. jq 1.8.2 is not on the system.
macOS ships `/usr/bin/jq` 1.7.1 (`jq-1.7.1-apple`), so the version string
shows whether mise installed jq or the command fell through to the system
copy. Logs came from `MISE_LOG_FILE` and `MISE_LOG_LEVEL=debug|trace`. The
user's PATH has mise's shim folder at entry 150, ahead of `/usr/bin` (155).

## Results

| # | Command | Env | Installed? | Output |
|---|---|---|---|---|
| 1 | `mise run probe` | defaults | yes | task ran after install |
| 2 | `mise run probe` | `MISE_TASK_RUN_AUTO_INSTALL=0` | no | task ran |
| 3 | `mise run probe` | `MISE_AUTO_INSTALL=0` | no | task ran |
| 4 | `mise x -- jq --version` | defaults | yes | `jq-1.8.2` |
| 5 | `mise x -- jq --version` | `MISE_EXEC_AUTO_INSTALL=0` | **yes** (test artifact, see 5a) | WARN "auto-install is disabled, so mise looks for jq on PATH instead". The PATH lookup then finds the user's real shim folder, which this mise does not know as its own because `MISE_DATA_DIR` points at a scratch folder. That shim installs jq 1.8.2 |
| 5a | same as 5, with the scratch `MISE_DATA_DIR`'s own `shims` folder first on PATH | `MISE_EXEC_AUTO_INSTALL=0` | no | same WARN, then `jq-1.7.1-apple` |
| 5b | same as 5, with a `jq` link to mise in another folder first on PATH | `MISE_EXEC_AUTO_INSTALL=0` | **yes** | `jq-1.8.2` |
| 6 | same as 5, shims removed from PATH | `MISE_EXEC_AUTO_INSTALL=0` | no | `jq-1.7.1-apple` |
| 7 | `mise x -- jq --version` | `MISE_EXEC_AUTO_INSTALL=0 MISE_NOT_FOUND_AUTO_INSTALL=0` | no | `jq-1.7.1-apple` |
| 8 | `mise x -- jq --version` | `MISE_AUTO_INSTALL=0` | no | `jq-1.7.1-apple` |
| 9 | `<mise data dir>/shims/jq --version` | defaults | yes | `jq-1.8.2` |
| 10 | shim | `MISE_NOT_FOUND_AUTO_INSTALL=0` | no | `jq-1.7.1-apple` |
| 11 | shim | `MISE_EXEC_AUTO_INSTALL=0` | **yes** | `jq-1.8.2` |
| 12 | shim | `MISE_AUTO_INSTALL=0` | no | `jq-1.7.1-apple` |
| 13 | `mise run` of a task with `env = { MISE_AUTO_INSTALL = "0" }` | defaults | **yes** | `jq-1.8.2` |
| 14 | same, with task `tools = { jq = "1.8.2" }` | defaults | **yes** | `jq-1.8.2` |
| 15 | same as 13, project `[settings] auto_install = false` | defaults | no | `jq-1.7.1-apple` |

Rows 13-15 ran with mise's shim folder removed from PATH.

In cpp-standard itself, a TRACE log of `mise run certify:macos --only A1` shows
`toolset::list_missing_versions_for_install` running after the toolset build
and before the task. Nothing was missing, so nothing was installed. This is
the step that installed LLVM 23 when it was missing.

## Where the source installs a tool

All automatic installs go through one filter.
`Toolset::install_missing_versions` (src/toolset/toolset_install.rs:216-268)
lists the missing versions. It returns them without installing anything when
`skip_auto_install` is set (227-230). Otherwise it installs only the versions
that pass `may_auto_install` (271-283):

- `skip_auto_install` is false; and
- the tool is not `lazy = true`, unless the caller asks for lazy tools; and
- when `missing_args_only` is set, the tool came from a command-line argument; and
- the tool is not in `auto_install_disable_tools`.

Each command sets these two options in its own way:

| Path | Code | `missing_args_only` | `skip_auto_install` |
|---|---|---|---|
| `mise run`, before the tasks (skipped by `--skip-tools`) | src/cli/run.rs:1295-1309 | `!task.run_auto_install` | `!task.run_auto_install \|\| !auto_install` |
| `mise run`, tools of one task (`tools =`) | src/task/task_tool_installer.rs:221-244 | `!task.run_auto_install` | `!task.run_auto_install \|\| !auto_install` |
| `mise x` / `mise exec` | src/cli/exec.rs:285-306 | tool arguments given, or `!exec_auto_install`, or running as a shim | `!exec_auto_install \|\| !auto_install` |

The comment at src/cli/run.rs:1280-1282 says the toolset is built offline and
that `install_missing_versions` resolves the missing tools online again. The
help text of `--skip-tools` is at src/cli/run.rs:392-396.

### `mise x` falls back to PATH

With auto-install off, `warn_if_command_falls_back` (src/cli/exec.rs:647-700)
prints the warning seen in row 5. The command is then looked up on PATH
(src/cli/exec.rs:826-912). The lookup leaves out every folder for which
`is_mise_shims_dir` is true (exec.rs:857, 867). That function compares the
folder with the user and system shim folders of the running mise
(crates/mise-util/src/file.rs:2186-2197), and the user shim folder is under
`MISE_DATA_DIR`. So:

- In normal use, `mise x` skips its own shim folder and runs the next `jq` on
  PATH, here `/usr/bin/jq` (row 5a).
- A shim in any other folder is not skipped. When the lookup finds one, that
  shim runs its own install path, which `exec_auto_install` does not control
  (row 5b). Row 5 is this case: the test's scratch `MISE_DATA_DIR` made the
  user's real shim folder look like another folder.

### A shim installs by command name

A shim does not use `exec_auto_install`. `mise x` running as a shim sets
`missing_args_only`, so the shim's toolset pass installs nothing
(src/cli/exec.rs:291-294). The shim then looks for the command in
src/cli/shim.rs:400-478:

1. If `not_found_auto_install` is on and a configured registry tool provides
   the command, it installs that tool (403-424).
2. It looks for the command in the installed tools (426-435).
3. If a missing `lazy = true` tool provides the command, it installs that tool.
   No auto-install setting controls this step (437-456).
4. If `not_found_auto_install` is on, it installs the configured tool that
   provides the command (458-476).

`Toolset::install_missing_bin` (src/toolset/toolset_install.rs:1027-1110) does
these installs with `InstallOptions::default()` (1100). It skips only the tools
in `auto_install_disable_tools`. The same rules apply to a command wrapper's
command (src/shims.rs:153-179, called from src/cli/shim.rs:298), and the shell
command-not-found hook calls `install_missing_bin` when `not_found_auto_install`
is on (src/cli/hook_not_found.rs:28-36).

So the shim path depends on `not_found_auto_install`. `auto_install = false`
turns that setting off (settings.rs:1826-1830), which is why rows 8 and 12
install nothing.

## Answers to the open questions

**Does `auto_install = false` cover `hook-env`?** `hook-env` installs no missing
tool with any setting. It builds the toolset offline (src/cli/hook_env.rs:63-71,
with the comment "missing tools are handled by the normal install paths instead
of hook-env") and calls no install function. It can, however, start an
automatic upgrade of a tool that is already installed:
`update_in_background` (src/cli/hook_env.rs:73) starts `mise __tool-update`
for an installed global tool that opts in with `auto_update` or
`tool_update.global_auto` (src/cli/tool_update.rs:60-98, 173-192). That path
skips missing tools and does not read `auto_install`. It does not start when
mise is offline, in CI, inside another update, or while the update service runs
(src/tool_update.rs:144-165), and the update stops when `locked` is set
(src/cli/tool_update.rs:174-177). On this Mac `tool_update.global_auto` is
false, and no global config file sets `auto_update`. It keeps the shim folder on PATH
when `activate_shims` is on and `not_found_auto_install` is on or a lazy tool is
declared (src/cli/hook_env.rs:201-202). With `auto_install = false`, a shell
that does not declare lazy tools therefore gets no shim folder from `hook-env`.

**Does it cover env directives with `tools = true`?** Env directives install
nothing. `tools = true` only makes a directive wait until the toolset is
resolved, so that it can read the tool paths (src/config/env_directive/mod.rs:197).
No code under src/config/env_directive calls an install function. A search of
the whole src tree for calls to `install_missing_versions`,
`install_missing_bin`, `install_missing_lazy_bin` and `install_all_versions`
finds no caller in the env code. The template in `.mise/conf.d/llvm.toml` reads
`tools['github:llvm/llvm-project']`; when that tool is missing, the template
takes its `else` branch and nothing installs.

**Can it be set for one task?** No. A task's `env` is set only for the task's
own process. mise reads its settings when it starts, and it installs the tools
before it starts the tasks (src/cli/run.rs:1299-1309) and the task's own tools
(task_tool_installer.rs:239-241). Rows 13 and 14 show the install with
`MISE_AUTO_INSTALL=0` in the task's `env`. These places do work:

- `MISE_AUTO_INSTALL=0` in the environment of the `mise run` process;
- `[settings] auto_install = false` in a config file that mise loads (row 15).
  This applies to every command in that project, not to one task;
- `mise run --skip-tools`. This skips only the step before the tasks. A shim
  that a task calls can still install.

**Does it stop dependency installs?** Yes, for the paths above. Dependencies are
added inside `install_all_versions` (src/toolset/toolset_install.rs:312-420).
When `skip_auto_install` stops the install, `install_all_versions` does not
run, so no dependency is installed either. Two exceptions are not in
cpp-standard's config today:

- A `lazy = true` tool installs its missing dependencies with it
  (toolset_install.rs:90-145), and lazy installs ignore `auto_install`.
- `mise deps install` installs missing tools with `missing_args_only = false`
  and does not read `auto_install` (src/cli/deps/install.rs:130-136).
- `[deps]` providers with `auto = true` run before `mise exec` and `mise run`
  (src/cli/exec.rs:393-403; src/cli/run.rs:1324-1338). They call the deps
  engine directly, not that tool install. They install project dependencies,
  such as node_modules, and do not read `auto_install` (src/cli/deps/mod.rs:7-15).

## Paths that `auto_install = false` does not stop

These are not used in cpp-standard today (no `lazy`, `[deps]`, daemons or tool
stubs in `mise.toml` or `.mise/`, `tool_update.global_auto` is false on this Mac, and no global config
file sets `auto_update`). They matter if one is added later:

| Path | Code |
|---|---|
| A `lazy = true` tool, from a shim or `mise x` | src/cli/shim.rs:437-456; src/cli/exec.rs:332-345 |
| `mise deps install` installs missing tools | src/cli/deps/install.rs:130-136 |
| `[deps]` providers with `auto = true` install project dependencies | src/cli/exec.rs:393-403; src/cli/run.rs:1324-1338 |
| `hook-env` upgrades an installed global tool that opts in to `auto_update` | src/cli/hook_env.rs:73; src/cli/tool_update.rs:60-98, 173-192 |
| Daemon tools (`missing_args_only = false`) | src/daemons/glue.rs:130-139, 276-285 |
| A tool stub runs its own tool | src/cli/tool_stub.rs:313-324 |

Commands that the user runs to install a tool, such as `mise install`,
`mise use` and `mise upgrade`, are explicit installs and do not read
`auto_install`.

## Conclusions

1. Three paths install a missing tool in cpp-standard's setup:
   - `mise run`, before a task, controlled by `task.run_auto_install`;
   - `mise x`, controlled by `exec_auto_install`;
   - a mise shim, controlled by `not_found_auto_install`, **not**
     `exec_auto_install`.
2. `auto_install = false` (`MISE_AUTO_INSTALL=0`) turns off all three, because
   mise sets the three settings to false when it loads its settings.
3. `exec_auto_install = false` alone is not enough. A shim called directly
   still installs (row 11). `mise x` skips its own shim folder, but a shim in
   another folder on PATH, such as one from a second `MISE_DATA_DIR`, still
   installs (rows 5, 5b).
4. A task's own `env` cannot turn auto-install off for that task (rows 13, 14).
   The setting must be in the environment of the `mise run` process, or in a
   loaded config's `[settings]`.
5. For a certification run, `MISE_AUTO_INSTALL=0` in the environment of
   `mise run` keeps a missing tool missing. The check then FAILs, or a system
   copy answers. The check must catch a system copy by its version or path.

## Definition of done for Tart

A run of `mise run certify:macos` on a fresh Tart VM, with `MISE_AUTO_INSTALL=0`
in the environment of `mise run`, belongs in the Tart definition of done (V1,
V2). Its report must show that no mise install ran:

- the list of folders under `$MISE_DATA_DIR/installs`, two levels deep (one
  folder per tool, then one per version), is the same before and after the
  run;
- the mise log of the run (`MISE_LOG_FILE`, level debug) has no install line.

`mise where` is not enough for this check. It takes one tool and prints the
folder of one installed version, so a new version or a new tool would not show.
