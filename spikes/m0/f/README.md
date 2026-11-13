# M0 (f) spike, Renovate leg

`.mise/conf.d/old.toml` holds an old pin (node 20.0.0). `config.js` limits
Renovate to the mise manager on this directory, one PR on a `spike-m0f/`
branch, and adds the file pattern Renovate needs for `.mise/conf.d/`.

Run on 2026-11-13 from a workstation with the agent App's token,
because `GITHUB_TOKEN` may not open pull requests (environment-standard.md
§6):

```sh
RENOVATE_TOKEN="$(mise run -q agent:token)" docker run --rm -e RENOVATE_TOKEN \
  -e RENOVATE_CONFIG_FILE=/cfg/config.js \
  -e RENOVATE_REPOSITORIES=ray-manaloto/cpp-standard \
  -e 'RENOVATE_BASE_BRANCHES=["spike/m0-f"]' \
  -v "$PWD/spikes/m0/f:/cfg:ro" \
  ghcr.io/renovatebot/renovate:44.239.1@sha256:7dba1a3b916a2cf302ba0df458ddcc8fcbac3c92d0fe9882ac13ba0363de656b
```

The control run used the same command with `RENOVATE_DRY_RUN=extract` and
the `mise` block removed from `config.js`. Results are in
`spikes/m0/README.md`. Deleted after M0.
