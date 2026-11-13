# Upstream research: mise bootstrap for a Mac + Ubuntu 26.04 image project

Date: 2026-11-13. Local mise 2026.11.7 (latest release v2026.11.7, 2026-11-12; releases are about daily).
Goal under study: one mise config that sets up an Apple Silicon Mac and builds Ubuntu 26.04 arm64/amd64 images by
running `mise bootstrap --from <repo>?ref=<sha>` inside `docker build`, later reused by devcontainers and GitHub
Actions job containers, everything pinned and Renovate-updated.

Repo for all numbers below is jdx/mise unless noted. Dates are 2026.

## 1. Key facts (verified from docs, source and release notes)

- `mise bootstrap --from <url>[?ref=<branch|tag|commit>]` clones to `$MISE_DATA_DIR/bootstrap-repo` (or `--from-dir`)
  and runs bootstrap from that project's `mise.toml`. `?ref=` arrived in v2026.9.18; `--config-dir` in v2026.10.21;
  `--save-env` in v2026.11.1; `--upgrade` in v2026.10.11. `--adopt` takes branches only.
- Cloning needs `git` before the repo's own `[bootstrap.packages]` can run. mise offers to install git/ssh via the host
  package manager (`--yes` accepts). In a Dockerfile, install `git ca-certificates curl` yourself first.
- `[bootstrap.packages]`: `"apt:curl" = "8.5.0-2ubuntu10"` is an exact pin, release-specific. `apt:gcc:arm64` is the
  arch qualifier. Selectors `os` (`linux/x64`, `macos/arm64`, `unix`) and `env`. Pinned or arch-qualified entries opt out
  of the "move to declared source" behaviour. `latest` entries are only upgraded by `mise bootstrap --upgrade`.
