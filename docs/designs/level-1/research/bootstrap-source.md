# mise bootstrap: source map for image builds (mise v2026.11.7)

Source read: tag v2026.11.7 (commit 531bdb947215b94ba1f3a3a78dd3f88af83e42ed), in a detached worktree. Paths below are relative to the mise repo root. Date of research: 2026-11-13. Nothing was run; `mise bootstrap` was not executed on this Mac.

## 1. `mise bootstrap --from <repo>?ref=<sha>`

- Flags and struct: `src/cli/bootstrap.rs` (~l.38-250). `--from`, `--adopt`, `--from-dir`, `--config-dir`, `--update`, `--upgrade`, `--only`/`--skip` (parts enum at l.261-283).
- URL parsing: `crates/mise-util/src/remote_source.rs:56-82` (`parse_git_repo`) splits a `?ref=` query and accepts a `git::` prefix.
- Clone: `checkout_bootstrap_repository` (`src/cli/bootstrap.rs:5775-5855`). Default location is `$MISE_DATA_DIR/bootstrap-repo`, or `--from-dir` (docs/bootstrap/from-repository.md table, ~l.28-36). `checkout_bootstrap_ref` (l.5711) checks out the ref; `update_bootstrap_ref` (l.5732) is used on `--update`. A full 40-char sha in `?ref=` pins the checkout; a branch or tag moves on `--update`. Without `--update`, an existing checkout is reused (see l.5775-5855).
- Git prerequisite: `crates/mise-system/src/git_prerequisites.rs` installs git/ssh through the host package manager if absent, so the base image should already have git and ca-certificates.
- `validate_bootstrap_checkout` (l.486) rejects a checkout that is not a valid bootstrap project.
- Child process: `run_from` (~l.2680) and `run_child_bootstrap` (~l.2815-2870) re-exec `mise bootstrap --cd <checkout>` with args from `bootstrap_from_child_args` (l.3173). Trust of the checkout is passed with `MISE_TRUSTED_CONFIG_PATHS`; `__MISE_BOOTSTRAP_CONFIG_UPDATED` signals that config changed.
- Global config in a container: `--adopt` clones to `~/.config/mise`; `--from` does not touch global config. Under root in a container that would be `/root/.config/mise`.
- Exit codes: the apt failure path below ends non-zero (driver aggregates failures, `crates/mise-system/src/driver.rs` l.63-330). I did not enumerate every exit code (UNVERIFIED).

## 2. Phases, order, and container behavior

- Run order: `run_phases` (`src/cli/bootstrap.rs` ~l.2090-2740); documented in `docs/bootstrap.md` table (~l.124-150): about 20 steps with hooks. A phase with nothing configured is a no-op.
- Tools phase: `Install::new_bare(self.dry_run, self.yes).run()` at `src/cli/bootstrap.rs:2665`. `new_bare` is `src/cli/install.rs:150`, a plain `mise install` with only `dry_run`/`yes` set.
- Systemd/launchd: `src/cli/system/install.rs` ~l.436-545 applies with a `skipped_reason`; `crates/mise-system/src/systemd.rs` ~l.282-296 `is_available` is false without systemd, so units are skipped, not failed. Do not configure `[bootstrap.systemd]`/launchd in the shared config for the image and the container is safe by default (UNVERIFIED for the exact message).
- Exclusion: `--only`/`--skip` take parts (l.261-283). The config also supports os filters on entries; I did not verify os filters on whole phases (UNVERIFIED).
- Shell phase: see `docs/bootstrap/shell.md:265`. Accounts: not exercised in my reading of the code (UNVERIFIED).

## 3. `[bootstrap.apt.sources]`

