# Stage 9: Implementation Readiness (re-review of D99-D134)

Status: resolved

The earlier Stage 9 report is in git history at a5452af.

**Target:** `docs/designs/environment-standard.md`. The trimmed design is
1837 lines; this review covers the Detailed Implementation, lines 1505-1837.

**Reviewers and finding counts:**

| Reviewer | ID prefix | Blocker | Major | Nit |
|---|---|---|---|---|
| `egm-implementation-readiness` | `ir-*` | 2 | 17 | 6 |
| `egm-codebase-details` | `cb-*` | 1 | 9 | 7 |
| `egm-style` | `sty-9-*` | 0 | 10 | 27 |

The reviewers had the decisions log, `m2-trust-backlog.md` and the
repository files.

## Trim check (side note, 2026-11-13)

The pre-trim design was rebuilt from the backup patch and compared with the
trimmed design.

- **Dropped decision IDs:** D125, D126, D129 and D132. D134 supersedes all
  four.
- **Kept:** every other cited decision, and the key rules: attestation,
  `inputs-hash.txt`, the runner group, draft PRs, gate removals, the
  coverage markers, the capability lock and Q5-Q8.
- **Lost:** one rule that D134 did not supersede: the `builder.yml`
  `concurrency:` group per artifact tag (D132). Without it, two runs can
  cold-build the same p2996 tag (58.6 min each) at the same time. F22 below
  restores it.

## What the reviewers agree on

**1. D134 holds.**

- No M2 backlog item has leaked into M1a.
- The trust roots match D108/D134.

**2. The plan does not match the repository as it is now.**

- The M0 spikes are on `main`: `spikes/m0/**` and two spike workflows.
- `builder.yml` on `main` is still the M0 (i) spike, with `id-token:
  write` and packslip signing.
- The App manifest still grants `actions: write`.
- `repo:rulesets` checks the org-admin count, which `GITHUB_TOKEN` cannot
  read.

**3. Many M1a files belong to no PR.**

- These have no PR: `publish.yml`, `post-merge.yml`, `gate-items.toml`, the
  vcpkg files, `.devcontainer` and the docs.
- The M1a done-condition needs a `main` run of `ci.yml`. That run never
  happens.

## Classification

### PROPOSE FIX: contradictions and wrong facts

