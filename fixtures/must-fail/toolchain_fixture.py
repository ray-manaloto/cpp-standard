"""Exercise the fetch refusal and fallback with local stand-ins for GHCR and attestation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/toolchain"))

import fetch

HASH = "5eed5eed5eed5eed"
WRONG_HASH = "0badc0de0badc0de"
TAG = f"standin-linux-arm64-{HASH}"
REPOSITORY = f"ghcr.io/{fetch.REPO}/must-fail-standin"
DIGEST = "sha256:" + "a" * 64
SUBJECT = f"oci://{REPOSITORY}@{DIGEST}"


def archive(path: Path, marker: str, hash_: str) -> Path:
    with tempfile.TemporaryDirectory() as directory:
        prefix = Path(directory)
        (prefix / "bin").mkdir()
        (prefix / "bin/marker").write_text(marker + "\n")
        (prefix / fetch.HASH_FILE).write_text(hash_ + "\n")
        subprocess.run(
            ["tar", "--zstd", "-cf", str(path), "-C", directory, "."], check=True
        )
    return path


class FixtureImage:
    def __init__(self, payload: Path) -> None:
        self.payload = payload

    def find(self, tag: str) -> fetch.Image | None:
        if tag != TAG:
            return None
        return fetch.Image(f"{REPOSITORY}:linux-arm64-{HASH}", DIGEST)

    def download(self, image: fetch.Image, tag: str, dest: Path) -> Path:
        return self.payload


def fixture(kind: str, tmp: Path, plant: bool) -> list[str]:
    valid = kind == "wrong-hash" or plant
    payload_hash = WRONG_HASH if kind == "wrong-hash" and not plant else HASH
    refused = archive(tmp / "refused.tar.zst", "refused", payload_hash)
    rebuilt = archive(tmp / "rebuilt.tar.zst", "rebuilt", HASH)
    old = archive(tmp / "old.tar.zst", "before", HASH)
    root = tmp / "installed"
    calls: list[str] = []

    def verify(subject: str) -> bool:
        calls.append(subject)
        return valid and subject == SUBJECT

    def rebuild(_: str) -> Path:
        return rebuilt

    def fail_rebuild(tag: str) -> Path:
        raise subprocess.CalledProcessError(1, ["artifact:build", tag])

    problems = []
    reason = fetch.HASH_FILE if kind == "wrong-hash" else "attestation"
    order = fetch.sources(fetch.Context.from_env({}))
    for rebuild_fn, expected in ((rebuild, "rebuilt"), (fail_rebuild, "before")):
        fetch.install(old, TAG, root)
        calls.clear()
        result = fetch.fetch(
            TAG,
            root,
            order,
            FixtureImage(refused),
            verify,
            rebuild_fn,
            tmp / "staged",
            stop_on_source_error=True,
        )
        marker = (root / TAG / "bin/marker").read_text().strip()
        if marker != expected:
            problems.append(f"installed {marker!r}, expected {expected!r}")
        if calls != [SUBJECT]:
            problems.append(f"verifier called with {calls!r}, expected {SUBJECT}")
        if len(result.refusals) != 1 or reason not in result.refusals[0]:
            problems.append(f"expected a refusal for {reason}, got {result.refusals}")
    return problems


def main(kind: str) -> int:
    if kind not in {"unattested", "wrong-hash"}:
        raise ValueError(kind)
    with tempfile.TemporaryDirectory() as directory:
        problems = fixture(
            kind, Path(directory), os.getenv("MUST_FAIL_PLANT") == "accept"
        )
    for problem in problems:
        print(f"FIXTURE WENT GREEN: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"REFUSED as required: toolchain-{kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