- Parsing: `crates/mise-system/src/lib.rs:2448-2473`; invalid entries are warned about and skipped.
- Writing: `crates/mise-system-packages/src/apt_sources.rs` (1129 lines). Output is a deb822 `.sources` file with the armored key inline in `Signed-By` (apt >= 2.4). Only declared fingerprints are kept; a mismatching key is rejected.
- Ordering: the driver applies sources first (`crates/mise-system/src/driver.rs` l.63-330), then runs one `apt-get update` (`apt.rs` `apply_sources` l.433-465; `lists_missing` l.31-43), then installs.
- Pins: `apt.rs` `install` (l.590-614) runs `apt-get install -y -- name=version`. `install_would_fail` (l.54-79) simulates first.
- If the pinned version disappears from apt.llvm.org: the simulation fails, mise runs `apt-get update`, install fails, and the run exits non-zero. There is no fallback to another version. This breaks `docker build` loudly, which is the desired behavior.
- Suites default to the release codename (`docs/bootstrap/packages/apt.md:91`). Whether apt.llvm.org publishes a suite for Ubuntu 26.04 must be checked independently (UNVERIFIED); set `suites` explicitly.
- arm64/amd64: I did not find per-arch handling in the source I read beyond apt's own `Architectures` field in deb822 (UNVERIFIED whether mise sets it).

## 4. Running as root: where tools land

- Sudo module: `crates/mise-ui/src/sudo.rs` (l.19, 163-215): as root, commands run directly; prompts only if `console::user_attended_stderr()`.
- `[tools]` from bootstrap use default `Install` options, so no `--system`. Install dir comes from `install_opts` (`src/cli/install.rs:~493`): `--system` -> `Settings::system_installs_dir()` (`crates/mise-util/src/dirs.rs:32-37`, default `/usr/local/share/mise/installs`, `crates/mise-util/src/env.rs:272-278`), else `--shared`, else `MISE_DATA_DIR` (default `$XDG_DATA_HOME/mise`, `env.rs:157-158`, so `/root/.local/share/mise` for root).
- Consequence: the non-root devcontainer user will NOT see root's installs unless `MISE_DATA_DIR` is set to a shared absolute path (e.g. `/opt/mise`) in the Dockerfile `ENV`, or the installs are made system-wide. System config dir is `/etc/mise` (`env.rs:192-196`, override `MISE_SYSTEM_CONFIG_DIR`); system shims `$MISE_SYSTEM_DATA_DIR/shims` (`dirs.rs:48-54`); `docs/dev-tools/system-installs.md:68-69` has the table.
- Discovery by another user: shims dir on PATH (`MISE_SHIMS_DIR` defaults to `$MISE_DATA_DIR/shims`, `env.rs:268-269`), or `mise activate`, or `mise reshim`. The user must also have read/exec access to the data dir.
- Conda relocatability: `src/backend/conda.rs:971-985` `render_unix_launcher` writes a `#!/bin/sh` launcher with the absolute prefix in `CONDA_PREFIX`, `CONDA_DEFAULT_ENV` and the exec target. The prefix is made absolute at l.639 (`std::path::absolute(tv.install_path())`). Conda text/binary prefix replacement during linking (l.367-384) also bakes the install path into files. So installs are not relocatable: the data dir path used during `docker build` must equal the runtime path. Same path in build and run is sufficient; copying the dir elsewhere or mounting a volume at a different path breaks it. Mounting a fresh volume over the data dir hides the baked tools.
- `mise generate devcontainer --mount-mise-data` mounts a volume at `/mnt/mise-data` (see 6), which would shadow an image-baked data dir; avoid it for baked images.

## 5. `--locked` and conda

- `Install` reads `locked: Settings::get().locked` (`src/cli/install.rs:532`). The setting is `MISE_LOCKED` (`settings.toml:2137-2160`); `--locked` is the same. Because bootstrap's tools phase calls `Install::new_bare`, which reads the global setting, `MISE_LOCKED=1` in the environment applies to bootstrap's tools phase. I found no `locked` reference in `src/cli/bootstrap.rs` (grep empty), so there is no bootstrap-specific flag; use the env var. The child process inherits the env.
- Locked semantics (`settings.toml:2138-2150`): a tool with no lockfile entry is an error; URL-locking backends need an entry for the current platform with a checksum (`locked_require_checksum`, `MISE_LOCKED_REQUIRE_CHECKSUM`, l.2163-2180); installs do not update the lockfile. `locked_scopes` (l.2184) defaults to global, project, system.
- Conda: conda download supports checksums for locked installs (`conda.rs:288, 348`), and extracting python info from locked basenames (l.409). Per-platform entries are required: create with `mise lock` for linux-arm64, linux-x64 (and macos-arm64). Exact platform key spelling for conda was not verified (UNVERIFIED).
- apt/brew `[bootstrap.packages]` are not covered by the tool lockfile; pins are the only reproducibility mechanism there.

