Status: resolved (re-audit)

# Stage 8: Intermediate Zoom Out

* **Target:** `docs/designs/environment-standard.md`, the full file (1,305 lines, after the Stage 7 fixes)
* **Date:** 2026-11-13
* **Reviewer:** `egm-zoom-out`, in a fresh context, using `zoom-out-standard.md`. Context: `zoom_out_report.md`, the re-audit report, `critic_report.md`, `decisions-log.md`, `concepts_brief.md`, and a search of `research/`.
* **Verdict:** changes requested. 1 Blocker, 7 Major, 6 Nit.

## Summary

Two Stage 7 additions bring back problems that Stage 5 had closed: the bot write-back (R2/A5) and owner review of leaf bumps (A2). Most of the other added weight serves the self-hosted runners or D54, but it sits in M0 and M1a, which threatens 2026-11-27.

## 🔴 Blocker

**B1. Installing toolchains through packslip contradicts the inputs-hash model.**
- Where: lines 443, 465-481, 762-764, 1162-1164, 1221-1222, 1237; D49, D56, D59.
- Problem 1: the packslip versions `"<ver>+<hash>.<N>"` have to be literal values in the owned `mise.toml`/`mise.lock`. The `.N` and the signer exist only after `main` publishes, so every p2996 bump needs a follow-up write-back PR that the owner reviews. That brings back R2/A5 and breaks D56.
- Problem 2: `main` keeps running the old compiler until that follow-up PR merges.
- Problem 3: one entry can't cover several OSes and architectures.
- Problem 4: PR jobs have no defined way to install their `pr-` build.
- Fix: one trust mechanism. Toolchains go on GHCR under the computed tag, with `attest-build-provenance`, and one `toolchain:fetch` runs the same `gh attestation verify` as `image:verify`. `mise.toml` never names a toolchain version. This removes packslip, the PR prereleases, immutable releases, the tag ruleset, `.N`, `toolchain:audit` and the GHCR mirror.

## 🟡 Major

| # | Finding | Lines | Fix |
|---|---|---|---|
| M1 | Folding `[tools]` into the owned `mise.toml` (D68) reopens Stage 5 A2: the daily tools PR would need the owner. | 494-506, 1162, 1218-1219 | Put `.mise/conf.d/tools.toml` back as a (P) file, and keep D68's platform-sliced lock hash. |
| M2 | `toolchain-env.lock.json` duplicates the exact `apt.toml` pins (it adds only libc6). Producing it needs a write-back (Renovate builds an image, or the builder pushes to the PR). Mend-hosted Renovate probably doesn't run `postUpgradeTasks` (*verify*). | 417-434, 525, 737-755, 1166-1173, 1233-1244 | Split the apt pins into `apt-toolchain-host.toml` (g++-16, binutils, make, pinned `libc6-dev`) and `apt.toml`. The toolchain hash covers the first file. Drop the env lock, its task, its check and the hook. |
| M3 | The owned list in §6 (only `ci*` and `gate/*`) disagrees with the (O) marks in the file plan. Read narrowly, agents could automerge `artifact/publish`, which signs as `main`, and `pins:validate`. | 710-724 vs 1168-1258 | One rule: `.mise/tasks/**` is owned, except a named list that agents may edit. |
| M4 | M0 and M1a carry M2/M3 trust machinery: hook and gha-outrunner tests, release protections, retention, audit. The cut order omits these items and M1b. | 813-856, 1139, 1170-1204 | The M0 (i) runner tests become the M2 entry gate. M1a trust work is limited to main-only publishing, the `pr-` namespace and attest + verify. Retention, audit and protections move to M1b. Add the M1b items to the cut order. |
| M5 | `mac-probe.yml` is a fence exception that protects an owned file the owner already reviews. The dev VM's `caps:update` and the post-merge run already cover it. | 395-401, 671-685, 1270; D55, D63 | Drop it and its hook entry. Keep the D63 ruleset settings. |
| M6 | Retention brings back R17 (D53 dropped GHCR cleanup). It breaks G1 and D27 (old commits are reproducible by pulling), and it conflicts with the tag ruleset. | 152-154, 487-490, 1104, 1202 | Retention covers local Tart images and `pr-` artifacts only. Never delete anything `main`'s history references. |
| M7 | The token broker is in M1b, but agents push as the App in M1a. How a token reaches the VM, and how it's refreshed, is not described. | 110, 184-185, 703-704, 1124-1133, 1248 | Move `agent:token` to M1a: a host launchd job writes a token every 50 minutes into a read-only shared folder, and a git/gh credential helper in the VM reads it. |

## 🟢 Nits

