"""Tests of python/artifact/artifact.py: the three `artifact-check` cases, the four `resolve`
cases, image:verify's devcontainer env file, and the agreement of publish.yml's inline names with
`artifact:names` (environment-standard.md file plan; spec #122 Testing Decisions). The registry,
the clock and the verifier are fakes, so nothing here needs the network, Docker or GitHub. Run:
python3 -I tests/artifact/test_artifact.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/artifact"))

import artifact

PUBLISH = ROOT / ".github/workflows/publish.yml"
BUILDER = ROOT / ".github/workflows/builder.yml"
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


class VerifyEnvFile(unittest.TestCase):
    """image:verify's --env-file (ticket #137, the file plan's .devcontainer row, D93): the
    devcontainer's compose starts only the digest image:verify verified; a refusal removes a
    stale env file and the error names the image."""

    tag_ref = f"{IMG}/tools:arm64-fedcba9876543210"

    def _verify(
        self,
        refs: dict[str, str],
        verified: bool = True,
        env_file: str | None = None,
        image: str = tag_ref,
    ) -> str:
        def verifier(candidate: str) -> bool:
            return verified

        return artifact.verify(
            image,  # type: ignore[arg-type]
            FakeRegistry(refs),  # type: ignore[arg-type]
            verifier,
            env_file,
        )

    def test_a_verified_tag_is_written_as_image_at_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = str(Path(tmp) / "devcontainer" / ".env")
            got = self._verify({self.tag_ref: DIGEST}, env_file=env_file)
            self.assertEqual(got, f"{IMG}/tools@{DIGEST}")
            self.assertEqual(
                Path(env_file).read_text(),
                f"{artifact.DEVCONTAINER_ENV_VAR}={IMG}/tools@{DIGEST}\n",
            )

    def test_an_explicit_digest_is_verified_and_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = str(Path(tmp) / ".env")
            got = self._verify({}, image=f"{IMG}/tools@{DIGEST}", env_file=env_file)
            self.assertEqual(got, f"{IMG}/tools@{DIGEST}")
            self.assertEqual(
                Path(env_file).read_text(),
                f"{artifact.DEVCONTAINER_ENV_VAR}={IMG}/tools@{DIGEST}\n",
            )

    def test_a_refusal_removes_a_stale_env_file_and_names_the_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "devcontainer" / ".env"
            env_file.parent.mkdir()
            env_file.write_text(f"{artifact.DEVCONTAINER_ENV_VAR}={IMG}/tools@stale\n")
            with self.assertRaisesRegex(artifact.ArtifactError, f"{IMG}/tools@"):
                self._verify(
                    {self.tag_ref: DIGEST}, verified=False, env_file=str(env_file)
                )
            self.assertFalse(env_file.exists())

    def test_a_missing_image_removes_a_stale_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("stale\n")
            with self.assertRaisesRegex(artifact.ArtifactError, self.tag_ref):
                self._verify({}, env_file=str(env_file))
            self.assertFalse(env_file.exists())

    def test_a_refusal_without_env_file_just_raises(self) -> None:
        with self.assertRaisesRegex(artifact.ArtifactError, "attestation refused"):
            self._verify({self.tag_ref: DIGEST}, verified=False)

    def test_a_registry_error_removes_a_stale_env_file(self) -> None:
        class ProbeFails(artifact.Registry):
            def __init__(self) -> None:
                super().__init__(None)

            def digest(self, ref: str) -> str | None:
                raise artifact.ArtifactError(f"registry probe of {ref}: HTTP 502")

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("stale\n")
            with self.assertRaisesRegex(artifact.ArtifactError, "registry probe"):
                artifact.verify(
                    self.tag_ref, ProbeFails(), lambda _: True, str(env_file)
                )
            self.assertFalse(env_file.exists())


def publisher_names_scripts(text: str) -> list[str]:
    """Every names step of publish.yml (the image and the toolchain jobs), each between its
    BEGIN and END markers."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "# BEGIN names"]
    ends = [i for i, line in enumerate(lines) if line.strip() == "# END names"]
    assert starts and len(starts) == len(ends), (starts, ends)
    scripts = []
    for start, end in zip(starts, ends, strict=True):
        block = lines[start + 1 : end]
        indent = min(len(line) - len(line.lstrip()) for line in block if line.strip())
        scripts.append("\n".join(line[indent:] for line in block) + "\n")
    return scripts


