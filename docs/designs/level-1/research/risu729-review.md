# Review of risu729's mise bootstrap and Renovate setup

Date: 2026-11-13. Read-only review. Nothing in either repo was changed.

Repos (fresh clones):
- DOT = <research-cache>/repos/risu729-dotfiles
- REN = <research-cache>/repos/risu729-renovate-config
- Saved docs: <research-cache>/docs/risu729/

Line numbers come from `cat -n` of the cloned files. Paths below are relative to DOT or REN.

## Short answer

risu729 runs one root `mise.toml` as a bootstrap project on macOS and Ubuntu (WSL). It is a personal workstation setup, not a toolchain image build. Three things transfer to us directly: the install script plus `mise bootstrap --yes --update --locked`, the install-twice-and-verify CI, and the Renovate custom managers for the mise pin. Three things we need and they lack: Renovate coverage and locking for `[bootstrap.packages]`/apt pins, a root-to-non-root system install pattern, and linux-arm64.

## Q1. Mise config structure

- `.miserc.toml:1-4`: `auto_env = true`. This is an early-init setting, so it cannot live in `mise.toml`. It makes mise load `mise.linux.toml`, `mise.macos.toml` and `mise.windows.toml` by OS, plus `mise.<profile>.toml` for `MISE_ENV`.
- `mise.toml:3`: `min_version = "2026.11.5"`.
- `mise.toml:8-34`: `[tools]` with exact pins (for example `hk = "2.11.1"`, `node = "26.13.0"`).
- `mise.toml:36-45`: `[settings]` with `experimental = true`, `lockfile = true`, `lockfile_mode = "generate"`, `exec_auto_install = false`, `dotfiles.default_mode = "symlink"`, `dotfiles.root = "unix/home"`.
- `mise.toml:51-66`: `[deps.*]`. `mise.toml:77-78`: `[task_config] includes = ["tasks.toml","tasks","worker/tasks.toml"]`.
- `mise.toml:82-223`: `[bootstrap.hooks.*]`, written as Tera templates. They branch with `{% if os() == "linux" %}` and `mise_env is defined and "personal" in mise_env`.
  - Pre-packages hook (lines 94-104) writes `/etc/apt/keyrings/docker.asc` and a docker apt list using `dpkg --print-architecture`, and adds passwordless sudoers.
  - macOS hook (line 133) runs `mise bootstrap packages apply brew:ruby --yes`.
- `mise.toml:227-292`: `[bootstrap.macos.*]` (defaults, dock, finder, keyboard).
- `mise.toml:294-340`: `[bootstrap.packages]`. Linux entries are unpinned, for example `"apt:cmake" = "latest"`, also `apt:clang`, `apt:clangd`, `apt:gdb`, `apt:llvm`. macOS entries use an OS filter, `"brew:git" = { os = "macos" }` and `"brew-cask:claude" = { os = "macos", adopt = true }`.
- `mise.toml:342-346`: `[bootstrap.repos]`.
- `mise.toml:349-443`: `[dotfile_groups.*]` and `[dotfiles]` using `variants = [{ os = "linux" }]`, `{ profile = "personal" }` and `mode = "template"`.
- `mise.toml:445-451`: `[hooks] postinstall`, skipped when `env.CI` is defined.
- Overlays: `mise.linux.toml` (`[bootstrap.user] login_shell = "/bin/bash"`), `mise.macos.toml` (zshrc block, a Screenshots directory with `state = "present"`), `mise.windows.toml`, and `mise.personal.toml` (additive: cloudflared systemd unit, extra `apt:` packages, extra `[bootstrap.repos]`).
- User-global config: `unix/home/.config/mise/{config.toml, config.linux.toml, config.macos.toml, config.personal.toml, miserc.toml.tera}`. `config.toml` uses tool filters like `os = ["linux"]` / `os = ["macos"]` (eza vs cargo:eza near lines 52-53, btop near line 60), `minimum_release_age = "3h"` (line 154) and `latest` versions. `miserc.toml.tera` persists `env = ["personal"]` for later runs.
- Lockfile: `mise.lock`, 741 lines, tools only. A grep for `apt` and `brew` in it returns nothing, so bootstrap packages are not locked or pinned. Platforms present: linux-x64 (with baseline and musl variants) and macos-arm64. There is no linux-arm64 entry. One file serves both OSes through per-platform tables. Separate locks exist for the global config and `mise.personal.lock`.
- One config serves both OSes by four mechanisms: `auto_env` overlays, per-package `os` filters, Tera `os()` branching in hooks, and dotfile `variants`.