- **N1.** Split "amd64 (hosted)" from "the PC runner" in the cut order, and cut the PC runner earlier. Nearly all of the self-hosted stack exists for the PC.
- **N2.** For Level 1, `hk.pkl` becomes a two-line call to `mise run ci:fast` and `gate:policy`. Defer the jouet gate-guard. Correct D64's wording ("the real gate" is `gate:policy`).
- **N3.** In M2, check whether gha-outrunner or actions/scaleset accepts App credentials. The existing PC runner App is narrower than a PAT with Administration write.
- **N4.** `toolchain:fetch` is used but not defined (A16 again).
- **N5.** `toolchain:audit` duplicates the post-merge and daily runs.
- **N6.** There is a GHCR mirror of the packslip releases, and PR artifacts exist in two stores. Use one store.

## Status of earlier findings

- **Still closed:** A1, A4, A6 (the job-start hook: keep it), A8-A14, A18, A20, A22, R1, R3-R5, R8, R9.
- **Reopened:**
  - A2 (M1, B1);
  - A5/R2 (M2, B1);
  - R17 (M6);
  - A16 (N4);
  - A7 partly (M4).

## Mechanisms that duplicate each other

| Mechanism | Duplicates | Finding |
|---|---|---|
| packslip, plus the GHCR mirror | GitHub attestations | B1, N6 |
| `toolchain-env.lock.json` | the exact `apt.toml` pins | M2 |
| jouet gate-guard, `hk.pkl` | `gate:policy`, `ci:fast` | N2 |
| `toolchain:audit` | the post-merge and daily runs | N5 |
| `mac-probe.yml` | the dev VM's `caps:update`, plus the post-merge macOS run | M5 |

## Author (Elephant) notes for the owner

* **This stage partly reverses choices you made in Stage 7: B1 (packslip), M1 (fold tools.toml), M2 (env lock) and M5 (mac-probe).** The reviewer gives a concrete mechanism for each, and I checked them:
  - **B1:** a packslip version is a literal string that has to be written after publishing. That's the bot write-back D49 removed.
  - **M1:** folding the tools back in does make the daily tools PR touch an owned root.
  - **M2:** the env lock does need someone to write it from an image that doesn't exist yet when the PR is opened.
  - **M5:** mac-probe is weaker. It's a judgment call.
* I recommend fixing B1, M1-M4, M6 and M7 before Stage 9, and asking you about each reversal one at a time.

## Owner decisions (2026-11-13)

Every finding was accepted. B1 was resolved differently from the proposed fix. The design records the decisions as D72-D82.

| Finding | Decision | Log |
|---|---|---|
| B1 | Keep packslip, but as the standalone CLI through `toolchain:fetch`, with the exact `--identity` for `builder.yml` at `refs/heads/main`. `mise.toml` and `mise.lock` never name a toolchain version. PR jobs share builds through `actions/cache` and publish no toolchain release. Images keep GHCR attestations and `image:verify`. `.N`, `toolchain:audit` and the GHCR mirror are dropped; recovery is a `salt` bump. The base image installs mise with `packslip install github.com/jdx/mise --pin`. M0 (i) becomes the packslip leg. | D72, D73 |
| M1 | `[tools]` goes back to `.mise/conf.d/tools.toml` (P). | D74 |
| M2 | `toolchain-env.lock.json`, `toolchain:env`, `toolchain-env:check` and `postUpgradeTasks` are dropped. `apt-toolchain-host.toml` (P) is split out and hashed; `mise bootstrap status --json` only verifies. | D75 |
| M3 | `.mise/tasks/**` is owned, except `linux/run`, `doctor`, `fmt`, `perf/*` and `review/cap`. | D76 |
| M4, N1 | The runner tests become the M2 entry gate. M1a trust work is limited to `main`-only publishing, attest + verify, packslip signing with `toolchain:fetch`, and the `pr-` namespace. Release protections, retention, the gate-guard and Renovate polish move to M1b and into the cut order. The PC runner is split from amd64 and cut before Mac GCC. | D77 |
| M5 | `mac-probe.yml` is dropped; the D63 ruleset settings stay. | D78 |
| M6 | Retention covers only local Tart images and `pr-` artifacts and caches. | D79 |
| M7 | `agent:token` moves to M1a: a launchd job writes a token into a read-only Tart shared directory, and a credential helper reads it. | D80 |
| N2 | `hk.pkl` is a thin call to `ci:fast` and `gate:policy`; D64's wording is corrected. | D81 |
| N3 | The M2 entry gate checks App credentials for gha-outrunner and actions/scaleset. | D82 |
| N4-N6 | Resolved by B1: `toolchain:fetch` is defined, `toolchain:audit` and the mirror are gone, and PR builds live only in `actions/cache`. | D72 |

