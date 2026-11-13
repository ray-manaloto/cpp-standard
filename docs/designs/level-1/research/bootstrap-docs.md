# mise bootstrap project: docs research (2026-11-13)

Scope: one mise bootstrap project in ray-manaloto/cpp-standard for (a) a fresh Apple Silicon Mac and
(b) Ubuntu 26.04 linux/arm64 + linux/amd64 container images, applied with
`mise bootstrap --from <repo>?ref=<sha>`. Base URL for all pages: https://mise.jdx.dev

## 0. Sources and version check

- Installed: `mise 2026.11.7 macos-arm64 (2026-11-11)`.
- Offline clone `<research-cache>/repos/mise/docs/` is at commit a290bd0b3 (2026-11-12),
  one day after the 2026.11.7 release. It is NOT an exact tag checkout; treat it as 2026.11.7 plus at most one day of changes.
- Live check: curl of bootstrap/from-repository, bootstrap/packages/apt, dev-tools/system-installs, dev-tools/mise-lock all
  returned HTTP 200; the live apt page contains `bootstrap.apt.sources` and `Signed-By`, matching the offline text.
  Full line-by-line diff was NOT done (see UNVERIFIED).
- Saved pages: `<research-cache>/docs/mise-bootstrap/` (26 files: offline copies named
  `<dir>_<page>.md`, plus 4 `live_*.txt` text extracts of the live pages).