- Unprefixed keys (v2026.11.6, #15506) install through one manager, default order apt, dnf, pacman, zypper, apk, brew,
  winget, scoop, choco, with `names = {apt=..., dnf=...}`. `brew:` works on Linux x86_64 and arm64 without Homebrew.
- apt: `apt-get update` runs only when lists are empty or the simulated install fails (#13659, v2026.9.15); `--update`
  forces it. DEBIAN_FRONTEND=noninteractive is set; sudo is used when not root. mise never removes packages or sources.
- `[bootstrap.apt.sources]` (#14306, merged 10-12, v2026.10.9): writes `/etc/apt/sources.list.d/mise-<name>.sources`
  with an inline Signed-By key (apt >= 2.4). Non-PPA sources need `uris`, `key`, `fingerprint`; also `suites`,
  `components`, `architectures`. PPAs are Ubuntu-only. Dnf analog `[bootstrap.dnf.repos]` (#14401, v2026.10.10).
- `[bootstrap.files]` with `phase = "pre-packages"` (#13052, merged 09-10, v2026.9.5). For apt, follow with `--update`.
- Official images `ghcr.io/jdx/mise` / `jdxcode/mise` (amd64+arm64). Default tag is scratch; `-debian` is Debian 13 slim.
  Docs recommend `COPY --from=ghcr.io/jdx/mise@sha256:<digest> /usr/local/bin/mise ...` plus `mise install --locked`
  with `mise lock --platform linux-x64,linux-arm64`.
- `mise install --system` writes shared storage under `/usr/local/share/mise/installs`; auto-sudo (#13384) for aqua,
  github, gitlab, forgejo, http, s3. Running as root in a build is supported.
- `mise oci build` (experimental) applies project `[bootstrap.packages]` (apt/apk only) and `[dotfiles]`; it does NOT
  apply `[bootstrap.files]`, `[bootstrap.apt.sources]` or the bootstrap task, needs root for apt (#14447), needs a Linux
  host of the same arch (no cross-build). Not a fit for this goal; `docker build` + `mise bootstrap` is.
- `mise generate devcontainer [--image --mount-mise-data --name --write]` writes `.devcontainer/devcontainer.json`
  (default image `mcr.microsoft.com/devcontainers/base:ubuntu`). `mise generate install-script --write ./bin/mise`
  makes a pinned wrapper; `generate bootstrap` is a deprecated alias (removal 2027.9.0).
- mise-action (latest v5.2.8, 2026-11-12): `bootstrap: true`, `bootstrap_skip`, `bootstrap_args` (PR #522, merged
  06-17); uses `mise --locked bootstrap` when a lockfile exists; `install_args` cannot be combined with `bootstrap: true`.
  Ubuntu container images lack curl and wget (mise discussion #10488, open); wget fallback merged in mise-action #521.

## 2. Discussions (via GraphQL, type DISCUSSION)

| # | Title | Date / state | What was decided |
|---|---|---|---|
| [14945](https://github.com/jdx/mise/discussions/14945) | Bootstrapping from a dotfiles repository in one go | 10-24, open | jdx: use `--from ... --from-dir ~/.dotfiles --config-dir`; shipped via #14973, #14969, #15025 |
| [14588](https://github.com/jdx/mise/discussions/14588) | bootstrap: use package managers installed by pre-packages | 10-17, closed | Hook runs in a child process, so PATH changes do not reach the package phase; fixed for nix in #14596 |
| [14290](https://github.com/jdx/mise/discussions/14290) | Add support for apt ppas | 10-11, closed | jdx opened #14306. Quote: "A plain `mise bootstrap` ... now moves an installed package onto a declared source" |
| [13047](https://github.com/jdx/mise/discussions/13047) | Package repository files step | 09-10, closed | Became #13052 (pre-packages phase), v2026.9.5 |
| [14802](https://github.com/jdx/mise/discussions/14802) | Select one package manager for unprefixed entries | 10-21, closed | Became #15506, v2026.11.6 |
| [10480](https://github.com/jdx/mise/discussions/10480) | Run `mise bootstrap` before `mise install` in mise-action | 06-16, closed | mise-action #522 `bootstrap: true`; mise #10497 skip controls |
| [10488](https://github.com/jdx/mise/discussions/10488) | Do not require curl for the mise github action | 06-16, open | #521 wget fallback merged; Ubuntu image has neither curl nor wget, still open |
| [14848](https://github.com/jdx/mise/discussions/14848) | oci-image with rust keeps downloading rustup-init | 10-22 | Fixed in #14854 |
| [8596](https://github.com/jdx/mise/discussions/8596) | mise install --system fails | 03-14 | jdx: "`--system` is behaving as designed here, but the name oversells it" (shared install cache, not mise-free). Recommended `brew:` bootstrap packages for no-mise-at-runtime |
| [5789](https://github.com/jdx/mise/discussions/5789) | Add a generator for Docker images | 2025-07-25, open | No maintainer reply |
| [15554](https://github.com/jdx/mise/discussions/15554) / issue 15549 | bootstrap remote hang | 11-10 | Fixed in #15607 |
| [15316](https://github.com/jdx/mise/discussions/15316) | Named env sets | | Shipped v2026.11.1 |
| 15645, 15634 | `bootstrap plan --json`; reuse discovery | 11-12, ideas | Open ideas, no decision |

Not read in full (UNVERIFIED content): 14161 (git/openssh for bootstrap), 12081 (oci apk), 14425 (`--upgrade`).

## 3. Issues and PRs

| # | Title / topic | State |
|---|---|---|
| [14306](https://github.com/jdx/mise/pull/14306) | `[bootstrap.apt.sources]` | merged 10-12 |
| 14395 | docs missing for apt.sources | closed 10-13 |
| 14401 | `[bootstrap.dnf.repos]` | merged |
| [13052](https://github.com/jdx/mise/pull/13052) | pre-packages files phase | merged 09-10 |
| 13659 / 13653 | apt update fallback on simulate failure / issue | merged / closed |
| 14291, 14296, 14447, 14968 | oci build apt failures, root requirement, absolute symlinks | closed/merged (14447 on 10-14) |
| 14548 | templated repos url/ref | merged 10-16 |
| 13935 | docs: pinned packslip bootstraps for Docker | merged 10-04 |
| 13384 | auto-elevate system installs | merged 09-19 |
| 15520 | non-root read-only system global links | closed 11-09 |
| 15130 | lockfile with dotfiles checkout | merged |
| 15607 | bootstrap remote home refusal | merged 11-11 |

Releases since 2026.9: v2026.9.5 pre-packages phase; 9.11/9.12 docker images (`latest` is scratch); 9.15 apt update
fallback; 9.18 `--from ?ref=`, install-script fix, git/oci includes; 10.9 apt.sources, debian image libatomic1; 10.10
dnf repos, snap, `--adopt ?ref`; 10.11 `--upgrade`, oci apt as root, docs recommend committing `mise.lock`; 10.18 CA
fallback (rustls); 10.21 `--config-dir`; 10.24 `extra_ca_certs`; 11.0 `--update` pulls global config checkout; 11.1
`--save-env`, lockfile v4; 11.4 `zip::` includes; 11.6 unprefixed packages.

## 4. Real public repos (ranked, with what to copy)

Checked by reading the files via `gh api`. Stars and last push from the API on 2026-11-13. No repo was found that uses
`mise bootstrap --from` itself in a Dockerfile (search "mise bootstrap --from" found only zachbornheimer/dev-profile
tests); the in-image pattern is `mise bootstrap` run against a copied or cloned project.

| Rank | Repo | Where | What to copy |
|---|---|---|---|
| 1 | [ray-manaloto/dotfiles-legacy](https://github.com/ray-manaloto/dotfiles-legacy) (owner's own) `.devcontainer/Dockerfile`, `mise-system.toml` | Ubuntu 26.04 resolute image | The full pattern: LLVM apt source written by hand with fingerprint assertion before key trust, then `mise bootstrap packages apply --manager apt --yes --update` and `status --json --missing` as a post-check, exact apt pins for all packages, `ARG MISE_VERSION` pinned and Renovate-bumped, base image digest pin, `mise install --system --locked`. Finding recorded there: "mise.lock does NOT cover bootstrap packages". Now replaceable by `[bootstrap.apt.sources]`. |
| 2 | [wagov-dtt/devcontainer-base](https://github.com/wagov-dtt/devcontainer-base) `Dockerfile` (pushed 2026-07-03, 2 stars) | Debian devcontainer base | Two-phase split: root runs `mise bootstrap packages install --yes --update -E apt` from a separate `mise.apt.toml`, then `sudo -Hu vscode mise bootstrap --yes` for user space. Multi-stage `FROM scratch` copy of the result. Secret mount for GITHUB_TOKEN. |
| 3 | [roalcantara/dots](https://github.com/roalcantara/dots) `distros/ubuntu/Dockerfile` (pushed 2026-11-12) | Mac + Ubuntu dotfiles in one repo | Closest to the stated goal: `FROM mcr.microsoft.com/devcontainers/base:ubuntu`, `curl https://mise.run \| MISE_VERSION=v2026.11.4 sh`, `mise bootstrap -E container --force-dotfiles --skip user --yes`. Copy the `-E container` env split, `--skip user`, and the local vs git-clone-remote build stages. Note it clones with `git clone --branch` instead of `--from`. |
| 4 | [chancez/dotfiles](https://github.com/chancez/dotfiles) `Dockerfile` (20 stars, pushed 2026-11-12) | Dotfiles image | Cache-warmer layer (copy only mise config, pre-install `[tools]`), then `mise bootstrap --dry-run`, `mise bootstrap --yes`, then `mise dotfiles status --missing` to fail the build on drift. |
| 5 | [shepherdjerred/monorepo](https://github.com/shepherdjerred/monorepo) `ci/ci-playwright/Dockerfile` (92 stars) | CI job container images | "Same signed mise bootstrap as ci-base", with `# renovate: datasource=github-releases depName=jdx/mise` on the version pin and scoped installs (only the needed package scope). Good model for CI job containers. |
| 6 | [statox/claude-devcontainer](https://github.com/statox/claude-devcontainer) `devcontainer/agent/Dockerfile` | Devcontainer | `mise bootstrap packages apply --yes` as root before handing `/mise` to the dev user. |
| 7 | [klab365/klab-pytest-toolkit](https://github.com/klab365/klab-pytest-toolkit) `.devcontainer/Dockerfile` | Devcontainer | Keeps the Dockerfile minimal; `[bootstrap.packages]` in `mise.toml` is the single source for local, CI and container, applied in `postStartCommand`. |
| 8 | [naa0yama/rotel](https://github.com/naa0yama/rotel) `.devcontainer/postStartCommand.sh` (same in several naa0yama repos) | Devcontainer | Pinned mise install with `## renovate: datasource=github-releases packageName=jdx/mise versioning=calver:YYYY.M.D automerge=true` comment. |

Also seen: himkt/config and TechDufus/dotfiles (`.github/workflows` run `mise bootstrap` as a CI check),
nettlesh/dotfiles (`mise bootstrap packages apply` and `files apply` on Arch), lepinkainen/dotfiles `mise-poc`.
Bump PRs for `ghcr.io/jdx/mise` appear in eclipse-opensovd/opensovd-core#249, bde-dev/devcontainer-images#42,
davydehaas98/homelab#1477, so Renovate already tracks the official image in the wild.

## 5. Renovate coverage

- Renovate's mise manager docs (checked in `lib/modules/manager/mise/readme.md`, main) cover: top-level `tools`,
  `tasks.*.tools`, remote git task files, remote `include` (`git::...?ref=` as git tags; `oci::` as docker), sha pins
  with a trailing `# version` comment, and `mise.lock` (lockedVersion, lock updates, `lockFileMaintenance` running
  `mise lock --bump`). The readme says `include` entries are not locked by `mise.lock`.
- `[bootstrap.packages]` and `[bootstrap.apt.sources]` are NOT parsed. The readme has no mention of bootstrap. The
  owner's earlier research (dotfiles-legacy renovate.json, #251/#288) states the schema "parses only tools/tasks and
  z.object silently strips [bootstrap.packages]". I did not find a renovatebot/renovate issue or discussion on this
  (GitHub search for "mise bootstrap", "bootstrap.packages", "mise apt" returned nothing relevant). Treat "no upstream
  issue exists" as UNVERIFIED because issue search is keyword-limited.
- Workaround proven in dotfiles-legacy: a regex customManager on `.devcontainer/mise-system.toml` with the `deb`
  datasource. Match string: `"apt:(?<depName>[a-z0-9.+-]+)"\s*=\s*"(?<currentValue>(?:\d+:(?<llvmMajor>\d+)(?:\.\d+)*~\+\+\d{14}\+[0-9a-f]+-1~exp1~[^"]*|[0-9][^"]*))"`.
  `registryUrlTemplate` picks the suite: apt.llvm.org per LLVM major, else
  `https://archive.ubuntu.com/ubuntu?suite=resolute&components=main&binaryArch=amd64`. A scoped packageRule
  (`matchDatasources: ["deb"]`) overrides registryUrls with the release, `-updates` and `-security` pockets
  (registryStrategy merge). A second rule groups LLVM snapshot debs and automerges. Gotchas recorded there: RE2 has no
  lookahead, so the value regex anchors on a leading digit; the `deb` datasource emits no releaseTimestamp, so
  `minimumReleaseAge` gives no soak; the binaryArch in the URL is amd64 only, so arm64 versions are not checked
  (UNVERIFIED whether Ubuntu versions ever differ between arches, they normally do not for `Architecture: all`/same
  source builds, but binary-only rebuilds can).
- Other custom managers in the same file worth copying: `ARG MISE_VERSION=` (github-releases), ubuntu base image
  `ubuntu:<ver>@sha256:` digest in Dockerfile and bake HCL (datasource docker), git-refs for a pinned sha.
- jdx/renovate-config `default.json` (read 2026-11-13): extends `config:recommended`, `docker:pinDigests`,
  `helpers:pinGitHubActionDigests`; `minimumReleaseAge` 7 days; `lockFileMaintenance` enabled; ignores
  `**/.mise/locks/**`; groups "mise tools" non-major; has rules for `ghcr.io/jdx/mise`. It has no bootstrap or apt
  rules. Useful to copy the digest-pinning and release-age settings.
- Because bootstrap packages are not in `mise.lock`, an exact apt pin in `mise.toml` converts silent drift into a loud
  build failure (the dotfiles-legacy rationale). Ubuntu archives drop old versions from `-updates`/`-security` pockets
  over time, so pins rot and need the Renovate regex manager to stay buildable.

## 6. last30days run (query "mise bootstrap devcontainer docker jdx")

Ran with `--auto-resolve` (no host plan), Python 3.13 through a local TLS proxy. Many sources failed with the known
`Missing Authority Key Identifier` TLS error (Reddit, ScrapeCreators TikTok/Instagram/YouTube, LLM rerank); Reddit also
403. Usable sources: X (8 posts) and GitHub (7 items). Findings, low volume:
- X, 2026-11-08, @Dennis_Rye: tool that inspects a system and builds "a mise bootstrap of your system and a single
  command to run it" ([post](https://x.com/Dennis_Rye/status/2119540969942974551)).
- X, 2026-10-29, @kattyancmp: Japanese blog on putting Mac and Ubuntu setup into one dotfiles repo with
  `mise bootstrap` ([post](https://x.com/kattyancmp/status/2115856307760820703)). Same goal as this project.
- X, 2026-11-07, @diffrinse: prefers nix-darwin, calling `mise bootstrap` "messy" (one negative opinion, no detail).
- GitHub: only Renovate bump PRs for `ghcr.io/jdx/mise` (see section 4). No new bootstrap-in-Docker discussion found.
Result: nothing contradicts section 1; no HN, Reddit or YouTube coverage was obtained.

## 7. Open gaps worth an upstream request (drafted text only, NOT posted)

1. Title: "bootstrap: record `[bootstrap.packages]` resolved versions and package checksums in mise.lock". Body: mise.lock
   pins tool URLs/checksums per platform, but apt/brew/dnf bootstrap packages are outside it, so a `latest` entry
   drifts silently while a content hash of the config says unchanged. Request: `mise lock` (or `bootstrap lock`) writes
   resolved version per manager and per arch (apt amd64 and arm64), and `mise --locked bootstrap` fails on mismatch.
2. Title: "bootstrap: first-class docs for `docker build` as root without sudo". Body: document the supported recipe
   (install git/ca-certificates/curl, `mise bootstrap --from <repo>?ref=<full sha> --yes`, root vs non-root split,
   expected layout, cache mounts for `/var/cache/apt` and `/var/lib/apt/lists`, `--skip user`).
3. Title: "bootstrap --from: option to require a full commit sha (reject branch/tag refs)". Reason: reproducible image
   builds; paranoid mode already requires full sha for includes.
4. Title: "mise oci build: apply `[bootstrap.apt.sources]` and `[bootstrap.files]` pre-packages". Reason: oci build
   currently silently skips them so a project that needs a third-party apt repo cannot use oci build.
5. Title: "apt pins that differ per architecture". Request: allow `"apt:curl" = {amd64 = "...", arm64 = "..."}` or a
   documented way to carry two pins, because multi-arch images may see different binary versions.
6. For renovatebot/renovate: "mise manager: extract `[bootstrap.packages]` apt pins (deb datasource) and
   `[bootstrap.apt.sources]` fingerprints". Body: the readme and schema ignore the section; users need regex managers.

## 8. UNVERIFIED

- That `mise bootstrap --from <repo>?ref=<full sha>` works end to end inside `docker build` as root without sudo, on
  both arches. Docs and CLI help say `?ref=` accepts a commit; I did not run it.
- That `mise.lock` omits bootstrap packages in mise 2026.11.7. Evidence is the owner's own 2026 notes (#288) and absence
  of any mention in docs; I did not run `mise lock` with bootstrap packages.
- Whether the Renovate `deb` datasource handles an arm64-only version difference (the owner's manager queries amd64).
- Whether `brew:` bottles pour correctly on linux/arm64 for the packages you need.
- Discussions 14161, 12081, 14425 content; discussion 5789 had no replies as of read.
- Absence of a renovatebot/renovate issue about bootstrap packages.
- Star counts and push dates are as of 2026-11-13 and change daily.

## 9. Tools used and failed

Used: `gh api` (REST and GraphQL for jdx/mise discussions, issues, releases, file contents), `gh search code`
(worked but rate-limited, so spaced with sleeps; the first multi-word `gh search issues` calls returned empty, so a
GraphQL search helper replaced them), `curl` on mise and Renovate docs and the Renovate repo readme, local read of a
dotfiles-legacy snapshot under `<research-cache>/repos/dotfiles`, and the last30days v3.38.1 engine.
Failed or partial: last30days Reddit/TikTok/Instagram/YouTube/rerank (TLS "Missing Authority Key Identifier" through the local
proxy on Python 3.13; Reddit 403; Digg CLI unknown flag); Exa and Firecrawl were not used (gh code search and
direct file reads covered item 2); several docs URLs 404 until corrected from
the repo tree.
