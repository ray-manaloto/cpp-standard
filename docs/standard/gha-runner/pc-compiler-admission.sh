#!/usr/bin/env bash
# Runner.Worker 2.338.2 invokes this before it releases any workflow step.
repo=ray-manaloto/cpp-standard
ref=refs/heads/main
if [[ "${GITHUB_REPOSITORY:-}" == "$repo" &&
  "${GITHUB_REF:-}" == "$ref" &&
  "${GITHUB_WORKFLOW_REF:-}" == "$repo/.github/workflows/pc-compiler.yml@$ref" &&
  "${GITHUB_EVENT_NAME:-}" == workflow_dispatch &&
  "${GITHUB_RUN_ATTEMPT:-}" == 1 &&
  -n "${CPP_EXPECTED_RUN:-}" && "${GITHUB_RUN_ID:-}" == "$CPP_EXPECTED_RUN" &&
  -n "${CPP_EXPECTED_SHA:-}" && "${GITHUB_SHA:-}" == "$CPP_EXPECTED_SHA" ]]; then
  exit 0
fi

echo 'CPP admission refused this workflow assignment' >&2
# Returning a conventional failure alone can release always() cleanup steps.
if read -r worker <"/proc/$PPID/comm" && [[ "$worker" == Runner.Worker ]]; then
  kill -KILL "$PPID" && exit 1
fi
# Keep the hook pending for host teardown if the worker topology changes.
exec /bin/sleep 86400
