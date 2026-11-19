#!/usr/bin/env bash
# The refusal test of image:verify (spec #122 Testing Decisions, D59, D93, D98): an image whose
# attestation was signed from a branch, not refs/heads/main, is refused with the production flags
# (python/artifact/artifact.py verify_flags), and accepted when the source ref is its own branch
# (the control, so a verifier that refuses everything cannot pass). Runs in every `resolve` job.
#
# The fixture, under branch-signed/, is made once by publish.yml run on a branch (the
# coordinator dispatches it, D114: no other workflow holds id-token):
#   manifest.json  the image manifest, byte for byte; its sha256 is the image digest, so gh
#                  verifies the attestation of the image without pulling it
#   bundle.jsonl   the attestation bundle (gh attestation download oci://<image>@<digest>)
#   ref.txt        the branch ref it was signed from, e.g. refs/heads/<branch>
# Until the bundle is committed the test is skipped with a named reason (an open item of #128).
set -euo pipefail

dir="$(cd "$(dirname "$0")" && pwd)/branch-signed"
root="$(cd "$(dirname "$0")/../.." && pwd)"
# The policy is checked first, so it is checked even while the fixture is missing.
read -ra flags < <(python3 -I "$root/python/artifact/artifact.py" verify-flags)
for want in "--source-ref refs/heads/main" \
  "--signer-workflow ray-manaloto/cpp-standard/.github/workflows/publish.yml" \
  "--repo ray-manaloto/cpp-standard"; do
  [[ " ${flags[*]} " == *" $want "* ]] || {
    echo "FAIL: the production flags lack $want: ${flags[*]}"
    exit 1
  }
done
if [[ ! -f "$dir/bundle.jsonl" ]]; then
  echo "SKIP: tests/image_verify/branch-signed/bundle.jsonl is not committed yet (#128 open item: a branch-signed bundle made by publish.yml)"
  exit 0
fi
ref="$(<"$dir/ref.txt")"
[[ "$ref" == refs/heads/* && "$ref" != refs/heads/main ]] || {
  echo "FAIL: ref.txt holds $ref, not a branch other than main"
  exit 1
}
verify() { gh attestation verify "$dir/manifest.json" --bundle "$dir/bundle.jsonl" "$@"; }

# Control: the same bundle with the source ref swapped for its own branch must pass.
own=("${flags[@]}")
for i in "${!own[@]}"; do [[ "${own[$i]}" != refs/heads/main ]] || own[i]="$ref"; done
verify "${own[@]}" >/dev/null || {
  echo "FAIL: control: the bundle does not verify for its own ref $ref"
  exit 1
}
if verify "${flags[@]}"; then
  echo "FAIL: an image attested from $ref passed the refs/heads/main policy"
  exit 1
fi
echo "PASS: an image attested from $ref is refused by image:verify's policy"