- Pages read: bootstrap, bootstrap/setup, from-repository, files, modules, packages/index, apt, brew, cli/bootstrap,
  cli/generate (+config, devcontainer, install-script), cli/lock, system-installs, install-layout, mise-lock,
  mise-lock-reference, backends/conda, shims, environments, directories, mise-cookbook/docker, continuous-integration,
  ide-integration, security (trust part only), dev-tools/index (OS-specific tools).
  Not read in full: bootstrap/hooks beyond the section in bootstrap.md, cli/trust, cli/bootstrap/packages/apply.
  (There is no separate hooks page; hooks live under bootstrap.md#hooks.)

## 1. Annotated skeleton `mise.toml` (bootstrap project root)

Project layout (from-repository, "A bootstrap project"; modules.md: "use `mise.toml` and `mise.ssh.toml` in the project directory"):

```
mise.toml            # shared: tools, tasks, hooks
mise.linux.toml      # linux-only packages/sources   (needs auto_env or -E linux)
mise.macos.toml      # mac-only packages             (needs auto_env or -E macos)
mise.lock            # lockfile for [tools]
.miserc.toml         # env/auto_env selection (see Q1)
```

```toml
# --- [settings] -------------------------------------------------------------
# lockfile / locked: mise-lock.md. "lockfile = true" writes mise.lock; --locked or MISE_LOCKED=1 refuses to resolve.
[settings]
lockfile = true
# Pin which platforms mise.lock covers (mise-lock.md; cli/lock.md --platform):
# lockfile_platforms is NOT verified as a setting name; use `mise lock --platform ...` (see Q5).

# --- [tools] (bootstrap.md run step 16, after packages step 4) ---------------
[tools]
cmake  = "4.5.0"          # exact; dev-tools. Resolved/locked in mise.lock
ninja  = "1.13.1"         # example version, confirm
sccache = "0.10.0"        # example version, confirm
vcpkg  = "latest"         # pin exact before use; UNVERIFIED registry name/version
gcovr  = "8.3"            # python tool, example version
# conda gxx (Linux only). os filter on tools: dev-tools/index.md "OS-specific tools"
"conda:gxx" = { version = "16.2.0", os = ["linux"] }   # conda.md; lockfile records url+checksum per platform

# --- [bootstrap.apt.sources] (apt.md#sources) --- Linux only: put in mise.linux.toml ---
[bootstrap.apt.sources.llvm]
uris          = "https://apt.llvm.org/resolute/"
suites        = "llvm-toolchain-resolute-23"
components    = "main"
architectures = ["amd64", "arm64"]          # apt.md: "architectures: Optional, such as amd64"; list form UNVERIFIED
key           = "https://apt.llvm.org/llvm-snapshot.gpg.key"
fingerprint   = "6084 F3CF 814B 57C1 CF12  EFD5 15CF 4D18 AF4F 7421"   # VERIFY against the key before use
# Output: /etc/apt/sources.list.d/mise-llvm.sources with inline Signed-By (apt.md#sources).

# --- [bootstrap.packages] (packages/index.md) ---
# Linux (mise.linux.toml): apt pin syntax "apt:curl" = "8.5.0-2ubuntu10" (apt.md)
[bootstrap.packages]
"apt:clang-23"       = "1:23.1.0~++XXXXXXXX-1~exp1~XXXXXXXX"   # exact apt.llvm.org version string: fill from apt-cache policy
"apt:libc++-23-dev"  = "..."
"apt:clang-tidy-23"  = "..."
"apt:valgrind"       = "latest"
# macOS (mise.macos.toml): brew cannot pin (brew.md); "latest" only, or versioned formulae
"brew:llvm" = "latest"
"brew:lld"  = "latest"
"brew:gcc"  = "latest"      # cannot hold 16.2.0 exactly; see Q2/gaps

# --- hooks (bootstrap.md#hooks); no os filter, only run_windows ---
[bootstrap.hooks.post-tools]
run = ["mise exec -- cmake --version", "mise exec -- ninja --version"]

# --- tasks (bootstrap.md#the-bootstrap-task: step 20 runs [tasks.bootstrap]) ---
[tasks.bootstrap]
run = "echo bootstrap project done"
```

All version strings above marked "example" or "..." are placeholders, not facts from the docs.

## 2. Answers

### Q1. Bootstrap project layout, `-E` environments, os/arch filters

from-repository.md#a-bootstrap-project: the repo is a normal mise project dir; `mise bootstrap --from <url>?ref=<branch|tag|commit>`
checks out to `$MISE_DATA_DIR/bootstrap-repo` (or `--from-dir`); `--update` fast-forwards. mise "trusts that configuration for this run"
(from-repository.md line 48), and the global config still loads.

Environments (environments.md, modules.md): `mise.<env>.toml` loads when env `<env>` is active, via `-E <env>`/`MISE_ENV` or `env = [...]` in miserc.
modules.md: "To pick modules for one run, use `mise -E ssh,gpg bootstrap`." "When two modules in the same directory declare the same key, the one listed later in `env` wins."
Platform environments: `auto_env` (settings; `mise.linux.toml`, `mise.macos-arm64.toml`) is off by default until 2027.6.0 and is set in `.miserc.toml`.
Practical rule: container build must run `mise -E linux bootstrap ...` (or enable `auto_env`), otherwise `mise.linux.toml` packages are silently not applied.

Inline os filters (bootstrap/packages/index.md): `"brew:jq" = { os = ["macos/arm64", "linux"] }`; `ripgrep = { version = "15", os = ["linux", "macos"] }`.
`os` accepts `linux`, `macos`, `unix`, `linux/x64`, `macos/arm64` (with aliases). Packages also take `env`. Tools accept `os` (dev-tools/index.md).
Hooks have no os filter (only `run_windows`). Files accept `os`.
Recommendation: put brew and apt entries in one `mise.toml` using `os` filters; this avoids dependence on `auto_env`/`-E`.

### Q2. `[bootstrap.apt.sources]`, apt pins, pre-packages files/hooks, phase order

Schema (apt.md#sources): fields `uris`, `suites` (defaults to release codename), `components` (default `main`), `architectures` (optional), `key` (http(s) URL, armored or binary),
`fingerprint` (full fingerprint or list; spaces ignored), and `ppa = "owner/archive"`. Quote: "Any other repository needs `uris`, `key`, and `fingerprint`".
"mise keeps only the keys whose fingerprints you declared from what it downloads, and fails if one is missing."
Output: "mise writes `/etc/apt/sources.list.d/mise-<name>.sources` with the signing key embedded in its `Signed-By` field" (needs apt 2.4+; Ubuntu 26.04 is fine).
"When it adds or changes a source, mise runs `apt-get update` once before installing. Without `--yes`, mise asks before it adds or changes any source". "mise does not remove sources."
Version pins: `"apt:curl" = "8.5.0-2ubuntu10"`; "A version pin or an architecture-qualified name opts a package out" of the declared-source move.
Pre-packages: files with `phase = "pre-packages"` (files.md#files-before-packages) plus hook `pre-packages`. Per bootstrap.md: "In step 4, the `pre-packages` hook runs before mise adds apt sources."
Phase order (bootstrap.md#how-it-runs, 21 steps): 1 accounts, 2 plugins, 3 pre-packages files, 4 apt sources then packages (hooks pre-/post-packages), 5 remaining files, 6 services, ... 9 repos, 10 dotfiles, 12 macos-defaults, 15 user, 16 tools (hooks pre-/post-tools), 17 plugin packages, 18 settings, 19 services, 20 `bootstrap` task, 21 final hook.
Consequence: apt/brew packages install BEFORE `[tools]`; a tool needing a system library can rely on the package already being present. Hook phases: pre/post-packages, repos, dotfiles, defaults, user, tools, and final.
Brew (brew.md): no version pinning for ordinary formulae (bottles exist only for the current version); only versioned formulae such as `postgresql@17`. So gcc 16.2.0 via `brew:gcc` cannot be exact; options are `brew:gcc@16` if such a formula exists (UNVERIFIED) or conda `gxx` on macOS too (osx-arm64 subdir exists, conda.md).

### Q3. System vs user installs, layout, shims vs PATH

system-installs.md: `mise install --system` installs to `/usr/local/share/mise/installs` (or `MISE_SYSTEM_DATA_DIR/installs`); related: `MISE_SYSTEM_INSTALLS_DIR`, `MISE_SYSTEM_SHIMS_DIR`, system config `/etc/mise` (`/etc/mise/config.toml` declares the versions).
`mise reshim --system`. Root can run it directly; otherwise sudo per `system_packages.sudo`. Elevated installs cover aqua, github, gitlab, forgejo, http, s3 backends only (conda is not listed; so conda via `--system` is UNVERIFIED and likely unsupported).
install-layout.md: identity layout is experimental; not needed here.
directories.md: user data dir `~/.local/share/mise`; "Do not set [directory variables] in `[env]`". Running bootstrap as root in `docker build` places `[tools]` in root's `~/.local/share/mise`, unreadable/irrelevant to a non-root devcontainer user.
Recommended for images: set `MISE_DATA_DIR=/opt/mise` (and `MISE_CONFIG_DIR`) as image `ENV` at build and run time, or use `--system`; put `/opt/mise/shims` (or `$MISE_DATA_DIR/shims`) on image `PATH`.
shims.md: shims work in non-interactive shells where `mise activate` is not run, which is the GHA `container:` case and devcontainer `postCreate`. cookbook/docker.md warns that mounting the home dir into a devcontainer hides installs, "which favors `--system`".
GHA container job: no login shell, so PATH must come from the image `ENV` (shims dir) or from `jdx/mise-action` / `mise exec` / `mise run` ("use `mise exec`/`mise run` instead of activation", continuous-integration.md).

### Q4. generate devcontainer / install-script / config

- `mise generate devcontainer` (cli/generate/devcontainer.md): emits `.devcontainer/devcontainer.json` using the mise dev container feature, `postCreateCommand` `mise install`, option `--mount-mise-data`. Fit: partial. It installs mise via the feature on a base image, but does NOT run `mise bootstrap` (no apt sources) so it is a template to edit, not the image builder. Use it as a starting point and change `postCreateCommand` to `mise bootstrap --only packages,tools --yes` if mise is preinstalled.
- `mise generate install-script` (cli/generate/install-script.md): generates a pinned mise installer wrapper with embedded checksums; flags `--version`, `--localize`, `--write`. Fit: good for the Dockerfile `RUN` that installs mise with a fixed version and checksum on both arm64 and amd64 (verify that the script embeds both linux-arm64 and linux-x64 checksums: UNVERIFIED).
- `mise generate config` (cli/generate/config.md): starter `mise.toml`; trivial, not needed.
- cookbook/docker.md alternatives: official `ghcr.io/jdx/mise:<ver>-debian` image (pin by digest; Debian, not Ubuntu 26.04 -> mismatch), a verified minisign release download, or `mise.run` with `MISE_VERSION`. Recommended pattern from the cookbook: `RUN mise trust && mise install --locked`.

### Q5. Lockfile coverage

mise-lock.md / mise-lock-reference.md: `mise.lock` (lockfile_version 4) records, per tool, version plus per-platform url/checksum; conda entries have url, checksum and deps per platform. Platform keys: `linux-x64`, `linux-arm64`, `macos-arm64`.
Generate for all three: `mise lock --platform linux-x64,linux-arm64,macos-arm64` (cli/lock.md). Enforce: `mise install --locked` or `MISE_LOCKED=1`; `jdx/mise-action@v5` adds `--locked` itself.
`mise.<env>.toml` gets its own `mise.<env>.lock`. If you split into `mise.linux.toml`, tools declared there lock to `mise.linux.lock`.
`[bootstrap.packages]` (apt, brew) are NOT in mise.lock (prior finding confirmed: nothing in mise-lock.md or the reference covers them). Drift detection: `mise bootstrap packages status --missing`. Apt exactness comes only from the `name=version` pin; brew has none.
Note on conda: the conda backend gives an isolated prefix per tool plus a launcher; only the requested package's commands reach PATH. Whether `gxx` exposes `g++` unprefixed (vs `x86_64-conda-linux-gnu-g++`) is UNVERIFIED.

### Q6. Non-interactive root in `docker build`

bootstrap cli (cli/bootstrap.md): `--yes` (also `MISE_YES`, and the `yes` setting turned on in CI) skips prompts, including the apt source prompt; `--dry-run` previews; `--update` refreshes apt metadata/fast-forwards the repo; `--only packages,tools`, `--skip`, `--upgrade`.
Docs example: `mise bootstrap packages apply --yes` then `mise install`; or `mise bootstrap --only packages,tools --yes`.
apt (apt.md): runs with `DEBIAN_FRONTEND=noninteractive`; as root no sudo is needed.
Trust: `--from` trusts the checked-out project config for that run; for later `mise install` in a Dockerfile use `mise trust` (cookbook: `RUN mise trust && mise install --locked`). Under CI mise auto-trusts.
Commands: `RUN mise bootstrap --from https://github.com/ray-manaloto/cpp-standard?ref=<sha> --yes --only packages,tools` then `mise install --locked` is NOT needed as tools step runs; whether `--locked` is honored by the bootstrap tools step is UNVERIFIED (set `MISE_LOCKED=1`).

### Q7. Renovate/Dependabot / updating pins

Docs mention Renovate only for reading Python sidecars; Dependabot is not mentioned. Documented flow: scheduled `mise lock --bump [--json] [--dry-run]` then PR; `MISE_SAFE=1` for bots. This covers `[tools]` and `mise.lock` only.
apt pins and the `?ref=<sha>` in the Dockerfile/devcontainer/workflow need custom updating (a scheduled job running `apt-cache policy` in the image, and a regex Renovate manager) - not documented by mise; UNVERIFIED design.

## 3. Gaps the docs do not cover

- No way to pin brew formula versions through bootstrap (gcc 16.2.0 on macOS).
- Bootstrap packages are absent from mise.lock; no apt checksum/lock.
- Hooks have no `os` filter.
- No documented multi-arch image recipe for bootstrap; `mise oci build` excluded.
- No documented `architectures` list syntax example; no example of a `suites` with a trailing-slash path combined with components for apt.llvm.org.
- No guidance for using `--from` inside a GHA `container:` job beyond mise-action.
- Interaction of `--system` with the conda backend is not stated.
- Dependabot/Renovate support for `mise.toml`/`mise.lock` versions beyond `mise lock --bump`.

## 4. UNVERIFIED

- Exact apt.llvm.org fingerprint, suite name `llvm-toolchain-resolute-23`, version strings (must be read from `apt-cache policy` in a 26.04 container).
- `architectures` accepting a TOML list.
- `lockfile_platforms` setting name.
- Whether `brew:gcc@16` exists; whether `conda:gxx` exposes unprefixed `g++`/`gcc`.
- Whether `conda:` works with `--system`.
- Whether `mise bootstrap` tools step honors `MISE_LOCKED`.
- Whether `install-script` embeds checksums for both Linux architectures.
- Live site vs offline diff for all pages (only 4 pages fetched, spot-checked for key strings); offline clone is 1 day newer than 2026.11.7.
- Not read in full: cli/trust, cli/bootstrap/packages/apply, bootstrap/files.md past line ~330, rest of security.md.
- Tool example versions in the skeleton (ninja, sccache, gcovr, vcpkg, cmake patch).
- Nothing was executed (no `mise bootstrap` dry run, no container test).

## 5. Tools used and failed

- Used: Bash (cat/sed/grep/cp/curl/git), Read on offline mise docs clone. curl for live pages (HTTP 200, text extracted with python3 stdlib, no proxy).
- Not used: Firecrawl, Exa, Context7, fnox proxy (curl worked without keys).
- Failures: initial `ls` of the missing output dir; one zsh glob error (retried); one truncated cat (re-read with Read).