def publisher_names_script(text: str) -> str:
    return publisher_names_scripts(text)[0]


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

    def test_every_names_step_is_the_same(self) -> None:
        scripts = publisher_names_scripts(PUBLISH.read_text())
        self.assertEqual(len(scripts), 2)
        self.assertEqual(len(set(scripts)), 1)

    def test_a_changed_publisher_name_is_caught(self) -> None:
        script = publisher_names_script(PUBLISH.read_text())
        mutated = script + 'echo "image=ghcr.io/somewhere/else" >> "$GITHUB_OUTPUT"\n'
        self.assertNotEqual(disagreements(mutated), [])


class FakeApi(artifact.Toolchains):
    """artifact.Toolchains over canned GitHub API answers (path prefix -> JSON, None for 404)."""

    def __init__(self, ref: str | None, answers: dict[str, object]) -> None:
        super().__init__(None, ref)
        self.answers = answers
        self.paths: list[str] = []

    def _get(self, path: str):  # type: ignore[override]
        self.paths.append(path)
        for prefix, answer in self.answers.items():
            if path.startswith(prefix):
                return answer
        return None


def ready_release(tag: str = TOOLCHAIN, **overrides: object) -> dict[str, object]:
    return {
        "draft": False,
        "name": tag,
        "assets": [{"name": f"{tag}.tar.zst"}],
    } | overrides