| # | Findings | Fix |
|---|---|---|
| F1 | ir-1 | M1a is done when two runs are green on every M1a preset and fixture: the merge-group `ci.yml` run of the last M1a PR, and the `post-merge.yml` run for `main`'s tip. |
| F2 | ir-2, cb-10, sty-9-5, cb-2 | The M1a table gets a "PR" column. It gives each row its PR and marks the row new, changed or deleted. `publish.yml` goes in PR 2. `post-merge.yml` and `gate-items.toml` go in PR 4. Line 1508 changes to "one or more PRs". |
| F3 | cb-1, ir-4, sty-9-7 | The spikes are on `main`. PR 3 copies the `scc.h` patch and deletes `spikes/m0/{bj,f,g,h,i}/**`, both spike workflows and the `hk.pkl` spike glob. It keeps `spikes/m0/README.md`. A step deletes the `m0i-linux-arm64-v*` test releases and tags. Lines 1189 and 1601 change to match. |
| F4 | cb-3, ir-4 | Step 3 describes `builder.yml` as it is now. PR 2 replaces the spike jobs, removes every `id-token` grant and removes the "path must not change" comment. |
| F5 | cb-5, ir-5, sty-9-8 | The App was created with `actions: write`. PR 6 changes `agent-app.manifest.json` and `agent-app.md`, and the owner removes Actions in the App settings. Done when `gh api /app` (JWT) shows no `actions`. |
| F6 | cb-4, ir-18 | `repo:rulesets --verify` runs on `GITHUB_TOKEN` without the bypass list and without the org-admin count. The owner-run `--apply` keeps the count. The task adds phases `m1b` and `m2`. The current phase is a literal in `repo-verify.yml`, which the M1b and M2 PRs bump. |
| F7 | ir-3 | Each stub check becomes real in a named PR: `pins-validate` in PR 1; `artifact-check` and `resolve` in PR 2; `gate-linux-arm64` and `must-fail` in PR 4. Each PR's pass condition names its job. |
| F8 | sty-9-1 | `builder.yml`: in M1a every hash builds on hosted runners. The PC runners come in M2 and the Mac runners in M3. |
| F9 | sty-9-2 | The runner rows use the D117 App credential, not a PAT. If the runner tools refuse it, M2 waits for the owner. |
| F10 | sty-9-3, ir-25 | `spikes/m2/README.md` adds two items: the reviewed M2 trust design (D134) and the D127 host condition. |
| F11 | sty-9-4 | PR 3 is done when an attested `main` release installs, passes `gh attestation verify` and matches its `inputs-hash.txt`. |
| F12 | sty-9-6, ir-23 | The heading says "steps 1-8 before M1a; steps 9-10 in M1a PR 6". In step 9, the owner deletes the `audit` environment. |
| F13 | sty-9-9, cb-13, ir-12 | The p2996 row gets `upstream`. §3 drops the `flags` field. The D89 versioning is marked M2. |
| F14 | sty-9-10, ir-9 (part) | The M0 outcomes become facts: (g) failed and its fallback applies (D103); (j) passed on a stand-in (D106, to be confirmed 2026-11-16); (b) passed (D105). |
| F15 | cb-6, ir-21, ir-22 | `build.sh` and its smoke test start from `spikes/m0/h/build.sh` and `smoke.sh`, with `COMPILER_RT_DEFAULT_TARGET_ONLY=ON` and the full SHA. |
| F16 | cb-7 | `tools.toml` pins `uv`. Without uv, `mise lock` skips the PyPI entries. |
| F17 | cb-8, sty-9-31 | `renovate.json5` gets the `.mise/conf.d/*.toml` `managerFilePatterns` entry (D104) and a link to Q6. |
| F18 | cb-9, ir-8 (part) | The reflection probe tests `__cpp_impl_reflection` or `__has_feature(reflection)`. The flags are `-freflection-latest` on p2996 and `-freflection` on GCC. |
| F19 | ir-15 | `hk.pkl` excludes `fixtures/must-fail/**`. |
| F20 | ir-17 | The gate jobs get `needs: [artifact-check, resolve]`. `ci` does not run the fixtures; `ci-must-fail` does. |
| F21 | ir-11 | `gate:policy` measures removals against `git merge-base HEAD origin/main`. |
| F22 | trim check | Restore the `builder.yml` `concurrency:` group per artifact tag. |
| F23 | ir-6 | PR builds also save `image.tar` as an artifact. The PR status job, which has `packages: write`, pushes the `pr-` tag. |
| F24 | ir-7 | In M1a, `artifact-check` gets `actions: read`, so it can read the merge-group cache and runs. |
| F25 | cb-15 | `apt.toml` gets the full package list from `spike-m0-bj.yml`. |
| F26 | sty-9-11, 14, 32, 36, 37; cb-11, 12, 14, 16; ir-24 | Small corrections: citations, an out-of-date "before public", `[tasks]`, the `ci.yml` changes, the `build.md` splice rule, the existing skill and `.gitignore` lines, and the macOS row marked M3. |

### DECLINE: left to the PR that builds the file (D134)

The PR that builds each file decides the items below. Its tests and the
commit review check them. The PR description gives the definition, and the
file-plan row links to it.

| Findings | Left to the PR |
|---|---|
| ir-9 (rest) | The encoder API and test table (PR 5). |
| ir-10 | The data schemas: capabilities, the lock, `expected.toml`, `gate-items.toml`, the results JSON and `pins-allowlist.toml`. |
| ir-13 | The hardening tool and the SARIF upload (PR 4). |
| ir-14 (rest) | The hk builtins and lint tools for each PR (D102). |
| ir-16 | The task language and test runner. Today's pattern is bash with a `test:*` task. |
| ir-8 (rest) | The toolchain install path and the preset lookup (PR 3). |
| ir-19, cb-17, sty-9-20 | External citations pinned to SHAs, when the file is copied. |
| ir-20 | The preset names and job timeout. |
| Other style Nits | Wording only. |

No finding is CONTEST or ESCALATE.

Status: resolved (D135).
