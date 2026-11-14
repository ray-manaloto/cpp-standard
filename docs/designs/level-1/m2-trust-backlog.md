# M2 trust backlog

Status: deferred by D134 (2026-11-13). This is the starting list for the M2
trust design, which is written and reviewed when M2 starts, after
2026-11-27. Nothing here is part of the Level 1 design until then.

Each item names the decision or review finding it came from, so the M2
design can re-decide it with the reasoning in hand.

## More trust roots

- `ci.yml`, `.mise/tasks/gate/**`, the fixture-runner task,
  `.mise/tasks/artifact/build`, `toolchains/*/build.sh` and the patches
  (D123).
- `pins-allowlist.toml` with toolchain sources allowlisted by URL prefix,
  `.mise/tasks/toolchain/fetch`, `.mise/tasks/image/verify`,
  `.mise/tasks/vm/**` and the PC image task (D125).
- `.mise/tasks/pins/validate`, `.mise/tasks/artifact/tag` and
  `tests/artifact_tag/**` (D129).
- `image/*.Dockerfile` and the non-pin scripts they COPY, `.devcontainer/**`
  and `.github/owned-roots.txt` (D132, D133).

## Checks

- A workflow-file allowlist, and a refusal of `pull_request`,
  `merge_group` and branch `push` triggers outside `ci.yml` and
  `builder.yml` (D126, D132, D133).
- A check that each pinned upstream commit is reachable from its named
  upstream branch (des-4-2, D132).
- Single-use `gate-removals.toml` entries (des-4-9, D132).
- Running `gate:policy` and the fixture runner from `main`'s copy (D115).
- An inputs-hash label on images, checked by `image:verify` (D133).
- A shared hash script for `artifact:tag`, if `publish.yml` must ever
  recompute the hash. It must not run in `publish.yml` as repository code
  (Z8-3).
- A `builder.yml` PR status job with fixed steps only, posting only
  `artifact/<tag>` contexts (D133).

## Hosts and runners

- The runner-image build job runs as a dedicated user with no host
  credentials, and without the repository's mise config. An `[env]` probe
  proves it (des-5-1, D133).
- The PC devcontainer opens only `main` or owner-authored commits, with no
  privileged mode or host mounts (des-4-5, D132).
- A replay check on `publish_run_id`, needed only if anyone but
  `GITHUB_TOKEN` and the owner can dispatch (des-5-3, D133).
- Packslip versioning (D89) and how `toolchain:fetch` finds a packslip
  release once the release tag is `<project>-v<version>`.