class ToolchainWait(unittest.TestCase):
    """artifact-check waits for a toolchain tag (#130): main's release, else in a pull-request or
    merge-queue run the builder's cache entry on the run's ref; never a cache entry elsewhere."""

    REL = f"repos/ray-manaloto/cpp-standard/releases/tags/{TOOLCHAIN}"
    CACHES = "repos/ray-manaloto/cpp-standard/actions/caches"
    REF = "refs/heads/gh-readonly-queue/main/pr-7-" + "a" * 40

    def test_release_counts(self) -> None:
        api = FakeApi(None, {self.REL: ready_release()})
        self.assertEqual(api.where(TOOLCHAIN), f"release {TOOLCHAIN}")

    def test_draft_release_does_not_count(self) -> None:
        self.assertIsNone(FakeApi(None, {self.REL: {"draft": True}}).where(TOOLCHAIN))

    def test_cache_entry_counts_on_the_run_ref(self) -> None:
        caches = {"actions_caches": [{"key": f"toolchain-{TOOLCHAIN}"}]}
        api = FakeApi(self.REF, {self.CACHES: caches})
        self.assertEqual(
            api.where(TOOLCHAIN), f"cache toolchain-{TOOLCHAIN} on {self.REF}"
        )
        self.assertIn("ref=refs%2Fheads%2Fgh-readonly-queue", api.paths[-1])

    def test_cache_entry_ignored_without_a_pr_ref(self) -> None:
        caches = {"actions_caches": [{"key": f"toolchain-{TOOLCHAIN}"}]}
        api = FakeApi(None, {self.CACHES: caches})
        self.assertIsNone(api.where(TOOLCHAIN))
        self.assertEqual(len(api.paths), 1)

    def test_candidates(self) -> None:
        self.assertEqual(
            artifact.candidates(TOOLCHAIN, None, False), [f"release {TOOLCHAIN}"]
        )
        self.assertEqual(
            artifact.candidates(TOOLCHAIN, 7, True),
            [f"release {TOOLCHAIN}", f"cache toolchain-{TOOLCHAIN}"],
        )

    def test_wait_finds_the_toolchain(self) -> None:
        api = FakeApi(None, {self.REL: ready_release()})
        missing = artifact.check(
            [TOOLCHAIN],
            FakeRegistry({}),
            None,
            False,
            0,
            1,
            log=lambda _: None,
            toolchains=api,
        )
        self.assertEqual(missing, [])

    def test_transient_api_errors_are_retried(self) -> None:
        answers = [
            urllib.error.HTTPError("u", 502, "bad gateway", {}, None),  # type: ignore[arg-type]
            urllib.error.URLError("reset"),
            io.BytesIO(json.dumps(ready_release()).encode()),
        ]

        def urlopen(req, timeout):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a

        with (
            unittest.mock.patch.object(artifact.urllib.request, "urlopen", urlopen),
            unittest.mock.patch.object(artifact.time, "sleep", lambda s: None),
        ):
            got = artifact.Toolchains(None, None).where(TOOLCHAIN)
        self.assertEqual(got, f"release {TOOLCHAIN}")

    def test_a_client_error_is_not_retried(self) -> None:
        def urlopen(req, timeout):
            raise urllib.error.HTTPError("u", 403, "forbidden", {}, None)  # type: ignore[arg-type]

        with (
            unittest.mock.patch.object(artifact.urllib.request, "urlopen", urlopen),
            self.assertRaises(artifact.ArtifactError),
        ):
            artifact.Toolchains(None, None).where(TOOLCHAIN)

    def test_absent_toolchain_times_out_as_missing(self) -> None:
        now = [0.0]
        clock = artifact.Clock(
            now=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)
        )
        api = FakeApi(self.REF, {})
        missing = artifact.check(
            [TOOLCHAIN],
            FakeRegistry({}),
            7,
            True,
            3,
            1,
            clock=clock,
            log=lambda _: None,
            toolchains=api,
        )
        self.assertEqual(missing, [TOOLCHAIN])
        self.assertGreater(len(api.paths), 2)  # it polled until the deadline

    def test_cache_entry_with_another_key_is_ignored(self) -> None:
        caches = {"actions_caches": [{"key": f"toolchain-{TOOLCHAIN}-other"}]}
        self.assertIsNone(FakeApi(self.REF, {self.CACHES: caches}).where(TOOLCHAIN))

    def test_wait_needs_a_lookup(self) -> None:
        with self.assertRaises(artifact.ArtifactError):
            artifact.check(
                [TOOLCHAIN], FakeRegistry({}), None, False, 0, 1, log=lambda _: None
            )

    def test_release_with_wrong_title_is_not_ready(self) -> None:
        bad = ready_release(name="wrong-title")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(FakeApi(None, {self.REL: bad}).where(TOOLCHAIN))
        self.assertIn("wrong-title", err.getvalue())
        self.assertIn(TOOLCHAIN, err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(FakeApi(self.REF, {self.REL: bad}).where(TOOLCHAIN))
            caches = {"actions_caches": [{"key": f"toolchain-{TOOLCHAIN}"}]}
            self.assertEqual(
                FakeApi(self.REF, {self.REL: bad, self.CACHES: caches}).where(
                    TOOLCHAIN
                ),
                f"cache toolchain-{TOOLCHAIN} on {self.REF}",
            )

    def test_release_without_archive_is_not_ready(self) -> None:
        for assets in ([{"name": "inputs-hash.txt"}], []):
            with self.subTest(assets=assets):
                bad = ready_release(assets=assets)
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertIsNone(FakeApi(None, {self.REL: bad}).where(TOOLCHAIN))
                self.assertIn(f"{TOOLCHAIN}.tar.zst", err.getvalue())
        caches = {"actions_caches": [{"key": f"toolchain-{TOOLCHAIN}"}]}
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                FakeApi(
                    self.REF, {self.REL: ready_release(assets=[]), self.CACHES: caches}
                ).where(TOOLCHAIN),
                f"cache toolchain-{TOOLCHAIN} on {self.REF}",
            )


