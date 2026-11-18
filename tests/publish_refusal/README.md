# The publisher refuses a pull-request build

The refusal test of `publish.yml` (spec #122 Testing Decisions; D114). It runs only on `main`,
so it is not a pull-request check: the coordinator dispatches it once in the second acceptance
step of M1a PR 2, and again whenever `publish.yml` changes. Its receipt names the revision of
`publish.yml` it ran against.

1. Pick a `builder.yml` run that came from a pull request:

   ```sh
   gh run list --repo ray-manaloto/cpp-standard --workflow builder.yml --event pull_request \
     --limit 1 --json databaseId --jq '.[0].databaseId'
   ```

2. Dispatch the publisher on `main` with that run id, and note the revision it runs:

   ```sh
   gh workflow run publish.yml --repo ray-manaloto/cpp-standard --ref main -f run_id=<run id>
   git -C <checkout> log -1 --format=%H origin/main -- .github/workflows/publish.yml
   ```

3. The run must fail in its `check` job, step "Check the builder run", with the line
   `refused: run <run id> came from a pull_request event`, and its `image` jobs must not run
   (nothing pushed, nothing attested):

   ```sh
   gh run view <publish run id> --repo ray-manaloto/cpp-standard --log-failed | grep 'refused: run'
   gh run view <publish run id> --repo ray-manaloto/cpp-standard --json jobs \
     --jq '.jobs[] | select(.name | startswith("image")) | .conclusion'   # skipped, or none
   ```

The receipt is a comment on the ticket with the publish run's URL, the refusal line and the
`publish.yml` revision.

## The branch-signed bundle of `tests/image_verify/`

That fixture needs an image attested by `publish.yml` running on a branch, which `publish.yml`
on `main` refuses to do. The coordinator pushes a scratch branch whose `publish.yml` (same path,
so the signer workflow matches) skips the `check` job, dispatches it on that branch with a
`main` builder run id, then commits `manifest.json`, `bundle.jsonl` and `ref.txt`:

```sh
skopeo inspect --raw docker://ghcr.io/ray-manaloto/cpp-standard/<base|tools>@<digest> > manifest.json
gh attestation download oci://ghcr.io/ray-manaloto/cpp-standard/<base|tools>@<digest> \
  --repo ray-manaloto/cpp-standard   # writes <digest>.jsonl; rename it bundle.jsonl
echo refs/heads/<scratch branch> > ref.txt
```

The scratch branch must push under its own image tag and attest a digest that `main` never
attested; otherwise `gh attestation download` also returns `main`'s bundle. Delete the branch and
its image afterwards.
