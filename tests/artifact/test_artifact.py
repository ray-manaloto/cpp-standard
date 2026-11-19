"""Tests of python/artifact/artifact.py: the three `artifact-check` cases, the four `resolve`
cases, and the agreement of publish.yml's inline names with `artifact:names` (environment-standard.md
file plan; spec #122 Testing Decisions). The registry, the clock and the verifier are fakes, so
nothing here needs the network, Docker or GitHub. Run: python3 -I tests/artifact/test_artifact.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/artifact"))

import artifact

PUBLISH = ROOT / ".github/workflows/publish.yml"
BASE = "base-arm64-0123456789abcdef"
TOOLS = "tools-arm64-fedcba9876543210"
TOOLCHAIN = "p2996-linux-arm64-00112233445566aa"
IMG = "ghcr.io/ray-manaloto/cpp-standard"
DIGEST = "sha256:" + "a" * 64
PR_DIGEST = "sha256:" + "b" * 64


class FakeRegistry:
    """Refs to digests. `appears` maps a ref to the probe number from which it exists."""

    def __init__(
        self, refs: dict[str, str], appears: dict[str, int] | None = None
    ) -> None:
        self.refs = refs
        self.appears = appears or {}
        self.probes: dict[str, int] = {}

    def digest(self, ref: str) -> str | None:
        self.probes[ref] = self.probes.get(ref, 0) + 1
        if ref in self.appears and self.probes[ref] < self.appears[ref]:
            return None
        return self.refs.get(ref)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def _check(
    registry: FakeRegistry, timeout: float = 30, pr: int | None = 7
) -> list[str]:
    clock = FakeClock()
    return artifact.check(
        [TOOLS],
        registry,  # type: ignore[arg-type]
        pr,
        False,
        timeout,
        10,
        artifact.Clock(clock.now, clock.sleep),
        log=lambda _: None,
    )


class ArtifactCheck(unittest.TestCase):
    def test_every_tag_exists(self) -> None:
        self.assertEqual(
            _check(FakeRegistry({f"{IMG}/tools:arm64-fedcba9876543210": DIGEST})), []
        )

    def test_pr_image_counts_in_a_pr_run(self) -> None:
        ref = f"{IMG}/tools:pr-7-arm64-fedcba9876543210"
        self.assertEqual(_check(FakeRegistry({ref: PR_DIGEST})), [])

    def test_tag_appears_during_the_wait(self) -> None:
        ref = f"{IMG}/tools:pr-7-arm64-fedcba9876543210"
        reg = FakeRegistry({ref: PR_DIGEST}, appears={ref: 3})
        self.assertEqual(_check(reg), [])
        self.assertEqual(reg.probes[ref], 3)

    def test_missing_tag_fails_by_name_after_a_short_wait(self) -> None:
        reg = FakeRegistry({})
        self.assertEqual(_check(reg, timeout=25), [TOOLS])
        # Polled at 0, 10, 20 and once at the deadline (25), never past it.
        self.assertEqual(reg.probes[f"{IMG}/tools:arm64-fedcba9876543210"], 4)
        msg = artifact.missing_message(TOOLS, 7, False, 25, "run 1")
        self.assertIn(TOOLS, msg)
        self.assertIn("run 1", msg)

    def test_merge_queue_looks_for_its_own_image(self) -> None:
        self.assertEqual(
            artifact.candidates(TOOLS, 7, True)[1],
            f"{IMG}/tools:pr-7-mq-arm64-fedcba9876543210",
        )


class Resolve(unittest.TestCase):
    main_ref = f"{IMG}/tools:arm64-fedcba9876543210"
    pr_ref = f"{IMG}/tools:pr-7-arm64-fedcba9876543210"

    def _resolve(
        self, refs: dict[str, str], event: str, verified: bool = True
    ) -> artifact.Resolved:
        seen: list[str] = []

        def verifier(image: str) -> bool:
            seen.append(image)
            return verified

        r = artifact.resolve(TOOLS, event, 7, False, FakeRegistry(refs), verifier)  # type: ignore[arg-type]
        self.assertEqual(seen, [f"{IMG}/tools@{DIGEST}"] if r.source == "main" else [])
        return r

    def test_main_image_is_verified_and_used_by_digest(self) -> None:
        r = self._resolve(
            {self.main_ref: DIGEST, self.pr_ref: PR_DIGEST}, "pull_request"
        )
        self.assertEqual(r, artifact.Resolved(f"{IMG}/tools@{DIGEST}", "main"))

    def test_pr_run_without_main_image_uses_its_own(self) -> None:
        for event in ("pull_request", "merge_group"):
            r = self._resolve({self.pr_ref: PR_DIGEST}, event)
            self.assertEqual(r, artifact.Resolved(f"{IMG}/tools@{PR_DIGEST}", "pr"))

    def test_main_run_without_main_image_fails(self) -> None:
        for event in ("push", "schedule", "workflow_dispatch"):
            with self.assertRaisesRegex(artifact.ArtifactError, "no unattested image"):
                self._resolve({self.pr_ref: PR_DIGEST}, event)

    def test_image_signed_from_a_branch_is_refused(self) -> None:
        # The verifier refuses (the real one: tests/image_verify/); resolve must not fall back.
        with self.assertRaisesRegex(artifact.ArtifactError, "refused"):
            self._resolve(
                {self.main_ref: DIGEST, self.pr_ref: PR_DIGEST}, "pull_request", False
            )

    def test_pr_number_from_the_ref(self) -> None:
        self.assertEqual(
            artifact.pr_from_ref(
                "merge_group", "refs/heads/gh-readonly-queue/main/pr-12-" + "c" * 40
            ),
            (12, True),
        )
        self.assertEqual(
            artifact.pr_from_ref("pull_request", "refs/pull/12/merge"), (12, False)
        )
        self.assertEqual(artifact.pr_from_ref("push", "refs/heads/main"), (None, False))


def publisher_names_script(text: str) -> str:
    """The names step of publish.yml, between its BEGIN and END markers."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "# BEGIN names")
    end = next(i for i, line in enumerate(lines) if line.strip() == "# END names")
    block = lines[start + 1 : end]
    indent = min(len(line) - len(line.lstrip()) for line in block if line.strip())
    return "\n".join(line[indent:] for line in block) + "\n"


def run_publisher(script: str, tag: str) -> dict[str, str]:
    with tempfile.NamedTemporaryFile("r", suffix=".out") as out:
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            check=True,
            env={"PATH": os.environ["PATH"], "TAG": tag, "GITHUB_OUTPUT": out.name},
        )
        return dict(
            line.split("=", 1) for line in Path(out.name).read_text().splitlines()
        )


def disagreements(script: str) -> list[str]:
    bad = []
    for tag in (BASE, TOOLS, TOOLCHAIN):
        want, got = artifact.names(tag), run_publisher(script, tag)
        if want != got:
            bad.append(f"{tag}: artifact:names {want} != publish.yml {got}")
    return bad


class PublisherNames(unittest.TestCase):
    def test_publisher_and_task_agree(self) -> None:
        self.assertEqual(disagreements(publisher_names_script(PUBLISH.read_text())), [])

    def test_a_changed_publisher_name_is_caught(self) -> None:
        script = publisher_names_script(PUBLISH.read_text())
        mutated = script + 'echo "image=ghcr.io/somewhere/else" >> "$GITHUB_OUTPUT"\n'
        self.assertNotEqual(disagreements(mutated), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