def publisher_block(text: str, name: str) -> str:
    """The lines of publish.yml between `# BEGIN <name>` and `# END <name>`, dedented."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"# BEGIN {name}")
    end = next(i for i, line in enumerate(lines) if line.strip() == f"# END {name}")
    block = lines[start + 1 : end]
    indent = min(len(line) - len(line.lstrip()) for line in block if line.strip())
    return "\n".join(line[indent:] for line in block) + "\n"


def release(rid: int, tag: str, title: str, draft: bool) -> dict:
    return {"id": rid, "tag_name": tag, "name": title, "draft": draft}


class PublisherReleaseCheck(unittest.TestCase):
    """publish.yml's toolchain job decides, before any change, whether the release exists and
    which drafts are stale (#130 review): the exact shell block of the workflow, on fixture
    listings."""

    def check(self, listing: list[dict] | str) -> tuple[int, dict[str, str], str]:
        script = (
            publisher_block(PUBLISH.read_text(), "release-check")
            + 'echo "published=$published"\necho "drafts=$drafts"\n'
        )
        r = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            env={
                "PATH": os.environ["PATH"],
                "RELEASE": TOOLCHAIN,
                "GH_REPO": "ray-manaloto/cpp-standard",
                "listing": listing if isinstance(listing, str) else json.dumps(listing),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        out = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        return r.returncode, out, r.stdout + r.stderr

    def test_a_different_tag_draft_with_the_title_fails(self) -> None:
        rc, out, log = self.check([release(1, "other-tag", TOOLCHAIN, True)])
        self.assertEqual(rc, 1)
        self.assertNotIn("drafts", out)  # it stops before naming anything to delete
        self.assertIn("refused: releases of another tag", log)

    def test_a_different_tag_release_with_the_title_fails(self) -> None:
        rc, out, _ = self.check([release(1, "other-tag", TOOLCHAIN, False)])
        self.assertEqual(rc, 1)
        self.assertNotIn("published", out)

    def test_a_same_tag_draft_is_stale(self) -> None:
        rc, out, _ = self.check(
            [release(7, TOOLCHAIN, TOOLCHAIN, True), release(8, "x", "y", True)]
        )
        self.assertEqual((rc, out), (0, {"published": "false", "drafts": "7"}))

    def test_a_same_tag_release_is_published(self) -> None:
        rc, out, _ = self.check(
            [
                release(7, TOOLCHAIN, TOOLCHAIN, False),
                release(9, TOOLCHAIN, TOOLCHAIN, True),
            ]
        )
        self.assertEqual((rc, out), (0, {"published": "true", "drafts": ""}))

    def test_no_hits(self) -> None:
        rc, out, _ = self.check([release(1, "x", "y", False)])
        self.assertEqual((rc, out), (0, {"published": "false", "drafts": ""}))
        rc, out, _ = self.check([])
        self.assertEqual((rc, out), (0, {"published": "false", "drafts": ""}))

    def test_no_listing_fails_with_its_own_message(self) -> None:
        for listing in ("", "not json", '{"message": "Bad credentials"}'):
            with self.subTest(listing):
                rc, out, log = self.check(listing)
                self.assertEqual(rc, 1)
                self.assertEqual(out, {})
                self.assertIn("could not list the releases", log)

    def test_a_clash_fails_even_beside_the_own_release(self) -> None:
        rc, _, _ = self.check(
            [
                release(7, TOOLCHAIN, TOOLCHAIN, False),
                release(8, "decoy", TOOLCHAIN, True),
            ]
        )
        self.assertEqual(rc, 1)


def _strip_yaml_comment(value: str) -> str:
    quote: str | None = None
    for i, ch in enumerate(value):
        if quote is None and ch in ('"', "'"):
            quote = ch
        elif quote == ch:
            quote = None
        elif quote is None and ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value.strip()


def job_concurrency(text: str, job: str) -> dict[str, str]:
    """Read `jobs.<job>.concurrency` from a workflow YAML file with standard-library Python."""
    lines = text.splitlines()
    jobs_idx = next(i for i, line in enumerate(lines) if line.rstrip() == "jobs:")
    job_indent: int | None = None
    job_idx: int | None = None
    for i in range(jobs_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            break
        if job_indent is None:
            job_indent = indent
        if indent == job_indent and line.strip().split(":", 1)[0] == job:
            job_idx = i
            break
    assert job_idx is not None and job_indent is not None, f"job {job!r} not found"
    conc_idx: int | None = None
    conc_indent: int | None = None
    for i in range(job_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= job_indent:
            break
        if conc_indent is None:
            conc_indent = indent
        if indent == conc_indent and line.strip().split(":", 1)[0] == "concurrency":
            conc_idx = i
            break
    assert conc_idx is not None and conc_indent is not None, (
        f"concurrency not found in {job!r}"
    )
    out: dict[str, str] = {}
    for i in range(conc_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= conc_indent:
            break
        k, _, v = line.strip().partition(":")
        out[k.strip()] = _strip_yaml_comment(v)
    return out


class BuilderWorkflow(unittest.TestCase):
    def test_toolchain_concurrency_keeps_every_pending_run(self) -> None:
        conc = job_concurrency(BUILDER.read_text(), "toolchain")
        self.assertEqual(conc.get("group"), "builder-${{ needs.tags.outputs.p2996 }}")
        self.assertEqual(conc.get("cancel-in-progress"), "false")
        self.assertEqual(conc.get("queue"), "max")


if __name__ == "__main__":
    unittest.main(verbosity=2)