## 6. Generated output

`mise generate devcontainer` (`src/cli/generate/devcontainer.rs`): JSON (pretty) with `name` (default "mise"), `image` (default `mcr.microsoft.com/devcontainers/base:ubuntu`, l.~97), `features` {`ghcr.io/devcontainers-extra/features/mise:1`: {}}, `customizations.vscode.extensions` [`hverlin.mise-vscode`], `mounts`, `containerEnv`, `remoteEnv`, `postCreateCommand` = `mise install`. With `--mount-mise-data`: volume `mise-data-volume` at `/mnt/mise-data`, `MISE_DATA_DIR=/mnt/mise-data`, `remoteEnv.PATH=${containerEnv:PATH}:/mnt/mise-data/shims`, and `postCreateCommand` = `sudo chown -R vscode:vscode /mnt/mise-data && mise install`. The feature version is a floating `:1`, not a pin, and it installs unpinned mise (UNVERIFIED version resolution). Not useful as is for a pinned image.

`mise generate install-script` (`src/cli/generate/install_script.rs`; `generate bootstrap` is a deprecated alias): emits a bash wrapper pinning a mise version (`--version`, else the latest release `self-update` would pick; l.~120). On first run it downloads `https://mise.jdx.dev/v{version}/install.sh`, verifies its minisign signature (`minisign::verify(&MISE_PUB_KEY, ...)`, l.~145) and runs it with `MISE_VERSION` and `MISE_INSTALL_PATH` (default `$MISE_DATA_DIR/bootstrap/mise-<version>`, l.58-62). So the version is pinned; integrity is a signature on the installer, not a checksum stored in the script for the bash variant. The Windows `.cmd` variant embeds SHA256 checksums resolved at generate time (l.~210-255). `MISE_VERSION` env can override the pin at run time.

## 7. Useful knobs for image builds

- `MISE_YES=1` (`settings.toml:5149-5157`): answers prompts including config trust; also on when `CI` is set. `--yes` on bootstrap sets `Install.yes` (`install.rs` skip field, ~l.140).
- `MISE_LOCKED=1`, `MISE_LOCKED_REQUIRE_CHECKSUM=1`.
- `MISE_DATA_DIR`, `MISE_SYSTEM_DATA_DIR`, `MISE_SYSTEM_CONFIG_DIR`, `MISE_SHIMS_DIR`, `MISE_INSTALLS_DIR` (`env.rs`).
- `bootstrap --only/--skip`, `--dry-run`, `--update`.
- `MISE_EXPERIMENTAL`: grep of `src/cli/bootstrap.rs` for "experimental" found nothing, so bootstrap does not appear to require it (UNVERIFIED that no gate exists elsewhere).

## Risks for docker build

1. Root installs go to `/root/.local/share/mise` by default; the devcontainer user will not find them. Set `MISE_DATA_DIR` to a shared absolute path in an `ENV` before bootstrap, and keep it identical at runtime.
2. Conda launchers and prefix replacement hard-code the absolute install path; never move or re-mount the data dir.
3. No TTY: set `MISE_YES=1` to avoid trust and confirmation prompts; sudo is bypassed as root.
4. A vanished pinned apt version or an unknown apt.llvm.org suite for 26.04 fails the build (intended); `apt-get update` runs once, so Docker layer caching can hide drift.
5. systemd/launchd phases are skipped without systemd; do not declare them in the shared config.
6. `MISE_LOCKED` is not a bootstrap flag; set it as env. Lockfile needs linux-arm64 and linux-x64 entries (and checksums).
7. `?ref=` must be a full sha for reproducibility; a branch name floats.
8. `--from` needs git in the image; mise may try to install it via apt.
9. The generated devcontainer uses a floating feature tag and a data volume that shadows baked tools.

## UNVERIFIED

- Whole-phase os filters; exact exit codes; apt `Architectures` handling per arch; apt.llvm.org suite for Ubuntu 26.04; conda lockfile platform key names; whether any experimental gate applies; behavior of accounts/shell phases in a container; devcontainer feature mise version.

## Tools used and failed

Used: Bash (git, grep, sed) on the v2026.11.7 worktree; `git fetch --tags` to get the tag. Failed or unused: no web tools. `git describe` initially found no tags until fetched.
