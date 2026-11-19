# Drift report, 2026-11-18

The first EGM drift report (ticket #143, spec #122).

- **Design revision:** `docs/designs/environment-standard.md` at commit
  `4f7b0c7aa6ffc82d315a2d7f49be0072030c2b3c` (blob `3a2c0807ecebaaff281b469269db6ab82f7dfe86`). That commit is
  the merge of the resolve ticket #142 (pull request #248), and it is the last commit that changed the design.
- **Code covered:** `main` at the same commit, `4f7b0c7aa6ffc82d315a2d7f49be0072030c2b3c`.
- **Decisions log:** read at the same commit, through D174.

## How this report was made

- **The design** is `environment-standard.md`. §11 hands the order of the machine move to
  [machine-bootstrap-migration.md](machine-bootstrap-migration.md), so that document is used only to match
  `unix/home/**` and the `python/` packages it moves. Its own file list was not audited row by row (open point 1).
- **Code-bearing directories** are every directory that holds a tracked file, from `git ls-files`, except
  `docs/designs/**` (the design documents themselves). `unix/home/**` and the five M0 spike folders are counted as
  one entry each.
- **Matching is by behaviour, not by path.** A directory matches a design section when the section describes what
  its files do, even if it does not name the path; for example `python/pins` is the code behind `pins:validate`.
  Where the path is missing from the design, the match is kept and the missing link is drift item 9.
- **Code named only in a decision row is drift.** The decisions log records why; the design is what agents build
  from. Each such item is a doc fix unless the owner prefers a code change.
- **Planned means the design names where it goes:** a milestone, a pull request of the M1a plan, the follow-up spec,
  or an open issue that the design says carries it. D156 changed the M1a plan, and the design says that where the
  file table's PR column differs, D156 wins (Detailed Implementation, M1a, first paragraph). This report uses D156's
  placement.
- **Depth.** Each file the design's tables name was checked for presence. Present files were checked against their
  row's status claims ("on `main` today", "already on `main`", "does not exist yet") and against a sample of their
  stated contents. There was no line-by-line content audit of every present file, and no host or live GitHub
  setting was inspected.
- **Coverage check.** A script checked that every directory from `git ls-files` and every file path in the design's
  tables appears in this report. Short names that only repeat a full path in the same row (`ci.yml`, `base.json`)
  and build outputs that are not repository files (`dist/`, `.cache/`, `capabilities.json`, `image.txt`,
  `inputs-hash.txt`) are folded into their full paths.

## environment-standard.md

### Drift: code the design does not describe

Each item is one fix. The owner kept all eleven (2026-11-18): item 1 has its own issue, items 2 to 10 share one
issue, and item 11 is part of the Spack container probe's ticket.

| # | Drift | Where | Fix | Issue |
|---|---|---|---|---|
| 1 | The `cpp-standard-agents` App's private key is held by an Actions job. `.github/workflows/apt-bump.yml` mints App tokens from the secret `APT_BUMP_PRIVATE_KEY` in the `apt-bump` environment (D173). Setup step 6 says the key is "never printed, never enters the VM, and no Actions job holds it"; §6 Credentials says jobs receive only `GITHUB_TOKEN`; §6 Credential storage keeps the App key on the Mac host only; and §6 Job permissions has no `apt-bump.yml` row. §7 describes the workflow but not its credential. | `.github/workflows/apt-bump.yml`; §6; setup step 6 | Doc fix (record the environment, its branch rule and the accepted risk in §6, and add the row), or a code fix that opens the PRs another way | #256 |
| 2 | The heavy-slot guard and the guarded test tabs have no design text. `slot:check`, `slot:grant`, `slot:release`, `slot:clear-expired` and `slot:guard-check` (#179), and `agents:testtab` and `agents:testtab-check` (#178), are built on `python/agents/{slot,slot_check,testtab,testtab_check,testguard}.py` and the project skill `run-testtab`. §9 covers worktrees, the merge queue and the session cap only. | `.mise/tasks/slot/`, `.mise/tasks/agents/testtab*`, `python/agents`, `.agents/skills/run-testtab`, `.claude/skills/run-testtab` | Doc fix: a §9 paragraph for the heavy-run slot and test tabs | #257 |
| 3 | The Python packages' gates have no design text: per-package coverage floors (`python/README.md`, #185), the suite recorder and `test:times` (`python/suites`, #186), `agents:cov`, `artifact:cov`, `pins:cov` and `suites:cov`, pctools' own gate (`pctools:check`, `pctools:codegen`, `pctools:lock`, `pctools:sync`, `pctools:test`) with its lint pins in `.mise/conf.d/python.toml`, and the hk steps that run them (`ruff`, `ruff-format`, `ty`, `pctools-*`, `*-cov`). §5's lint gate lists the C++, shell, workflow and config builtins only. | `python/README.md`, `python/suites`, `.mise/tasks/{agents,artifact,pins,suites}/cov`, `.mise/tasks/test/times`, `.mise/tasks/pctools/`, `.mise/conf.d/python.toml`, `hk.pkl` | Doc fix: one paragraph in §5 for the Python gates | #257 |
| 4 | The repository workflow tools are described only in the decisions log. The root `mise.toml` is a mise monorepo root with `[monorepo]` and an `[env]` table (D163), but §3 and the schema say it holds `min_version`, `[settings]` and `[hooks]` only and that every task is a file task (D93). `repotools.toml` sets the merge gate of `//repo:pr-merge` (D169). `mise.ci.toml`, `mise.ci.lock` and `.mise/locks/mise.ci/**` are CI's own tools (D168). `privacy:scan`, `uv:cache-warm`, the hk steps `repo-check`, `workflow-check`, `commit-msg` and `typos-msg`, and the agent docs in `docs/agents/` have no design text. | `mise.toml`, `repotools.toml`, `mise.ci.toml`, `mise.ci.lock`, `.mise/locks/mise.ci/pipx-datamodel-code-generator/0.89.0`, `.mise/tasks/privacy/`, `.mise/tasks/uv/`, `docs/agents/`, `python/repo`, `python/workflow` | Doc fix: §3 and the schema for D163; a section for the workflow tools, CI's tool config and the merge gate | #257 |
| 5 | Five `.mise/conf.d` fragments are not in the design: `build.toml`, `docker.toml`, `llvm.toml`, `python.toml` and `vm.toml`. D161 decided that only the design's five fragments are pins, but §3 and the schema still say the configuration is `mise.toml` "with five conf.d pins fragments" and list no others. The schema puts `"github:llvm/llvm-project"` (macOS only, D38) in `tools.toml`; it is in `llvm.toml`. `build.toml` pins `github:microsoft/vcpkg-tool`, while the M1a `tools.toml` row says vcpkg is not a mise tool. | `.mise/conf.d/` | Doc fix: §3 and the schema name the macOS and certification fragments (D161); or a code fix that moves the LLVM pin | #257 |
| 6 | `toolchains/gcc-macos/` is on `main` (`build.sh`, `pins.toml`, `README.md` and `macos/` with four input and argument files), but its M3 rows say the first version "lands here in M3 (D84)". The `macos/` files are not named at all. | `toolchains/gcc-macos/`, `toolchains/gcc-macos/macos` | Doc fix: say it landed early and with which status (certification, not the builder) | #257 |
| 7 | `.github/workflows/author-email.yml` (the noreply-author check on every push to `main`) has no design text and no row in §6 Job permissions. | `.github/workflows/author-email.yml` | Doc fix: a file row and a permissions row | #257 |
| 8 | Files that implement a designed piece are not named where the design describes it. `image:resolve` does what the `image:verify` row says the `resolve` job does. `python/artifact` and `python/pins` are the code behind `artifact:*`, `pins:validate` and `pins:apt-bump`. `docs/runbooks/agent-app-create.sh` is the setup-step-6 script. `tests/artifact/`, `tests/apt_bump/`, `tests/pins_validate/` and `tests/publish_refusal/` are the tests the rows describe without a path. `.betterleaksignore` is an hk settings file missing from the `.editorconfig`, `.rumdl.toml`, `.ryl.toml`, `_typos.toml` row. | `.mise/tasks/image/resolve`, `python/artifact`, `python/pins`, `docs/runbooks/agent-app-create.sh`, `tests/artifact`, `tests/apt_bump`, `tests/pins_validate`, `tests/publish_refusal`, `.betterleaksignore` | Doc fix: add the paths to their rows, so the next drift report finds them by name | #257 |

### Drift: design text that no code implements and that no later work is assigned

| # | Drift | Where in the design | Fix | Issue |
|---|---|---|---|---|
| 9 | `.mise/conf.d/tools.toml`'s row (M1a PR 1, merged) lists mold, sccache, `gh`, packslip, `"pipx:clang-format"`, jouet, fnox and the tier-2 tools. The file holds cmake, ninja, python, uv and gcovr. No PR or milestone is named for the rest. | M1a file table, `tools.toml` row; schema | Doc fix (move each tool to the PR that needs it, e.g. clang-format to PR 4 with the C++ builtins), or add the pins | #257 |
| 10 | Status text that the code has overtaken: the `ci.yml` row says "on `main` today every job but `lint` is an `echo` stub on `ubuntu-24.04`", but only `must-fail` is still a stub on `ubuntu-24.04`; the other five jobs, `lint` included, run on `ubuntu-26.04-arm`. Setup step 3 says the M0 (i) spike's `builder.yml` (jobs `build`, `mq-fetch`, `publish`, `branch-sign`, `mise-checks`) is on `main`; PR 2's `builder.yml` (jobs `tags`, `build`, `pr-image`, `dispatch`) replaced it. `SITEMAP.md` still says the design is Goldfish-reviewed through D135 with D136 to D155 awaiting review; the design's status header says D136 to D155 were reviewed. | M1a `ci.yml` and `builder.yml` rows; setup step 3; `docs/designs/SITEMAP.md` | Doc fix | #257 |
| 11 | The Spack layering (§11, D142, D144, D145) is marked "planned, not built", behind open question Q9, with no milestone, PR or follow-up spec. | §11 Spack | Doc fix (name where it goes, or move it out of Level 1) | #253 |

### Planned, not drift

Design text that no code implements yet, with the place the design assigns it. A design item with an open
ticket counts as planned, not drift (owner, 2026-11-18).

| Item | Assigned to | Where the design says so |
|---|---|---|
| `toolchains/p2996/build.sh`, `toolchains/p2996/pins.toml`, `toolchains/p2996/linux/**`, `.mise/tasks/toolchain/fetch`, the real `must-fail` job and its `toolchain:fetch` refusal tests, the deletion of `spikes/m0/{bj,f,g,h,i}/**`, `.github/workflows/spike-m0-bj.yml`, `.github/workflows/spike-m0-h.yml` and the `spikes/**/mise.toml` glob in `hk.pkl` | M1a PR 3 | M1a PR order item 3; file rows; D156 |
| `CMakeLists.txt` and `CMakePresets.json` in their final form, `cmake/presets/{base,compilers,checks,matrix}.json` with every preset, `cmake/probes.cmake` with `profile-data.cmake`, `cmake/capabilities.lock.json`, `gate-policy.toml`, `.mise/tasks/gate/policy`, `gate-removals.toml`, `.mise/tasks/caps/update`, `vcpkg.json`, `vcpkg-configuration.json`, `triplets/*.cmake`, `.clang-format`, `.clang-tidy`, `src/cppstd/core.cppm`, `tests/core_test.cpp`, `docs/standard/coverage.md`, `fixtures/must-fail/` with `expected.toml`, `.mise/tasks/ci/fast`, `.mise/tasks/ci-must-fail`, `.mise/tasks/doctor`, `.mise/tasks/vcpkg/bootstrap`, `gate-items.toml`, `.github/workflows/post-merge.yml`, and the hk C++ builtins | M1a PR 4, five pull requests | M1a PR order item 4 (which moves `gate-removals.toml` from PR 6 to PR 4); file rows; D156 |
| `src/fix/encoder.cppm`, `tests/fix_encoder_test.cpp` | M1a PR 5 | M1a PR order item 5 |
| `.devcontainer/devcontainer.json`, `.devcontainer/compose.yaml`; the gate jobs in the tools image with `toolchain:fetch` | Spec #122 (moved forward from PR 6) | M1a, first paragraph and PR order item 6; D156 |
| `README.md`, `.github/owned-roots.txt`, CODEOWNERS with the trust roots (`.github/CODEOWNERS`), the full `.mise/tasks/repo/rulesets` with phases `m1b` and `m2` (`.github/rulesets/main.json`), `.github/workflows/repo-verify.yml`, `tests/agent_token/`, `docs/runbooks/agent-app.manifest.json` and `docs/runbooks/agent-app.md` without actions write, the final `ci.yml` without `workflow_dispatch`, `docs/standard/compilers.md`, `docs/standard/build.md`, `docs/standard/checks.md`, the owned-roots and fence text in `AGENTS.md`, the agent-token tests of `.mise/tasks/agent/token`, setup steps 9 and 10 | Follow-up spec "M1a trust roots and repository rules" | M1a PR order item 6; D156 |
| `renovate.json5`, `.mise/tasks/review/digest`, `.github/workflows/digest.yml`, `.github/workflows/retention.yml`, `.github/rulesets/toolchain-tags.json`, `.jouet/project.toml`, `.jouet/rules/gate-guard.toml`, `.jouet/rules/tests/`, `.mcp.json`, `fnox.toml`, `.mise/tasks/linux/run` | M1b | M1b file table; §10 M1b and cut order |
| `image/runner.inputs.toml`, `spikes/m2/README.md`, `runner/hook/job-started.sh`, `runner/pc/outrunner.yaml`, `runner/pc/golden.md`, `.mise/tasks/runner/pc-image`, `docs/runbooks/pc-runner.md`, amd64 in `.github/workflows/builder.yml` | M2 | M2 file table; `image/runner.inputs.toml` row ("M2, new") |
| `vm/inputs.toml`, `.mise/tasks/vm/golden`, `.mise/tasks/vm/dev`, `runner/mac/agent-token.plist`, `runner/mac/outrunner.yaml`, `.github/workflows/mac-gate.yml`, `docs/runbooks/mac-runner.md`, `toolchains/p2996/macos/**` | M3 | M3 file table; `toolchains/p2996/macos/**` row ("M3, new") |
| `canary/pins.toml`, `canary/allowlist.toml`, `.mise/tasks/canary`, `.github/workflows/canary.yml` | M4 | M4 file table |
| `.mise/tasks/perf/instructions`, `.mise/tasks/review/cap`, `review/cap.toml`, `docs/standard/tools.md`, `docs/standard/perf.md` | M5 | M5 file table |
| D148's `minimum_release_age = "0s"`; how Renovate's `CI Check` and auto-merge fit the six required checks | Issue #222 | §3 `[settings]`; §7 |
| One `build.sh` for the CI and certification p2996 builds | Issue #226 | §11 Certification playbooks |
| The Mac `agent-secrets` service's image coupling and stale-token report; retiring `GEMINI_API_KEY` in `agents:pc-doppler` | Issues #221, #224 | §12 Logins with no typing |
| Where agents run and who starts containers once agents are isolated | Issue #219 | §6 The fence; §10 M2 entry gate |
| What `repo:rulesets --phase m2` adds | Issue #220 | §6 settings check; §10 M2 entry gate |
| Runner-side admission before cpp-standard gets a PC slot | Issue #218 | §6 Public repository and self-hosted runners (D174) |
| Whether the host inputs join the trust roots, and who applies each | Issue #227 | §6 Trust roots |
| Verifying the apt release file's signature and Valid-Until | A follow-up ticket (#229 in D173) | §7 apt pins |

### Directory map

Every code-bearing directory, matched to the design section that describes it, or to its drift item.

| Directory | Design section | Status |
|---|---|---|
| `.` (root files) | §3, M1a file table, §11 machine configs | Matched; `mise.toml` drift 4, `repotools.toml`, `mise.ci.toml` and `mise.ci.lock` drift 4, `.betterleaksignore` drift 8 |
| `.agents/skills/egm-check`, `.agents/skills/egm-check/references`, `.agents/skills/egm-check/scripts` | M1b `.agents/skills/*` row (`.agents/skills/egm-check/` is already on `main`) | Matched |
| `.agents/skills/macos-certify`, `.agents/skills/ubuntu-certify`, `.agents/skills/ubuntu-arm64-run` | M1b `.agents/skills/*` row; §11 certification playbooks | Matched, ahead of M1b |
| `.agents/skills/pins-apt-bump` | M1b `.agents/skills/*` row; §7 ("and the skill of the same name") | Matched |
| `.agents/skills/run-testtab` | none | Drift 2 |
| `.claude`, `.claude/skills` | M1b `.claude/settings.json` and `.claude/skills/*` row (`.claude/skills/<name>` links) | Matched, ahead of M1b; the `run-testtab` link is drift 2 |
| `.github` | §6 Trust roots; setup step 6 (`.github/CODEOWNERS`) | Matched |
| `.github/rulesets` | §6 settings check; `.github/rulesets/main.json` row | Matched |
| `.github/workflows` | §2, §5, §6, §7; M0 and M1a file tables | Matched; `apt-bump.yml` drift 1, `author-email.yml` drift 7 |
| `.mise` | §3 (`.mise/mise.lock`) | Matched |
| `.mise/apple-bin` | §11 certification playbooks (`docs/standard/macos.md` names `dsymutil` there) | Matched |
| `.mise/conf.d` | §3; schema | Matched for the five pins fragments; the other five are drift 5 |
| `.mise/locks/pypi-gcovr/8.8~6108473f` | §3 (`.mise/locks/**` sidecars) | Matched |
| `.mise/locks/mise.ci/pipx-datamodel-code-generator/0.89.0` | none | Drift 4 |
| `.mise/tasks` | §3, §6 (tasks are files under `.mise/tasks/`) | Matched |
| `.mise/tasks/agent` | §6 Credential storage; `.mise/tasks/agent/token` row | Matched |
| `.mise/tasks/agents` | §12 (`agents:image`, `agents:up`, `agents:refresh`, `agents:agy-login`, `agents:app-create`, `agents:pc-doppler`) | Matched; `agents:testtab*` drift 2, `agents:cov` drift 3 |
| `.mise/tasks/artifact` | §2; `artifact/tag`, `artifact/check`, `artifact/build` and `artifact/names` rows | Matched; `artifact:cov` drift 3 |
| `.mise/tasks/certify` | §11 certification playbooks (`certify:macos`, `certify:ubuntu`) | Matched |
| `.mise/tasks/ci` | §5; `.mise/tasks/ci/_default` row | Matched (tracer-bullet form, one preset; PR 4 completes it) |
| `.mise/tasks/image` | §2 step 5; `.mise/tasks/image/verify` row | Matched; `image:resolve` drift 8 |
| `.mise/tasks/pc` | §11 (`pc:doctor`) | Matched |
| `.mise/tasks/pctools` | none (pc:doctor's package gate) | Drift 3 |
| `.mise/tasks/pins` | §3 `pins:validate`; §7 `pins:apt-bump` | Matched; `pins:cov` drift 3 |
| `.mise/tasks/privacy` | none | Drift 4 |
| `.mise/tasks/repo` | §6 settings check; `.mise/tasks/repo/rulesets` row | Matched |
| `.mise/tasks/slot` | none | Drift 2 |
| `.mise/tasks/suites`, `.mise/tasks/test` | none | Drift 3 |
| `.mise/tasks/toolchain` | §11 certification playbooks (`toolchain:acpp-metal` and `toolchain:iwyu-llvm23` are steps of `docs/standard/macos.md` and `docs/standard/ubuntu.md`) | Matched through the playbooks; `toolchain:fetch` is planned for PR 3 |
| `.mise/tasks/ubuntu` | §11 certification playbooks (`ubuntu:arm64` and `ubuntu:clangd` in `docs/standard/ubuntu.md`) | Matched through the playbooks |
| `.mise/tasks/uv` | none | Drift 4 |
| `cmake/presets` | §4; `CMakePresets.json, cmake/presets/{base,compilers,checks,matrix}.json` row | Matched (tracer-bullet form; PR 4 completes it) |
| `docs/agents` | none | Drift 4 |
| `docs/runbooks` | setup step 6; `docs/runbooks/agent-app.md` row | Matched; `agent-app-create.sh` drift 8 |
| `docs/standard` | §11, §12 | Matched |
| `docs/standard/agent-auth` | §6 Trust roots (`docs/standard/agent-auth/**`); §12 Logins with no typing | Matched |
| `docs/standard/gha-runner` | §6 Public repository and self-hosted runners | Matched |
| `docs/standard/reports` | §11 ("kept under `docs/standard/reports/`") | Matched |
| `docs/standard/ubuntu-cert-tools`, `docs/standard/ubuntu-cert-tools/.mise/locks/pypi-gcovr/8.8` | §11 certification playbooks (`docs/standard/ubuntu-cert.Dockerfile`) | Matched |
| `docs/standard/ubuntu-p2996` | §11 (`docs/standard/ubuntu-p2996/build-linux.sh`) | Matched |
| `image` | §2, §3; `image/base.Dockerfile`, `image/tools.Dockerfile` and `image/base.inputs.toml` rows | Matched |
| `python` | none (`python/README.md`) | Drift 3 |
| `python/agents` | §12 (`app_create.py` behind `agents:app-create`) | Matched; `slot*.py`, `testtab*.py`, `testguard.py` drift 2 |
| `python/artifact` | §2 (behind `artifact:*`, `image:verify`) | Matched; path not named, drift 8 |
| `python/guards/src/guards` | §11 through the migration doc (M1 copy) | Matched |
| `python/pctools`, `python/pctools/schema`, `python/pctools/src/pctools`, `python/pctools/src/pctools/data`, `python/pctools/tests` | §11 (`pc:doctor`, `gha-fence`) | Matched; its gate is drift 3 |
| `python/pins` | §3 and §7 (behind `pins:validate`, `artifact:tag`, `pins:apt-bump`) | Matched; path not named, drift 8 |
| `python/repo`, `python/repo/lint/rules`, `python/repo/lint/tests`, `python/repo/schema`, `python/repo/src/repotools`, `python/repo/tests` | §11 through the migration doc (moved by D160) | Matched as a moved package; its role here is drift 4 |
| `python/suites` | none | Drift 3 |
| `python/workflow`, `python/workflow/schema`, `python/workflow/src/workflowtools`, `python/workflow/tests` | §11 through the migration doc (moved by D160) | Matched as a moved package; its role here is drift 4 |
| `spikes/m0` | §10 M0 results; `spikes/m0/README.md` row | Matched |
| `spikes/m0/{bj,f,g,h,i}/**` | M0 file table | Matched; deletion planned for PR 3 |
| `src`, `src/standin` | M1a, first paragraph (the tracer bullet's "M0 stand-in module", D156) | Matched |
| `tests` | M1a, first paragraph (tracer bullet, `tests/standin_test.cpp`) | Matched |
| `tests/apt_bump`, `tests/artifact`, `tests/pins_validate`, `tests/publish_refusal` | §7, §2 (`artifact:names` test), §3, `publish.yml` row (negative test) | Matched; paths not named, drift 8 |
| `tests/artifact_tag` | §2 step 2 | Matched |
| `tests/image_verify`, `tests/image_verify/branch-signed` | `.mise/tasks/image/verify` row | Matched |
| `toolchains/gcc-macos`, `toolchains/gcc-macos/macos` | M3 file table | Drift 6 (present ahead of M3) |
| `unix/home/**` | §11, through [machine-bootstrap-migration.md](machine-bootstrap-migration.md) (M1 copy, 2026-11-17) | Matched |

### Files the design's tables name

Each file is present, planned (see the Planned table for where), or drift.

| File | Status |
|---|---|
| `LICENSE`, `.mise/conf.d/apt-sources.toml`, `.mise/conf.d/apt-toolchain-host.toml`, `.mise/conf.d/apt.toml`, `.mise/conf.d/lint.toml`, `.mise/mise.lock`, `.mise/locks/**`, `image/base.inputs.toml`, `pins-allowlist.toml`, `.mise/tasks/pins/validate`, `.mise/tasks/artifact/tag`, `.mise/tasks/artifact/check`, `.mise/tasks/artifact/build`, `.mise/tasks/artifact/names`, `.github/workflows/publish.yml`, `.mise/tasks/image/verify`, `image/base.Dockerfile`, `image/tools.Dockerfile`, `tests/artifact_tag/`, `tests/image_verify/`, `.mise/tasks/check`, `.editorconfig`, `.rumdl.toml`, `.ryl.toml`, `_typos.toml`, `.github/workflows/builder.yml`, `docs/designs/level-1/m2-trust-backlog.md`, `docs/standard/gha-runner/README.md` | Present |
| `spikes/m0/README.md`, `spikes/m0/{bj,f,g,h,i}/**`, `.github/workflows/spike-m0-bj.yml`, `.github/workflows/spike-m0-h.yml` | Present; deletion (except the README) planned for PR 3 |
| `mise.toml` | Present; its extra tables are drift 4 |
| `.mise/conf.d/tools.toml` | Present; missing tools are drift 9 |
| `.github/workflows/ci.yml` | Present; status text drift 10; `must-fail` and the final form planned (PR 3, follow-up spec) |
| `hk.pkl` | Present; PR 3 and PR 4 changes planned |
| `CMakeLists.txt`, `CMakePresets.json`, `cmake/presets/{base,compilers,checks,matrix}.json`, `.mise/tasks/ci/_default` | Present in the tracer bullet's form; PR 4 completes them |
| `AGENTS.md` | Present with the Workflow facts section; owned roots and fence planned (follow-up spec) |
| `.github/CODEOWNERS`, `.github/rulesets/main.json`, `.mise/tasks/repo/rulesets`, `.mise/tasks/agent/token`, `docs/runbooks/agent-app.md`, `docs/runbooks/agent-app.manifest.json` | Present in their first version; changes planned (follow-up spec) |
| `.claude/settings.json`, `.claude/skills/*`, `.agents/skills/*`, `.agents/skills/egm-check/` | Present (M1b row) |
| `.agents/skills/.mise-skills.json`, `.agents/skills/hk-*` | Not tracked, as the row says (per-machine, git-ignored) |
| `toolchains/gcc-macos/build.sh`, `toolchains/gcc-macos/pins.toml`, `toolchains/gcc-macos/README.md` | Present ahead of M3: drift 6 |
| `toolchains/p2996/build.sh`, `toolchains/p2996/pins.toml`, `toolchains/p2996/linux/**`, `.mise/tasks/toolchain/fetch` | Planned, PR 3 |
| `cmake/probes.cmake`, `profile-data.cmake`, `cmake/capabilities.lock.json`, `gate-policy.toml`, `.mise/tasks/gate/policy`, `gate-removals.toml`, `.mise/tasks/caps/update`, `vcpkg.json`, `vcpkg-configuration.json`, `triplets/*.cmake`, `.clang-format`, `.clang-tidy`, `src/cppstd/core.cppm`, `tests/core_test.cpp`, `docs/standard/coverage.md`, `fixtures/must-fail/`, `expected.toml`, `.mise/tasks/ci/fast`, `.mise/tasks/ci-must-fail`, `.mise/tasks/doctor`, `.mise/tasks/vcpkg/bootstrap`, `gate-items.toml`, `.github/workflows/post-merge.yml` | Planned, PR 4 |
| `src/fix/encoder.cppm`, `tests/fix_encoder_test.cpp` | Planned, PR 5 |
| `.devcontainer/devcontainer.json`, `.devcontainer/compose.yaml` | Planned, spec #122 |
| `README.md`, `.github/owned-roots.txt`, `.github/workflows/repo-verify.yml`, `tests/agent_token/`, `docs/standard/compilers.md`, `docs/standard/build.md`, `docs/standard/checks.md` | Planned, follow-up spec |
| `renovate.json5`, `.mise/tasks/review/digest`, `.github/workflows/digest.yml`, `.github/workflows/retention.yml`, `.github/rulesets/toolchain-tags.json`, `.jouet/project.toml`, `.jouet/rules/gate-guard.toml`, `.jouet/rules/tests/`, `.mcp.json`, `fnox.toml`, `.mise/tasks/linux/run` | Planned, M1b |
| `image/runner.inputs.toml`, `spikes/m2/README.md`, `runner/hook/job-started.sh`, `runner/pc/outrunner.yaml`, `runner/pc/golden.md`, `.mise/tasks/runner/pc-image`, `docs/runbooks/pc-runner.md` | Planned, M2 |
| `vm/inputs.toml`, `.mise/tasks/vm/golden`, `.mise/tasks/vm/dev`, `runner/mac/agent-token.plist`, `runner/mac/outrunner.yaml`, `.github/workflows/mac-gate.yml`, `docs/runbooks/mac-runner.md`, `toolchains/p2996/macos/**` | Planned, M3 |
| `canary/pins.toml`, `canary/allowlist.toml`, `.mise/tasks/canary`, `.github/workflows/canary.yml` | Planned, M4 |
| `.mise/tasks/perf/instructions`, `.mise/tasks/review/cap`, `review/cap.toml`, `docs/standard/tools.md`, `docs/standard/perf.md` | Planned, M5 |

## machine-bootstrap-migration.md

Used here only to match `unix/home/**`, `python/guards`, `python/repo` and `python/workflow` to §11. Its own
inventory, order and step checks were not audited against the code (open point 1).

## Open points

1. Audit `machine-bootstrap-migration.md` row by row, in the next drift report or a ticket of its own.
2. Done: each kept drift item links its issue in the **Issue** column.