---

# Stage 8 re-audit (cap reached)

* **Date:** 2026-11-13
* **Reviewer:** `egm-zoom-out`, in a fresh context. It checked claims against the local mise and packslip clones.
* **Verdict:** changes requested. 0 Blocker, 5 Major, 5 Nit.
* **Earlier findings:**
  - Resolved: B1, M1, M2, M3, M5, M6, M7 (over-scoped), N1-N6.
  - Partly resolved: M4.

| # | Finding | Fix |
|---|---|---|
| MJ1 | Sections contradict each other on how a PR gets its toolchains: "`main`'s release if the hash matches" vs "cache only" (lines 284, 476, 559, 1279). | One rule everywhere: (1) `main`'s release for that hash, else (2) the cache, else (3) rebuild. |
| MJ2 | A cache is scoped to its ref plus the default branch, so merge-group runs can't read a PR's cache. Each toolchain-input bump is built three times. | The merge group downloads the PR builder run's artifact by inputs hash, or accept the cost as a recorded limit. M0 confirms the scoping. |
| MJ3 | Mac spikes (a), (d), (e) and the Tart-directory broker still gate M1a. | Split M0: the Linux spikes block M1a and are time-boxed; the Mac spikes feed M3. M1a ships only the host credential helper. |
| MJ4 | The Mac-only p2996 bumps mean an owner review every day. `macos.inputs.toml` isn't an owned root. Cut item 2 leaves these bumps without a home. | Weekly Mac group. Either add it to CODEOWNERS until Q4 or call the rule advisory. Say what happens under the cut. |
| MJ5 | The mise version is "pinned" in three places, and `min_version` is a minimum, not a pin (`docs/configuration.md:590`). | The exact version and the packslip digest live only in `image/base.inputs.toml`, which the Mac golden image also hashes. `min_version` is a rarely changed floor. Fix `pins:validate` and the Renovate managers. |
| N1 | D76 lists `fmt`. | Remove it. |
| N2 | The digest has no milestone in the cut order. §7 and M1b disagree on `apt-toolchain-host.toml` in the Renovate managers. | Move the digest to M1b, or point those rows at failed runs. Align §7 and M1b. |
| N3 | packslip with immutable releases needs the order draft → upload → publish. The action attests every file by default (`attest: true`). | State the order. Set `attest: false`, or update the alternative. |
| N4 | The tag algorithm can't hash a slice of `mise.lock`. "Such as cmake, ninja" is vague. | A slice input = sha256 of the canonical slice, keyed `path#platform`. Use an exact list of tools. |
| N5 | The GCC recipe is placed in M1a "for M0". The M0 (i) test release needs a minimal `builder.yml` on `main`, and it must be deleted before the tag ruleset is on. | Move the recipe to the M0 branch, and state both conditions. |

**Re-audit cap reached:** the fixes are applied by the author with the owner's decisions, and Stage 9 follows. There is no further Stage 8 run.

## Owner decisions (re-audit, 2026-11-13)

The owner decided MJ2 and MJ4; the rest were applied as proposed. The design records them as D83-D87.

| Finding | Decision | Log |
|---|---|---|
| MJ1, MJ2 | One fetch rule everywhere: `main`'s signed release for the hash, then the PR builder run's artifact (merge groups, `actions: read`), then `actions/cache` (PRs), then rebuild. A miss never fails a job. M0 (i) confirms cache scoping. | D83 |
| MJ3, N2 | M0 split: M0-Linux (b, c, f, g, h, i) blocks M1a, exit review 2026-11-16; M0-Mac (a, d, e) feeds M3. M1a ships only the host credential-helper `agent:token`; the Tart broker is M3. The digest moves to M1b, cut position 3; every cut has a trigger date. | D84 |
| MJ4, N4 | One shared `toolchains/<name>/pins.toml` per toolchain with an exact `host_tools` list; no per-OS inputs files and no Mac-only PR. A lock slice input is the sha256 of its canonical JSON. macOS builds post-merge; a red run is the backstop. | D85 |
| MJ5 | The exact mise version and packslip digest live only in `image/base.inputs.toml`, also hashed by the Mac golden image; `min_version` is a floor. `pins:validate` and Renovate follow. | D86 |
| N1 | `fmt` removed from D76. | D76 |
| N3, N5 | Draft → upload → publish; `attest: false`. The M0 (i) test needs a minimal `builder.yml` on `main`, and its release is deleted before the tag ruleset is on. The GCC recipe lives on the M0 spike branch. | D87 |
