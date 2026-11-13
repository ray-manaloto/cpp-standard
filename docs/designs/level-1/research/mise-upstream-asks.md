# Upstream asks for mise bootstrap image builds (drafts, NOT posted)

Date: 2026-11-13. Nothing was posted, commented, reacted, forked or committed. Searched jdx/mise at main `a290bd0` (2026-11-12 21:25 CST, after v2026.11.7; open release PR #15617 = 2026.11.8) and renovatebot/renovate main.

## 0. How jdx wants requests (CONTRIBUTING.md, docs/contributing.md, .github/ISSUE_TEMPLATE/config.yml)

- **mise accepts no external pull requests** ("GitHub does not let anyone outside the maintainer team create one"). Feature requests go to **Discussions, category Ideas** ("Share ideas for new features"); the issue chooser has `blank_issues_enabled: false` and points to Discussions ("Questions and Ideas"). Bug reports go to Discussions "Troubleshooting and bug reports" (asks for `mise doctor` output).
- Bug reports "are only for problems you ran into while using mise... Reports found by reading the source or by having an agent search the code will be closed." So lead with what we ran; use source citations only as supporting detail.
- AI help is allowed but must end with a disclosure line: `*AI-assisted — Tool: <tool>; model: <provider>/<model>; version: <version-or-unavailable>.*`
- Pattern in comparable threads: jdx replies within hours and implements the request himself (#14535 -> #14548 same day; #12081 -> #12083 next day; #8549 -> #8581 same day; #10549 gave a design sketch). A short, concrete Ideas post with a proposed shape works.
- Renovate: discussions are "our preferred starting point"; template `suggest-an-idea.yml` has one free-text field.

## 1. Gap table

| Gap | Existing thread? | Status | Recommendation |
|---|---|---|---|
| G1 bootstrap tools step is a bare `mise install` (root data dir) | No thread for bootstrap + install location. Related: [#8549](https://github.com/jdx/mise/discussions/8549) Shared directory for mise installs (open, Ideas, 2026-03-10; jdx: "+1", implemented in #8581 -> `/usr/local/share/mise`); [#8596](https://github.com/jdx/mise/discussions/8596) `install --system` fails (open; jdx: "behaving as designed... name oversells it", #12253 docs); PR #15526 (merged 11-10, non-root read-only system global links) | Not landed. v2026.11.7 and main still call `Install::new_bare` (src/cli/bootstrap.rs:2733) | Post Discussion A |
| G2 `mise oci build` ignores `[bootstrap.apt.sources]`, pre-packages files, hooks | No thread for apt.sources. Related, all closed: #12081 (apk entries, implemented #12083), #10687 (apt layer non-reproducible), #14291 (apt failures), #10549 (dotfiles in OCI, `~` is /root), #10934 (`--copy`). Docs state "Other `[bootstrap]` sections, such as `[bootstrap.files]`, and the `bootstrap` task are not applied to images" (docs/dev-tools/mise-oci.md:267-271) but do not name apt.sources | Not landed | Include in Discussion A as a secondary ask (needs a quick `mise oci build` repro first, see UNVERIFIED) |
| G3 `mise.lock` does not lock `[bootstrap.packages]` | No thread. Nearest: #12298 (lockfile records resolved version per spec; closed, tools only), #15233 (npm provenance in lock, open). `src/lockfile.rs` and `src/cli/lock.rs` do not mention bootstrap | Not landed | Post Discussion B |
| G4 Renovate mise manager ignores `[bootstrap.*]` | No renovatebot/renovate discussion or issue found. Schema `lib/modules/manager/mise/schema.ts` parses only `tools`, `tasks`, `include`; readme has no mention of bootstrap/apt. Active mise-manager threads are about lockfiles/pypi: discussions 47692, 47762, 47279, 47260, 47947; PRs 47884, 46407, 44022, 45903 (all open) | Not landed | Post Discussion C to renovatebot/renovate |
| G5 apt.llvm.org keeps one build per package | Not a mise issue, no thread. Only mitigation is mise-side (see B) | Upstream property | Folded into Discussion B as motivation + a prefix-pin question |
| G6 `--from ?ref=` accepts branches; no way to require a full sha | No thread. Precedent exists: `paranoid` requires a full lowercase 40/64-hex sha or OCI digest for remote `include` (docs/paranoid.md:117-122; release note #14902). `--adopt` refuses non-branches, `--from` does not check; grep of src/cli/bootstrap.rs shows no paranoid gate | Not landed | Include in Discussion A |
| G7 no documented "build an image with mise bootstrap as root" recipe | No thread. `docs/bootstrap/*` has no Dockerfile example; `docs/mise-cookbook/docker.md` has a packslip-based mise installer Dockerfile (#13935) but no `bootstrap --from`. #14292 (docs: "Start from a repository", closed) unrelated to Docker | Not landed | Include in Discussion A (offer our tested recipe) |

Searches that found nothing relevant (negative evidence, keyword-limited): discussions/issues/PRs for "bootstrap docker", "bootstrap Dockerfile", "bootstrap devcontainer", "oci build apt sources", "bootstrap lock packages", "packages in mise.lock", "bootstrap --locked", "from ref commit sha", "bootstrap install --system", "non-root user bootstrap install". Open PRs mentioning bootstrap on 2026-11-13: only #15617 (release), #15672 (task sandbox), #13958 (identity install layout, experimental). Commits since 2026-11-10 (84 on main) are all brew/dotfiles/plugins/lock-of-other-backends fixes; nothing for G1-G7. Releases 2026.10.x-2026.11.7 notes grepped for oci/--system/apt/sha/lock: only #15526, #14902 (paranoid sha pin for remote includes), #15506 (unprefixed packages) are adjacent.

## 2. Posting plan

Three posts, not one: A (mise Ideas) bundles the four mechanical, code-local asks that share one scenario (G1, G2, G6, G7); B (mise Ideas) is the lockfile design (G3, G5), which needs a design decision and would otherwise bury A; C (Renovate "suggest an idea") is a different project. jdx closes threads when he ships a fix, so keeping the lockfile design out of A lets A close quickly. If the owner wants fewer, merge B into A and drop the G2 paragraph.

Before posting: fill `<...>`, re-run the G2 repro (section 5), and check that all commands still match mise at post time. Disclosure line is already appended; edit the version if you want it.

---

## 3. Draft A: mise Discussion, category Ideas

**Title:** `bootstrap: install tools system-wide, require a sha for --from, and a Dockerfile recipe`

I want one mise project that sets up a fresh Apple Silicon Mac and also builds Ubuntu 26.10 (latest) `linux/arm64` and `linux/amd64` toolchain images, for devcontainers and for GitHub Actions job containers. Everything pinned, updated by Renovate. The image build runs `mise bootstrap` as root inside `docker build`, and the devcontainer user is not root.

**What works today** (mise 2026.11.7, `ubuntu:26.10` pinned by digest, arm64 and QEMU amd64). Config:

```toml
[bootstrap.apt.sources.llvm]
uris = "https://apt.llvm.org/resolute/"
suites = "llvm-toolchain-resolute-23"
components = "main"
key = "https://apt.llvm.org/llvm-snapshot.gpg.key"
fingerprint = "6084 F3CF 814B 57C1 CF12 EFD5 15CF 4D18 AF4F 7421"

[bootstrap.packages]
"apt:gcc-16" = "16.2.0-3ubuntu1"
"apt:g++-16" = "16.2.0-3ubuntu1"
"apt:clang-23" = "1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94"
"apt:libc++-23-dev" = "1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94"
"apt:libc++abi-23-dev" = "1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94"
"apt:valgrind" = "1:3.27.1-0.2ubuntu2"
"brew:jq" = { os = "macos" }

[tools]
cmake = "4.5.0"
ninja = "latest"
```

GCC and valgrind come from the Ubuntu 26.10 archive. apt.llvm.org has no suite for 26.10 (`dists/llvm-toolchain-stonking-23/Release` is a 404), so the config uses the `resolute` (26.04) suite on a 26.10 base, which installed and ran fine.

Dockerfile steps, as root: `apt-get install -y curl ca-certificates git`, download the pinned mise binary and check its sha256, then
`mise bootstrap --from 'file:///src?ref=<full sha>' --yes`, then `mise install --locked` against a `mise.lock` made with `mise lock --platform linux-arm64,linux-x64,macos-arm64`. This works: the apt source is written, all six pinned packages install in one `apt-get install` call, a wrong key fingerprint and a wrong version pin both fail the build with exit 1, and the `os = "macos"` brew entry is skipped. Thank you, this is a very good fit.

**What is missing**

1. **Tools land in root's data dir.** Bootstrap's tools phase is a plain `mise install` (src/cli/bootstrap.rs:2733, `Install::new_bare`), so in a build they go to `/root/.local/share/mise`, and `/root` is mode 700, so the non-root devcontainer user cannot use them. What I do today is run `mise bootstrap --skip tools --yes` and then, as a second step, `mise install --system --locked && mise reshim --system` with the config in `/etc/mise` (on arm64 I also used an empty `MISE_DATA_DIR`, on amd64 plain; both worked), then put `/usr/local/share/mise/shims` on PATH. That works for the `dev` user: `cmake --version` gives 4.5.0, and `g++-16` and `clang++-23 -stdlib=libc++` compile and run a C++23 `<print>` program, and a CMake 4.5 `import std` project builds with both compilers via Ninja. Two traps: `mise lock` writes `mise.lock` with mode 600, and if it stays that way the `dev` user gets `mise WARN failed to read lockfile /etc/mise/mise.lock (possible corruption): ... Permission denied (os error 13)` on every shim call (`chmod 644` fixes it). And in an earlier run, when bootstrap had already installed to root's dir, `install --system` printed "already installed" and created an empty shims dir; I only found that by trial.
   Proposal: a way to make the bootstrap tools step use the system install location, for example `mise bootstrap --system`, or a config key such as `[bootstrap] install = "system"`. It would also run the equivalent of `reshim --system` and forward the choice to the `--from` child process. The same applies to `--upgrade`.
2. **No way to require an exact commit for `--from`.** `?ref=` accepts a branch, tag or commit, and a branch floats. For reproducible images I need the build to fail unless the ref is a full commit sha. Paranoid mode already does this for remote `include` (docs/paranoid.md, "Remote includes"). Proposal: apply the same rule to `bootstrap --from` and `--adopt ?ref=`/`[bootstrap.repos]` under paranoid mode, or add a flag such as `--require-sha`.
3. **`mise oci build` skips `[bootstrap.apt.sources]`.** With the LLVM source above, a one-package `[bootstrap.packages] "apt:clang-23" = "<exact version>"`, `[tools] ninja = "1.13.2"` (installed first with `mise install`) and `[oci] from = "ubuntu:26.10"`, `MISE_EXPERIMENTAL=1 mise oci build` (run inside an arm64 `ubuntu:26.10` container) fails with `mise ERROR apt-get failed while installing OCI system packages: exit status: 100` and `E: Unable to locate package clang-23`, as if the LLVM source was never added to the image rootfs. The docs say `[bootstrap.files]` and the bootstrap task are not applied to images, but do not mention apt sources. So a project that needs a third-party apt repository can use `bootstrap` in `docker build` but not `oci build`. Proposal: apply `[bootstrap.apt.sources]` (and the pre-packages `[bootstrap.files]` that apt needs) in the OCI package layer, or fail with a clear error when they are configured.
4. **Docs.** There is no recipe for "build a container image with `mise bootstrap` as root". I would be glad to write one: install git/ca-certificates/curl first, pinned mise binary with checksum, `bootstrap --from <repo>?ref=<sha> --yes`, `MISE_LOCKED=1`, what to do about the data dir and the non-root user, and the apt cache mounts. A short page under docs/bootstrap or the Docker cookbook would do.

Questions: is a system-install option for bootstrap acceptable in principle, and is `[bootstrap] install = "system"` or a flag the better shape?

*AI-assisted — Tool: Claude Code; models: Anthropic/claude-sonnet-5-5 (first draft, re-test and edits), Anthropic/claude-opus-5-5 (edits); version: unavailable.*

---

## 3b. Draft B: mise Discussion, category Ideas

**Title:** `mise.lock for [bootstrap.packages]: record resolved apt/brew versions per platform`

Same setup as my other post: one mise project, Ubuntu 26.10 (latest) `arm64` and `amd64` images plus a Mac, all pinned.

`mise.lock` pins `[tools]` with URLs and checksums per platform. `[bootstrap.packages]` is outside it. I ran `mise lock --platform linux-arm64,linux-x64,macos-arm64` (mise 2026.11.7) on a config with six `apt:` entries, a `brew:` entry and two tools (cmake, ninja). The lockfile (49 lines) holds only the two tools. So an `apt:` entry without an exact version can resolve to different versions on different days, and on `arm64` versus `amd64`, with nothing in the repository recording which was used. Exact pins in `mise.toml` give a loud failure instead, but then they rot: apt.llvm.org keeps only the current build per package (version strings like `1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94`), so a pinned version disappears within days and the build fails with `E: Version '1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.95' for 'clang-23' was not found` (I changed the last digit to simulate it). It is worse on the newest Ubuntu: apt.llvm.org has no suite for 26.10, so I use the `llvm-toolchain-resolute-23` suite of 26.04, and I cannot tell which suite or Ubuntu release a pin was resolved against from `mise.toml` alone. Ubuntu `-updates`/`-security` drop old versions too, more slowly.

Proposal (any of these would help):
1. `mise lock` (or `mise bootstrap lock`) records, per manager and per architecture, the resolved version of each `[bootstrap.packages]` entry, and ideally the package checksum when the manager exposes it (apt: the `SHA256` field of the Packages index entry). `mise --locked bootstrap` installs exactly that version and fails if it is not available, like `install --locked` does for tools.
2. Allow a version prefix as a pin, for example `"apt:clang-23" = "1:23.1.*"` (apt accepts a glob after `=`), with the exact resolved build recorded in the lockfile. That keeps `mise.toml` readable and lets the lock be refreshed by a bot.
3. Per-architecture pins for the same package, if the lock cannot cover it.

Questions: is a package section in `mise.lock` in scope, given that bootstrap packages are installed by the OS package manager? Is a prefix pin acceptable in `mise.toml`?

*AI-assisted — Tool: Claude Code; models: Anthropic/claude-sonnet-5-5 (first draft, re-test and edits), Anthropic/claude-opus-5-5 (edits); version: unavailable.*

---

## 3c. Draft C: renovatebot/renovate Discussion, "Suggest an idea"

**Title:** `mise manager: extract [bootstrap.packages] apt pins and [bootstrap.apt.sources]`

mise 2026.9+ has `mise bootstrap`, which installs OS packages declared in `mise.toml`. I run it on Ubuntu 26.10 (latest):

```toml
[bootstrap.apt.sources.llvm]
uris = "https://apt.llvm.org/resolute/"
suites = "llvm-toolchain-resolute-23"
components = "main"
key = "https://apt.llvm.org/llvm-snapshot.gpg.key"
fingerprint = "6084 F3CF 814B 57C1 CF12 EFD5 15CF 4D18 AF4F 7421"

[bootstrap.packages]
"apt:g++-16" = "16.2.0-3ubuntu1"
"apt:valgrind" = "1:3.27.1-0.2ubuntu2"
"apt:clang-23" = "1:23.1.6~++20261108033809+c47d7823685a-1~exp1~20261108153913.94"
```

An exact value after `apt:<name>` is installed as `apt-get install <name>=<version>`, so it works as a version pin (docs: https://mise.jdx.dev/bootstrap/packages/apt.html). Renovate's `mise` manager reads `mise.toml` but its schema (`lib/modules/manager/mise/schema.ts`) only parses `tools`, `tasks` and `include`, and the readme does not mention `bootstrap`, so these pins are never updated. For Ubuntu and LLVM the pins go stale within days to weeks, so an unattended pin breaks the image build. Note the two sources above are different suites: `g++-16` and `valgrind` come from the Ubuntu 26.10 archive (`stonking`), `clang-23` from apt.llvm.org's `resolute` suite, because apt.llvm.org has no suite for 26.10. So the suite for a package cannot be derived from the base image either.

What I used in an earlier setup: a `customManagers` regex manager with the `deb` datasource, `registryUrlTemplate` per suite, and a `packageRules` entry that adds the `-updates` and `-security` pockets. It works but needs per-repository regex work, cannot see which suite a pin belongs to, and the `deb` datasource URL carries a single `binaryArch`.

Idea: in the `mise` manager, extract each `[bootstrap.packages]` key of the form `apt:<name>` with a string value (or `{ version = ... }` if that form exists) as a dependency with `depName = <name>`, `datasource = deb`, a `depType` such as `bootstrap`, and the pin as `currentValue`. The registry URL cannot be known from `mise.toml` alone, so leave it to `registryUrls`/`packageRules`, or derive one from `[bootstrap.apt.sources.*]` `uris`/`suites`/`components` when present. The same section also accepts `brew:` and unprefixed keys; those could follow later. This is about the same as what the `dockerfile` manager does for `apt-get install pkg=version`.

Questions: would a PR for this be welcome in the `mise` manager, or do you prefer a regex-manager preset? Is `deb` the right datasource for versions with epochs and `~` suffixes (`1:23.1.6~++2026...`)? Does the datasource's single `binaryArch` matter for multi-arch images?

*AI-assisted — Tool: Claude Code; models: Anthropic/claude-sonnet-5-5 (first draft, re-test and edits), Anthropic/claude-opus-5-5 (edits); version: unavailable.*

(Checked 2026-11-13: Renovate's CONTRIBUTING.md, docs/development/contributing.md and the suggest-an-idea template have no AI-use rule; the disclosure line is kept anyway.)

---

## 4. Fork / PR assessment for G1

- **A PR to jdx/mise is not possible.** CONTRIBUTING.md: "mise is not accepting pull requests from external contributors, and GitHub does not let them be created." The only route is Discussion A and waiting for jdx to implement it; precedent says he usually does, often within a day.
- **A private fork is technically small but not worth keeping.** Where the code is (main `a290bd0`; line numbers shift daily, v2026.11.7 had them ~70 lines earlier):
  - `src/cli/bootstrap.rs:110` `pub(crate) struct Bootstrap`: add a `--system` flag (usage derive, like other flags near l.38-250 in v2026.11.7).
  - `src/cli/bootstrap.rs:2733` tools phase: `Install::new_bare(self.dry_run, self.yes).run()`. Replace with an `Install` whose `system` is set; `src/cli/install.rs:150` `new_bare` uses `..Default::default()`, and the `system: bool` field (install.rs:132-139, `conflicts = "shared"`) is private to the module, so a `new_bare_system` constructor or visibility change is needed. `install_opts` (install.rs:493-501) already maps it to `Settings::system_installs_dir()`.
  - `src/cli/bootstrap.rs:2736` `Upgrade::new_bare` has the same issue for `--upgrade`.
  - After the install: the equivalent of `mise reshim --system` (`src/cli/reshim.rs` has `pub system: bool`, l.40).
  - `src/cli/bootstrap.rs:3025` `run_child_bootstrap` and `:3251` `bootstrap_from_child_args`: forward the flag to the `--from` child.
  - Docs and the usage spec (`mise.usage.kdl`, generated docs) in the same change.
  - Estimate: roughly 30-80 lines of Rust plus a docs edit and an e2e test; the hard part is the "already installed in the user dir" behaviour (the `--system` install must not count root's user-dir installs, see handson error 4), which may need a change in install-state lookup, not just a flag.
- **Why not fork:** mise releases about daily, bootstrap.rs is 7372 lines and moves every day (84 commits on main since 11-10), the binary would have to be built per arch (arm64 and amd64) and released by us, and the image pins a mise version with a checksum from the official release. Cost of rebasing is high for a small win.
- **Cheaper workaround that needs no mise change** (already proven): in the Dockerfile, run bootstrap with `--skip tools` (the parts enum, l.261-283 in v2026.11.7) and then `mise install --system --locked && mise reshim --system`. UNVERIFIED that `--skip tools` still exists under that name on 2026.11.7 and that the flow works end to end; test it before relying on it. Alternatively set `MISE_DATA_DIR=/usr/local/share/mise` (or `/opt/mise`) via `ENV` for both build and runtime; conda launchers bake the absolute path, so build and runtime paths must match (bootstrap-source.md section 4).
- **Recommendation:** post Discussion A; use the `--skip tools` + `install --system` workaround meanwhile; do not fork.

## 5. UNVERIFIED

- G2: we have not run `mise oci build` with `[bootstrap.apt.sources]` ourselves; the claim rests on docs (mise-oci.md:267-271 names `[bootstrap.files]` and the bootstrap task, not apt.sources) and on `crates/mise-oci/src/packages.rs` having no source handling (grep for `sources` found nothing). Run a 3-line repro (apt entry that needs the LLVM source, `mise oci build` on a Linux host as root) and note the exact output before posting; if it errors clearly, soften item 3 of draft A.
- G3: observed on 2026.11.7 (lock generated in container, 465 lines, tools only); a deliberate re-check with only bootstrap packages and no tools was not done.
- G1 `bootstrap --skip tools` workaround and whether bootstrap honours `MISE_DATA_DIR` as an absolute shared path end to end: not run.
- Whether `apt-get install pkg=1:23.1.*` works through mise's pin path (mise passes `name=version`, so likely yes) and whether mise's `install_would_fail` simulation accepts a glob: not run.
- Whether `[bootstrap.packages]` accepts `{ version = ... }` for apt (draft C wording hedges).
- Renovate: no existing discussion found, but GitHub search is keyword-limited; the deb datasource's arm64 behaviour is untested; Renovate AI-disclosure expectations not checked.
- Paranoid mode does not appear to gate `bootstrap --from` (grep of src/cli/bootstrap.rs for "paranoid" found nothing); not tested at runtime.
- jdx's response times are inferred from 4-5 threads, not a guarantee.
- Discussion bodies/comments were read through the first 12 comments only; 14945, 14161, 14425 not re-read this round.
- Whether gh search misses PRs by title wording; REST search was rate limited mid-run (403), GraphQL search used instead.

## 6. Tools used and failed

Used: `gh api` REST (releases, commits since 2026-11-10, contents of CONTRIBUTING.md, discussion templates, renovate manager files) and GraphQL (discussion/issue/PR search and thread reads in jdx/mise and renovatebot/renovate); `gh search issues` (a few calls); `gh pr view`; a shallow clone of jdx/mise main at `a290bd0` into a local scratch directory for grep/sed of src and docs; the notes `bootstrap-handson.md`, `bootstrap-source.md` and `bootstrap-upstream.md`.
Failed or limited: `gh search issues` hit the REST search rate limit (HTTP 403) twice and returned empty arrays for several multi-word queries, so GraphQL `search(type: DISCUSSION/ISSUE)` replaced it; no Exa, Firecrawl, Context7 or last30days used (everything needed was first-party GitHub).