## Q2. Fresh-machine bootstrap

`unix/install.sh`:
- Line 7: `mise_version="2026.11.5"` (Renovate keeps it current).
- Lines 33-49: on macOS, installs Xcode command line tools and waits.
- Lines 51-71: `curl https://mise.run | MISE_VERSION=... MISE_INSTALL_PATH=~/.local/bin/mise ... sh`, then checks the version.
- Lines 85-95: `mise trust` for each `mise*.toml` (avoids `--all`).
- Lines 97-165: clones the repo to `~/.ghr/github.com/risu729/dotfiles`, then `mise --cd ... bootstrap repos update ... --skip-dirty`.
- Lines 170-181: `export MISE_AUTO_ENV=true`, `MISE_ENV="${profile}"`.
- Line 196: `mise --cd "${dotfiles_dir}" bootstrap --yes --update --force-dotfiles --locked --skip-dirty`
- Line 199: `mise reshim`. Lines 188-195: a CARGO_HOME/RUSTUP_HOME workaround (jdx/mise#11938).

Delivery: a Cloudflare Worker serves `curl dot.risunosu.com/mac|wsl[?profile=&ref=]` (README.md; the Worker injects `git_ref` and `profile`, per AGENTS.md).

They do not use `--from` or `--adopt`. The install script clones the repo and runs `mise bootstrap` inside it as the project. Dotfiles are handled by mise's own `[dotfiles]` (`mise dot`), not chezmoi.

Privilege model: runs as the normal user; mise runs apt through `sudo`, and the pre-packages hook adds passwordless sudoers. Mise docs (`bootstrap/packages/index.md:420-434`) confirm: when not root, mise elevates apt through sudo, then run0, then doas, and `system_packages.sudo = false` forbids that.

Containers: none is a toolchain image.
- `worker/docker/Dockerfile:1-43`: multi-stage `ghcr.io/jdx/mise:2026.11.5@sha256:...` copied into `ubuntu:26.04@sha256:...`, `MISE_DATA_DIR=/mise`, `MISE_CACHE_DIR`, `MISE_TRUSTED_CONFIG_PATHS`, `MISE_YES=1`, shims on PATH, a version-drift check, runs as root. It is a Worker preview container.
- `docker/wsl/Dockerfile`: `FROM scratch; ADD wsl-amd64.wsl /`, a WSL rootfs used to test the installer.
- `compose.ci.yml`: services `worker` and `test-linux`.

## Q3. CI testing bootstrap

`.github/workflows/ci.yml`:
- Runners `ubuntu-26.04` and `macos-26`. mise installed with `jdx/mise-action@b44d12e7... # v5.2.7`, `version: 2026.11.5`, `cache: false`, plus `actions/cache` on `~/.cache/mise/downloads-cas` keyed on `hashFiles('mise.lock')`.
- `bootstrap: true` is not used. mise-action only installs mise and tools. Bootstrap is exercised by running the real installer.
- `test-linux` (matrix profile bare/personal): `tasks/test/installer-linux` builds an Ubuntu 26.04 WSL rootfs image (amd64 only) with compose, curls the installer from the preview Worker with `?ref=<sha>`, runs it twice (idempotency), then `tasks/verify/installation`, which runs `mise doctor --json` (fail on warnings) and project checks from `mise/doctor/mise.toml`.
- `test-macos` (macos-26): `tasks/test/installer-macos`, same flow with `DOTFILES_REF=$GIT_COMMIT_SHA`.
- `mise-backends`: `tasks/verify/mise-backends` (`mise backends switch --dry-run`) on both OSes.
- Others: `lint` (`mise run check --lint`), `test-bats`, Worker container on ubuntu-24.04 and ubuntu-24.04-arm, `CI Check` aggregate. `health.yml` is a weekly scheduled call of ci.yml. `codeql.yml` runs security-extended.
- All actions are SHA-pinned with version comments, `permissions: {}`, persist-credentials false.
- CI equals local because every check is a `mise run` task and the same installer runs in both.

## Q4. Renovate

`REN/src/default.json5` (282 lines; `default.json` is generated):
- Lines 4-12 `extends`: `config:best-practices`, `:pinVersions`, `:automergeMinor`, `:automergeDigest`, `:prHourlyLimitNone`, `:prConcurrentLimitNone`, `customManagers:biomeVersions`. Lines 13-17 `ignorePresets`: `:ignoreModulesAndTests`, `security:minimumReleaseAgeNpm`.
- Lines 21-33: `minimumReleaseAge: "1 day"`, `minimumReleaseAgeBehaviour: "timestamp-optional"`, `internalChecksFilter: "strict"`, `prCreation: "immediate"`, `platformAutomerge: false`.
- Lines 39-131 customManagers: regex for hk Pkl imports and hk-config raw URLs; jsonata for the mise-action `with.version` in workflows (lines 66-81, updates jdx/mise), wrangler compatibility dates, cargo-dist. Lines 132-178: customDatasources.
- Lines 179-281 packageRules: own `risu729/**` releases skip the age check; python minor is breaking; mise automerges (CalVer); groups for biome, hk, mise (including the `ghcr.io/jdx/mise` container, `groupSingleUpdates`), typescript, usage. Lines 276-280 disable updates for `**/.mise/locks/**` and `**/.config/mise/locks/**`.
- Presets are published by semantic-release tags; consumers pin `github>risu729/renovate-config#3.23.2` and Renovate bumps the pin (README regex manager does the same for the repo itself).

`DOT/.github/renovate.json5` (110 lines):
- Line 4: `extends: ["github>risu729/renovate-config#3.23.2"]`.
- Lines 7-11: mise group including the container. Lines 28-39: `lockFileMaintenance` for the global mise lock, `schedule: ["* * * * *"]`, groupName "global mise lockfile". Lines 44-51: disable per-tool PRs for `latest` via `matchCurrentValue: "/^latest$/"`.
- Lines 66-79: jsonata manager for `min_version` in `mise.toml` (github-releases, jdx/mise). Lines 80-88: regex manager for `mise_version="..."` in `unix/install.sh`. Lines 89-99: tombi schema URLs. Lines 100-108: PSScriptAnalyzer from `[vars]`.

Native Renovate mise manager (saved README): supports `mise.lock`, `mise.{env}.lock`, `lockFileMaintenance` (`mise lock --bump`), runs mise in safe mode after `mise trust`. A grep of its files finds no bootstrap, apt or brew support.

Key negatives: no customManager for `[bootstrap.packages]`, apt sources, brew or `apt:`; no `postUpgradeTasks` anywhere; lock refresh relies on the native manager only.

## Q5. Issues, PRs and discussions

Source: `gh api repos/{r}/issues?creator=risu729` (REST). The `gh search issues` route hit the 30/hour limit, so counts below come partly from earlier search JSON.

jdx/mise: 800 PRs and 11 issues by risu729 (2024-2026). Relevant:
- Lockfile identity and outcomes: #9984, #9985, #9988, #9989, #9992 (merged, May 2026); #10102 (aqua github_content raw URLs); #10226, #10239, #10463, #10599 (respect lockfile backend during locked installs, merged); #10937, #10547; closed: #10918, #10946 (migration/outcomes), #11392 (preserve os-restricted versions when pruning), #12198.
- Bootstrap, hooks and schema: #10202 (run_windows hook), #11004 (shell activation schema), #11039 (hooks schema), #11041, #11043, #11047, #11051, #11061, #11010 (preview hooks in dry runs), #12738, #12741 (dotfiles schema), all merged; closed: #12529 (accounts), #12759, #12760, #12789-#12792, #12815.
- Release age: #10491 (warn for system pnpm/bun `minimum_release_age`). Other: #11206, #12204 (system task precedence, closed), #7214 (npm via pnpm).

renovatebot/renovate: 15 PRs. Relevant:
- #44174 (merged 2026-06-30) "fix(manager/mise): install resolver tools during mise lock": adds mise, node, npm, golang, ruby to the lock toolConstraints. Originated in jdx/mise discussion #10563.
- #45278 "validate artifact-resolved versions" (closed, not merged).
- #33113 (mise backends), #32688, #35547 (config presets), #32954, #34025 (core tools).

jdx/mise-action: 11 PRs, for example #467, #474 (rust cache), #278 (MISE_ENV in cache key), #521 (wget fallback). jdx/hk: 15 items, not examined.

Note: the REST lists do not distinguish merged from closed; merged/closed labels above come from the earlier search JSON for the first 300 PRs.

## Q6. Patterns to copy, what does not fit, gaps

### Patterns to copy

Root config plus early-init overlay selection:
```toml
# .miserc.toml
auto_env = true
```

Single run command used after install (`unix/install.sh:196`):
```sh
mise --cd "${dotfiles_dir}" bootstrap --yes --update --force-dotfiles --locked --skip-dirty
```
For us, drop `--force-dotfiles` and `--skip-dirty`.

Per-OS packages in one table (`mise.toml:294-340`):
```toml
"apt:cmake" = "latest"                      # we use exact pins instead
"brew:git" = { os = "macos" }
"brew-cask:claude" = { os = "macos", adopt = true }
```

Tera hooks branching by OS:
```
{% if os() == "linux" %} ... {% endif %}
```

Renovate pin for mise in an install script (`DOT/.github/renovate.json5:80-88`, regex manager on `mise_version="..."`), the jsonata manager for `min_version` (lines 66-79), and the mise-action `with.version` manager (`REN default.json5:66-81`). Group them with the `ghcr.io/jdx/mise` image so one PR moves all pins.

Release-age gate (`REN default.json5:21-33`):
```json5
minimumReleaseAge: "1 day",
minimumReleaseAgeBehaviour: "timestamp-optional",
internalChecksFilter: "strict",
platformAutomerge: false,
```

Lockfile sidecar guard (`default.json5:276-280`): disable updates for `**/.mise/locks/**`.

CI: run the real bootstrap twice and then `mise doctor --json` failing on warnings; SHA-pin every action; `permissions: {}`; cache `~/.cache/mise/downloads-cas` keyed on `hashFiles('mise.lock')`.

Container: digest-pinned `ghcr.io/jdx/mise` multi-stage copy into `ubuntu:26.04@sha256`, with `MISE_DATA_DIR` outside `$HOME`, shims on PATH, and a version-drift check (`worker/docker/Dockerfile`). This is a useful hint for the non-root problem our hands-on test found.

Useful extras from the mise bootstrap docs: `mise bootstrap plan --detailed-exitcode` and `status --missing` suit CI drift checks; apt pins are `name=version` and a pinned package opts out of source moves (`apt.md`, Version pins).

### Does not fit

Personal dotfiles, brew casks, macOS defaults, WSL and Windows, the Cloudflare Worker delivery, `latest` unpinned apt (we require exact pins), and the `personal` profile.

### Gaps (what we must build)

1. Renovate cannot see `[bootstrap.packages]` or `[bootstrap.apt.sources]`. They have no regex or jsonata manager for it either. We need a customManager (regex on `"apt:name" = "ver"`) plus a deb datasource, or a scheduled script that refreshes pins.
2. Bootstrap packages are not recorded in `mise.lock`. Pin integrity for apt is only the version string.
3. No linux-arm64 in their lock, and no multi-arch matrix. We need `linux-arm64` in `lockfile_platforms`.
4. No root bootstrap followed by non-root use. Our `mise install --system --locked && mise reshim --system` finding has no counterpart here.
5. No devcontainer or toolchain image build, no conda toolchain, no `postUpgradeTasks`, and CI does not use mise-action `bootstrap: true`.

## UNVERIFIED

- GraphQL discussions query for risu729 in jdx/mise and renovatebot/renovate was not run; discussion #10563 is known only from the Renovate PR text.
- Issues and discussions inside risu729's own repos, and comments they left on others' threads, were not enumerated.
- jdx/hk items and mise's own bootstrap issue tracker were not examined.
- Nothing was executed: installer, CI jobs and Renovate behaviour are read from source, not run.
- `health.yml` appears to call `uses: $/.github/workflows/ci.yml`; the odd `$` was not resolved.
- Merged versus closed state for PRs beyond the first 300 is unconfirmed.

## Tools used and failed

Used: git (clones), gh REST (`repos/{r}/issues?creator=risu729&state=all`), gh search (partial), shell grep and sed, mise docs fetched into `<research-cache>/docs/risu729/mise-bootstrap-docs`.
Failed or limited: `gh search issues` (403 rate limit, 30/hour); one zsh quoting error (`= not found`); some outputs truncated and re-read in pieces. No fnox-proxied research tools were needed.
