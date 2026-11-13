# M0 spike results

One line per check in environment-standard.md section 10. The spike code
is deleted after M0; this file is kept.

## (i) The packslip and cache leg (2026-11-13)

| Check | Result | Evidence |
|---|---|---|
| Test release published as draft, upload, sign (`jdx/packslip` v1.11.4, `attest: false`), publish; tag `m0i-linux-arm64-v0.0.1-r.13.1`, titled with its artifact tag | PASS | [run 43480269574](https://github.com/ray-manaloto/cpp-standard/actions/runs/43480269574), job `publish` |
| `packslip install` with the exact `builder.yml@refs/heads/main` identity installs it | PASS | same run, step "Install it with the exact main identity" |
| A bundle signed on a branch verifies for its own identity and is refused for the `main` identity ("identity mismatch") | PASS | [run 43480472915](https://github.com/ray-manaloto/cpp-standard/actions/runs/43480472915), job `branch-sign` |
| A cache saved on the PR ref is not readable from the merge-group ref | PASS | [run 43483507903](https://github.com/ray-manaloto/cpp-standard/actions/runs/43483507903), job `mq-fetch` (PR #9) |
| The PR run's artifact downloads in the merge group by `run-id` | PASS | same run, job `mq-fetch` |
| `mise bootstrap packages status --missing` fails before bootstrap and exits 0 after it | PASS | every `mise-checks` job, for example run 43483507903 |
| Regenerating the lock on the Mac host and in an `ubuntu:26.04` container (the job now runs `ubuntu:26.10`), both mise 2026.11.8, gives identical files | FAIL with the default `minimum_release_age`; PASS with a fixed cutoff date | FAIL: run 43483507903, job `mise-checks`; PASS: [run 43484976602](https://github.com/ray-manaloto/cpp-standard/actions/runs/43484976602), job `mise-checks` (PR #12) |
| The test release and its tag are deleted | PASS | `gh release delete --cleanup-tag`, 2026-11-13 |

Findings for the M0-Linux exit review on 2026-11-16:

- **The lock is not reproducible as configured.** Only two lines differ:
  `exclude-newer` in `.mise/locks/**/uv.lock` and the sidecar digest in
  `mise.lock` that follows from it. mise's `minimum_release_age` defaults
  to `24h`, and `mise lock` passes "now minus 24h" to `uv lock
  --exclude-newer` (mise v2026.11.8 `src/backend/pipx/lock.rs:715`,
  `settings.toml:2333`). Options: a fixed cutoff date or `0s` in the
  settings (a reproducible lock, but no 24h hold-back on new releases), or
  compare the locks with that line ignored. The spike now uses a fixed
  date, later than every pinned release, and the lock regenerates
  identically; the date has to move forward with the pins.
- **uv must be a pinned tool.** Without uv on PATH, `mise lock` warns "uv
  >= 0.12.10 is unavailable" and silently leaves out the PyPI sidecars and
  the `uv` line in `mise.lock`. `.mise/conf.d/tools.toml` must pin uv.
- **The merge queue fires `merge_group` runs only when a required check
  exists.** With none, PR #8 merged with no merge-group run. D101 made the
  `ci.yml` job names required from setup step 7.
- The branch refusal was shown with `packslip verify`, which runs the same
  identity check as `packslip install`.
