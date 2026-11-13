# Stage 9: Implementation Readiness

Status: resolved

* **Target:** `docs/designs/environment-standard.md`, DetailedRange lines 1256-1465 (lines 1-1255 read as context)
* **Date:** 2026-11-13
* **Reviewers:** three, each in a fresh context, using `implementation-readiness-standard.md`:
  - `egm-implementation-readiness` (IR);
  - `egm-codebase-details` (CD), which checked the plan against the local mise, packslip, actions/runner and gha-outrunner clones and the prior art in dotfiles-legacy and cpp-utilities;
  - `egm-style` (ST).
* **Verdict:** not ready. IR found 4 Blockers, 13 Majors and 3 Nits; CD found 4 Blockers, 14 Majors and 8 Nits; ST found 13 Majors and 15 Nits. After merging duplicates, 8 Blockers remain.
* The author verified each finding listed below as **V** against a primary source.

## 🔴 Blockers

| # | Finding | From | Evidence | Fix |
|---|---|---|---|---|
| X1 | **On the Free plan, attestations, rulesets and the merge queue work only on public repos.** cpp-standard is private, in the `ray-manaloto` org (Free). | IR M1, extended by the author | **V** GitHub security-features doc ("Free … public repositories"), the `actions/attest` README, the plans page ("Repository rules — Free: Public repositories"), the merge-queue gated-features doc ("public repository owned by an organization"), and `gh api /orgs/ray-manaloto` (plan=free). | Owner decision: make the repo public before M0-Linux (Q1 scrub and Q3 licence become setup exit criteria), or upgrade the plan, or use a fallback. |
| X2 | **The lock for `conf.d` tools is `.mise/mise.lock`, not `mise.lock`.** | CD B1 | **V** `mise/src/lockfile.rs:2676-2683`; `docs/dev-tools/mise-lock.md:95`. | Use `.mise/mise.lock` everywhere, or load the fragment through `include =` from `mise.toml`. |
| X3 | **A p2996 commit can't be a packslip version.** Two releases can't share a version that differs only in build metadata. | CD B2, M3; IR M3 | **V** `packslip/content/spec.md:1897-1899` ("distinguish them with an ordered component, not build metadata"); signed versions must be semver (`spec.md:1834`). | Use one packslip project per `<toolchain>-<os>-<arch>`. The version is semver with an ordered component, e.g. `23.0.0-p2996.<yyyymmdd>.<n>`. The inputs hash goes in a release field or the tag, and `toolchain:fetch` resolves hash → version. |
| X4 | **A mise task can't call Actions** (`actions/cache`, `download-artifact`, `jdx/packslip@v1`). | IR B2, CD B3 | `packslip/action.yml:208-219` (composite). | Split the work: workflow steps restore or download into a staging directory; the task reads release → staged file → rebuild. Outside Actions, only the release or a rebuild applies. Define the artifact names and the lookup. |
| X5 | **PR jobs must push `pr-` images and post commit statuses, but §6 makes PR jobs read-only.** | IR B1 | Design §2 vs §6. | Add a per-job permissions table: the PR and merge-group publish job gets `packages: write` (pr- namespace) and `statuses: write`, as an accepted risk under D54/D60. |
| X6 | **M0 (i) can't run in the given order:** it needs a builder and a merge queue on `main` before the ruleset and required checks exist. | IR B3 | Design setup steps. | Spell out the bootstrap sequence: root commit → minimal `builder.yml` and stub `ci.yml` → M0 (i) → delete the test release → design PR → ruleset without required checks → M1a `ci.yml` → required checks. |
| X7 | **llvm-cov has no source exclusion markers,** so the 100% rule on clang and p2996 is undefined. | IR B4 | (Reviewer's knowledge; to be verified in M0.) | Decide the coverage tool chain per compiler (for example lcov 2.x on top of `llvm-cov export -format=lcov`, with `LCOV_EXCL_*`). Add an M0-Linux check (j). |
| X8 | **Image and golden hashes miss inputs that are copied in or that shape the image:** the `[bootstrap.apt.sources]` in `mise.toml`, the runner hook, `vm:golden`, and the PyPI lock sidecars. | CD B4, M5 | Prior art: `dotfiles-legacy/.../p2996_hash.py:338-397` (PR #140, #154). | Hash the exact COPY set of each Dockerfile. Move the apt source into a pins fragment. Add the hook, `vm:golden`, the runner version and `.mise/locks/**` to the relevant hashes. Add `schema=1`. |

## 🟡 Major (merged)

- **Apt and bootstrap syntax (CD M1, M2).**
  - The apt.llvm.org source needs `uris = "https://apt.llvm.org/resolute/"`, `suites = "llvm-toolchain-resolute-23"` and the fingerprint from the research.
  - `[bootstrap.packages]` entries need the table form `{ version, os }`.
  - binutils and make are unverified: verify them in M0.
- **Install packslip where it's used (CD M4, IR M3).**
  - Add packslip and `gh` to `tools.toml`.
  - COPY `/packslip` into the base image.
  - Add the mise signer pin (`ps1_…`) to `base.inputs.toml`.
- **vcpkg (CD M6):** it has no mise registry entry. Name its backend and its baseline mechanism.
- **Platform keys (CD M7):** use `linux-x64`, `linux-arm64` and `macos-arm64`, map `amd64` to `x64`, and give the `mise lock --platform` command.
- **Devcontainer and image tags (CD M8, IR M2, ST M2).**
  - There is no `image:tag` task.
  - `initializeCommand` can't set `image`; use `dockerComposeFile` plus a generated `.env`.
  - A resolve job verifies the image and outputs a digest, and the container jobs use it.
  - Define the GHCR package names and the merge-group tag rule.
- **Task layout (CD M9, ST M8):** use `ci/_default` and `ci/fast`, and state that file tasks are the only kind.
- **gha-outrunner (CD M10, M11, M12, IR M11).**
  - It takes a PAT only (`main.go:115`).
  - PC: `LoadCredentialEncrypted`. Mac: a LaunchAgent wrapper that reads the token from the Keychain.
  - The root guest-exec runner needs a wrapper.
  - Bake `/actions-runner/.env` with the hook.
  - Add egress filtering, stable image aliases, and `max_runners: 1` on the Mac.
  - Add a positive hook test and an M3 Tart gate.
- **Base digest and probe (CD M13):** use `FROM base@sha256`, and reuse the dotfiles-legacy probe and disk-freeing steps.
- **cpp-utilities reuse (CD M14):**
  - `ProfileCheck` needs `ProfileCommon` and `ProfileOverrides`.
  - Reuse `_profile_undone_in` in `gate:policy`.
- **Required check names (IR M4):** list the `ci.yml` job IDs, all running on `merge_group`, and match them in `main.json`.
- **agent:token (IR M5):** specify the key store, the JWT signer, the installation ID and the `gh` wrapper. Add a test and a fallback.
- **gate-policy schema (IR M6):** give the TOML schema, how presets are resolved, the line-hash definition, and the fixtures.
- **jouet gate-guard (IR M7):** match `cmake/presets/*.json`, give the marker regexes, and add a test.
- **artifact:tag spec and test (IR M8):** define the JSON slice, the arch mapping and the CLI, and add golden-vector tests.
- **Exit criteria (IR M9):** add an exit line for each setup step and M0 check, thresholds for (h), fallbacks for (f) and (g), and done-conditions for M1a and M1b.
- **M1a PR order (IR M10):** list the PR sequence, with an exit check for each.
- **Retention API (IR M12):** name the APIs and permissions, the closed/reopened rules, `retention-days`, and a test.
- **Daily settings-check token (IR M13):** `GITHUB_TOKEN` lacks Administration. Confirm which endpoints it can read, or choose another credential.
- **Writing (ST M1-M13):**
  - define the owner's setup agent;
  - spell out the full `--identity` URL;
  - fix the research path;
  - move the gcc-macos rows to M3;
  - name the project for bug #28242;
  - list every triplet;
  - add a file for the App-PR test;
  - make the "newest" pins exact;
  - add the missing (O) marks;
  - define the two-VM rule;
  - give a permission level for each App permission.

## 🟢 Nits (merged)

- `COPY --chmod=644` for the lock.
- Pin `jdx/packslip` by SHA.
- `--install-dir` must be absolute; record the toolchain sizes against the 10 GiB and 100k-entry limits.
- `gh attestation verify --repo`.
- Use `bootstrap packages status --missing`.
- State the LLVM 23.1.5 (mac) vs 23.1.6 (apt) difference.
- `download-artifact` needs `github-token`.
- Make the pins fields consistent.
- Explain the ci.yml rebuild window.
- Plus style nits ST N1-N15: wording, capitalization, abbreviations (CUJ, CLT, SOH, GHCR, P3394), and `(O)` marks.

## Coverage of the new mechanisms (IR)

| Mechanism | Test | Fallback |
|---|---|---|
| Job-start hook | Partial: refusal tests only | Missing |
| packslip `toolchain:fetch` | M0 (i) | Partial |
| Cache and merge-group artifact | M0 (i) | Rebuild; the mechanism is undefined (X4) |
| Image attestations and `image:verify` | Missing | Missing (X1) |
| Shared pins and lock slices | Missing | n/a |
| gha-outrunner libvirt | M2 gate | incuse or runscaler |
| gha-outrunner Tart | Missing | Partial |
| jouet gate-guard | Missing | Cut item 1 |
| `gate:policy` | Fixtures | Schema missing |
| `agent:token` | Missing | Missing |
| Retention | Missing | Cut item 4 |

## Resolution classification (egm-resolve)

| Finding | Class | Note |
|---|---|---|
| X1 public repo | ESCALATE | Owner decision: visibility or plan. |
| X2 lock path | PROPOSE FIX | Use `.mise/mise.lock` everywhere; one defensible answer. |
| X3 packslip version | PROPOSE FIX | One project per toolchain/OS/arch; ordered prerelease version; hash in the release. |
| X4 Actions vs task | PROPOSE FIX | Workflow steps stage files; the task only reads them. |
| X5 PR permissions | PROPOSE FIX | Per-job permissions table. |
| X6 bootstrap order | PROPOSE FIX | Ordered setup sequence. |
| X7 coverage markers | ESCALATE | Owner decision on the coverage tool chain, after verification. |
| X8 hash inputs | PROPOSE FIX | Hash the COPY set; reuse the dotfiles-legacy approach. |
| Daily settings-check token (IR M13) | ESCALATE | Owner decision on the credential. |
| All other Majors | PROPOSE FIX | Specification gaps. |
| Nits | PROPOSE FIX | Cheap; applied with the Majors. |

## Author (Elephant) notes for the owner

* **X1 is the most important finding.** Until cpp-standard is public, the merge queue, the rulesets and the image trust check can't exist on the Free plan. This also moves Q1 (the scrub) and Q3 (the licence) onto the critical path.
* **X2 and X3 are factual errors in my design,** confirmed in the mise and packslip source.
* **The rest are gaps in the specification,** not changes to the design. They make the plan buildable without the implementer having to decide anything.

## Owner decisions and outcome (2026-11-13)

* **X1:** go public before M0-Linux, after the Q1 scrub and the Q3 licence; fork-PR approval for all outside contributors right after the switch (D95).
* **X7:** each compiler's own coverage tool, in gcov mode, with no exclusion markers (D88). The owner asked for research first; the author tested clang 23.1.5 and GCC 16 and found that gcov mode never counts compile-time-only code, while clang's source-based mode counts `constexpr` helpers used only in `static_assert` as uncovered. p2996 (LLVM 21) lacks LLVM PR #190870. M0 (j) proves the rule on p2996, with a fallback.
* **Daily ruleset check (IR M13):** the owner's existing Doppler PAT in a `main`-only `audit` environment, with no new App (D92).
* **Applied as proposed:** X2 (`.mise/mise.lock`), X3 (D89), X4 (D91), X5 (D94), X6 (D95), X8 (D90), the Majors (D93, D96) and the Nits.
* **Counts:** 8 Blockers fixed (3 after an owner decision), about 27 Majors fixed, Nits fixed; 0 contested; 0 declined.
* **Residual risks:** p2996 coverage in gcov mode is unproven until M0 (j); the gha-outrunner runner-as-root choice is decided in the M2 gate; the binutils and make apt versions are verified in M0 (f); one PAT for every future project widens the blast radius of a leak.

## Re-audit (2026-11-13, the stage's one allowed re-audit)

Three fresh reviewers (IR, CD, ST) re-checked the Detailed Implementation.

* **IR: not ready, 4 new Blockers**, all caused by the first fix pass:
  - N1: the publish task still called Actions;
  - N2: going public would expose unscrubbed design history;
  - N3: M0 (i) needed a merge queue that didn't exist yet;
  - N4: setup steps used tasks that only land in M1a PR 6.
  Plus 8 Majors and 3 Nits.
* **CD: 1 Blocker** (`components = ["main"]` won't parse; verified at `apt_sources.rs:44`), 4 Majors and 8 Nits. Most earlier technical fixes checked out against the source.
* **ST: 11 Majors and 9 Nits**, all wording, placement and naming.

**Resolution.**
- **N2:** the owner chose "scrub locally, push one squashed commit" (D97). The scrub list is kept outside every repository: both dotfiles repositories are public (verified).
- **Applied as proposed:**
  - N1: publish split between tasks and workflow steps (D98);
  - N3 and N4: the new setup order, with a bootstrap commit and ruleset phases;
  - the CD Blocker and the Majors;
  - the style items.
- **A side-note added** a parse check of the schema to M0 (f).

**Residual risks, accepted at the convergence cap:**
- p2996 coverage in gcov mode is unproven until M0 (j);
- the cross-release apt source (`resolute` on 26.10) is unproven until M0 (f);
- the runner-as-root choice is decided at the M2 gate;
- one PAT serves every future project;
- the scrub and the licence now sit on the M0-Linux critical path.

Status: resolved (re-audit).
