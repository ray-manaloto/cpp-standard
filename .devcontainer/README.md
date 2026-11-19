# The devcontainer

Open the repository in the devcontainer (arm64, the published tools image). On the host,
`initializeCommand` runs `mise run image:verify tools --env-file .devcontainer/.env`. That writes the
verified digest to the generated, gitignored `.devcontainer/.env`, and compose starts exactly that digest.
An image that fails verification never starts.
Unset `CPPSTD_TOOLS_IMAGE`, `COMPOSE_ENV_FILES` and `COMPOSE_DISABLE_ENV_FILE` before opening the
devcontainer so Compose uses the generated file.

## First start: log gh in

No GitHub token is passed into the container. `toolchain:fetch` verifies the toolchain release with
`gh attestation verify`, so gh must be logged in first. On the first create, `postCreateCommand` stops
with "gh is not logged in". Then, inside the container:

```sh
gh auth login
mise trust /workspaces/cpp-standard \
  && fetched=$(mise run -q toolchain:fetch --release-only) \
  && prefix=$(printf '%s\n' "$fetched" | sed -n 's/^prefix=//p') \
  && test -n "$prefix" \
  && export CPPSTD_P2996_PREFIX="$prefix" \
  && mise run vcpkg:bootstrap && mise run doctor
```

That command is the rest of `postCreateCommand`. Rebuild the container only to pick up a new tools image.
