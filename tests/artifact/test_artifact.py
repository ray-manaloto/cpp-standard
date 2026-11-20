"""Tests of python/artifact/artifact.py: the three `artifact-check` cases, the four `resolve`
cases, image:verify's devcontainer env file, and the agreement of publish.yml's inline names with
`artifact:names` (environment-standard.md file plan; spec #122 Testing Decisions). The registry,
the clock and the verifier are fakes, so nothing here needs the network, Docker or GitHub. Run:
python3 -I tests/artifact/test_artifact.py
"""

from __future__ import annotations

import contextlib
import http.client
import io
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
    def test_toolchain_uses_its_full_tag_in_the_tools_package(self) -> None:
        names = artifact.names(TOOLCHAIN)
        self.assertEqual(names["image"], artifact.names(TOOLS)["image"])
        self.assertEqual(names["image_tag"], TOOLCHAIN)
        self.assertEqual(names["ref"], f"{names['image']}:{TOOLCHAIN}")

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
    """The real source selection with fake registry and Actions cache responses."""

    def __init__(self, ref: str | None, digest: str | None, keys: list[str]) -> None:
        super().__init__(None, ref)
        self.registry = FakeRegistry({TOOLCHAIN_REF: digest} if digest else {})  # type: ignore[assignment]
        self.keys = keys
        self.paths: list[str] = []

    def _get(self, path: str) -> dict:
        self.paths.append(path)
        return {"actions_caches": [{"key": key} for key in self.keys]}


TOOLCHAIN_REF = artifact.names(TOOLCHAIN)["ref"]
CACHE_KEY = f"toolchain-{TOOLCHAIN}"


class ToolchainWait(unittest.TestCase):
    REF = "refs/heads/gh-readonly-queue/main/pr-7-" + "a" * 40

    def test_registry_takes_precedence(self) -> None:
        api = FakeApi(self.REF, DIGEST, [CACHE_KEY])
        self.assertEqual(
            api.where(TOOLCHAIN),
            artifact.Found(f"image {TOOLCHAIN_REF}@{DIGEST}", DIGEST),
        )
        self.assertEqual(api.paths, [])

    def test_cache_counts_on_the_run_ref(self) -> None:
        api = FakeApi(self.REF, None, [CACHE_KEY])
        self.assertEqual(
            api.where(TOOLCHAIN), artifact.Found(f"cache {CACHE_KEY} on {self.REF}")
        )
        self.assertIn(f"key={CACHE_KEY}", api.paths[-1])
        self.assertIn("ref=refs%2Fheads%2Fgh-readonly-queue", api.paths[-1])

    def test_cache_ignored_without_a_pr_ref(self) -> None:
        api = FakeApi(None, None, [CACHE_KEY])
        self.assertIsNone(api.where(TOOLCHAIN))
        self.assertEqual(api.paths, [])

    def test_wrong_cache_key_is_ignored(self) -> None:
        self.assertIsNone(
            FakeApi(self.REF, None, [CACHE_KEY + "-older"]).where(TOOLCHAIN)
        )

    def test_candidates(self) -> None:
        self.assertEqual(artifact.candidates(TOOLCHAIN, None, False), [TOOLCHAIN_REF])
        self.assertEqual(
            artifact.candidates(TOOLCHAIN, 7, True),
            [TOOLCHAIN_REF, f"cache {CACHE_KEY}"],
        )

    def test_wait_finds_the_toolchain(self) -> None:
        self.assertEqual(
            artifact.check(
                [TOOLCHAIN],
                FakeRegistry({}),
                None,
                False,
                10,
                1,
                toolchains=FakeApi(None, DIGEST, []),
            ),
            [],
        )

    def test_absent_toolchain_times_out_as_missing(self) -> None:
        clock = FakeClock()
        api = FakeApi(self.REF, None, [])
        self.assertEqual(
            artifact.check(
                [TOOLCHAIN],
                FakeRegistry({}),
                7,
                True,
                5,
                1,
                artifact.Clock(clock.now, clock.sleep),
                toolchains=api,
            ),
            [TOOLCHAIN],
        )
        self.assertGreater(len(api.paths), 2)

    def test_wait_needs_a_lookup(self) -> None:
        with self.assertRaises(artifact.ArtifactError):
            artifact.check([TOOLCHAIN], FakeRegistry({}), None, False, 10, 1)


def response(payload: bytes = b"", **headers: str) -> unittest.mock.MagicMock:
    reply = unittest.mock.MagicMock()
    reply.__enter__.return_value = reply
    reply.read.return_value = payload
    reply.headers = headers
    return reply


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://ghcr.io", code, "registry answer", {}, io.BytesIO()
    )


class RegistryProbe(unittest.TestCase):
    def setUp(self) -> None:
        self.bearer = response(b'{"token":"stand-in"}')

    def test_builder_probe_fails_on_authentication_error(self) -> None:
        env = {"GITHUB_EVENT_NAME": "push", "GH_TOKEN": "stand-in"}
        errors = [self.bearer, http_error(401), self.bearer, http_error(401)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            unittest.mock.patch.dict(os.environ, env, clear=True),
            unittest.mock.patch.object(
                artifact.urllib.request, "urlopen", side_effect=errors
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            rc = artifact.main(["probe", TOOLCHAIN])
        self.assertEqual(rc, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("HTTP 401", stderr.getvalue())

    def test_manifest_miss_allows_build(self) -> None:
        with unittest.mock.patch.object(
            artifact.urllib.request,
            "urlopen",
            side_effect=[self.bearer, http_error(404)],
        ):
            self.assertIsNone(artifact.Registry(None).digest(TOOLCHAIN_REF))

    def test_bearer_404_is_a_failure(self) -> None:
        with (
            unittest.mock.patch.object(
                artifact.urllib.request, "urlopen", side_effect=http_error(404)
            ),
            self.assertRaisesRegex(artifact.ArtifactError, "token request.*HTTP 404"),
        ):
            artifact.Registry(None).digest(TOOLCHAIN_REF)

    def test_missing_digest_is_a_failure(self) -> None:
        with (
            unittest.mock.patch.object(
                artifact.urllib.request,
                "urlopen",
                side_effect=[self.bearer, response()],
            ),
            self.assertRaisesRegex(artifact.ArtifactError, "invalid digest"),
        ):
            artifact.Registry(None).digest(TOOLCHAIN_REF)

    def test_probe_retries_transient_server_error(self) -> None:
        good = response(**{"Docker-Content-Digest": DIGEST})
        with (
            unittest.mock.patch.object(
                artifact.urllib.request,
                "urlopen",
                side_effect=[self.bearer, http_error(500), good],
            ),
            unittest.mock.patch.object(artifact.time, "sleep"),
        ):
            self.assertEqual(artifact.Registry(None).digest(TOOLCHAIN_REF), DIGEST)

    def test_token_request_retries_transient_server_error(self) -> None:
        good = response(**{"Docker-Content-Digest": DIGEST})
        with (
            unittest.mock.patch.object(
                artifact.urllib.request,
                "urlopen",
                side_effect=[http_error(500), self.bearer, good],
            ),
            unittest.mock.patch.object(artifact.time, "sleep") as sleep,
        ):
            self.assertEqual(artifact.Registry(None).digest(TOOLCHAIN_REF), DIGEST)
        sleep.assert_called_once_with(5)

    def test_raw_manifest_bytes_are_preserved(self) -> None:
        raw = b'{ "schemaVersion": 2 }\n'
        with unittest.mock.patch.object(
            artifact.urllib.request, "urlopen", side_effect=[self.bearer, response(raw)]
        ):
            self.assertEqual(artifact.Registry(None).manifest_bytes(TOOLCHAIN_REF), raw)

    def test_interrupted_manifest_read_is_a_registry_error(self) -> None:
        broken = unittest.mock.MagicMock()
        broken.__enter__.return_value.read.side_effect = http.client.IncompleteRead(
            b"partial"
        )
        registry = artifact.Registry(None)
        with (
            unittest.mock.patch.object(registry, "RETRIES", 0),
            unittest.mock.patch.object(
                artifact.urllib.request,
                "urlopen",
                side_effect=[self.bearer, broken],
            ),
            self.assertRaisesRegex(
                artifact.ArtifactError, "registry pull.*IncompleteRead"
            ),
        ):
            registry.manifest_bytes(TOOLCHAIN_REF)

    def test_blob_uses_the_digest_url_and_does_not_forward_credentials(self) -> None:
        pinned = f"{artifact.names(TOOLCHAIN)['image']}@{DIGEST}"
        dest = Path(self.enterContext(tempfile.TemporaryDirectory())) / "blob"
        with unittest.mock.patch.object(
            artifact.urllib.request,
            "urlopen",
            side_effect=[self.bearer, io.BytesIO(b"layer bytes")],
        ) as urlopen:
            self.assertEqual(artifact.Registry(None).blob(pinned, DIGEST, dest), dest)
        self.assertEqual(dest.read_bytes(), b"layer bytes")
        req = urlopen.call_args.args[0]
        self.assertTrue(req.full_url.endswith(f"/tools/blobs/{DIGEST}"))
        self.assertEqual(req.get_header("Authorization"), "Bearer stand-in")
        redirect = urllib.request.HTTPRedirectHandler().redirect_request(
            req, None, 307, "Temporary Redirect", {}, "https://storage.example/blob"
        )
        self.assertIsNone(redirect.get_header("Authorization"))


class PublisherToolchain(unittest.TestCase):
    QUOTED_MANIFEST_UNKNOWN = (
        'time="2026-11-20T03:31:07Z" level=fatal msg="Error parsing image name '
        '\\"docker://ghcr.io/ray-manaloto/cpp-standard/tools:'
        'p2996-linux-arm64-2842aa720aeefb6e\\": reading manifest '
        "p2996-linux-arm64-2842aa720aeefb6e in "
        'ghcr.io/ray-manaloto/cpp-standard/tools: manifest unknown"'
    )

    def run_push(
        self, error: str, marker: str = "toolchain-push"
    ) -> tuple[subprocess.CompletedProcess, str]:
        text = PUBLISH.read_text()
        script = text.split(f"# BEGIN {marker}\n", 1)[1].split(f"# END {marker}", 1)[0]
        fake = """skopeo() {
          case "$1" in
            inspect) printf '%s\n' "$PROBE_ERROR" >&2; return 1 ;;
            copy) printf '%s\n' "$*" >copy.log ;;
            *) return 1 ;;
          esac
        }
        """
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", fake + script],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
                env={
                    "PATH": os.environ["PATH"],
                    "DIGEST": DIGEST,
                    "DIR": "dist",
                    "IMAGE": TOOLCHAIN_REF.rsplit(":", 1)[0],
                    "REF": TOOLCHAIN_REF,
                    "PROBE_ERROR": error,
                },
            )
            copy = Path(directory, "copy.log")
            return result, copy.read_text() if copy.exists() else ""

    def test_push_probe_refuses_auth_failure(self) -> None:
        result, copied = self.run_push(
            "reading manifest: unauthorized: credentials not found"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("probing", result.stdout)
        self.assertEqual(copied, "")

    def test_manifest_unknown_uploads_by_digest(self) -> None:
        result, copied = self.run_push(
            "reading manifest: manifest unknown: manifest unknown"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"docker://{TOOLCHAIN_REF.rsplit(':', 1)[0]}@{DIGEST}", copied)
        self.assertNotIn(f"docker://{TOOLCHAIN_REF}", copied)

    def test_quoted_manifest_unknown_uploads_by_digest(self) -> None:
        result, copied = self.run_push(self.QUOTED_MANIFEST_UNKNOWN)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"docker://{TOOLCHAIN_REF.rsplit(':', 1)[0]}@{DIGEST}", copied)
        self.assertNotIn(f"docker://{TOOLCHAIN_REF}", copied)

    def test_quoted_manifest_unknown_publishes_attested_tag(self) -> None:
        result, copied = self.run_push(
            self.QUOTED_MANIFEST_UNKNOWN, marker="toolchain-tag"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            copied.strip(),
            f"copy --preserve-digests docker://{TOOLCHAIN_REF.rsplit(':', 1)[0]}@{DIGEST} "
            f"docker://{TOOLCHAIN_REF}",
        )

    def test_quoted_auth_failure_refused_in_push_and_tag(self) -> None:
        auth_err = (
            'time="2026-11-20T03:31:07Z" level=fatal msg="Error parsing image name '
            '\\"docker://ghcr.io/ray-manaloto/cpp-standard/tools:tag\\": '
            'unauthorized: authentication required"'
        )
        for marker in ("toolchain-push", "toolchain-tag"):
            result, copied = self.run_push(auth_err, marker=marker)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("probing", result.stdout)
            self.assertEqual(copied, "")


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


def pull_request_paths(text: str) -> list[str]:
    """Read `on.pull_request.paths` from a workflow YAML file with standard-library Python."""
    lines = text.splitlines()
    on_idx = next(i for i, line in enumerate(lines) if line.rstrip() == "on:")
    pr_idx = next(
        i
        for i in range(on_idx + 1, len(lines))
        if lines[i].strip().split(":", 1)[0] == "pull_request"
    )
    pr_indent = len(lines[pr_idx]) - len(lines[pr_idx].lstrip())
    paths_idx = next(
        i
        for i in range(pr_idx + 1, len(lines))
        if len(lines[i]) - len(lines[i].lstrip()) > pr_indent
        and lines[i].strip().split(":", 1)[0] == "paths"
    )
    paths_indent = len(lines[paths_idx]) - len(lines[paths_idx].lstrip())
    out: list[str] = []
    for i in range(paths_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= paths_indent:
            break
        item = line.strip()
        assert item.startswith("- "), f"expected list item, got {line!r}"
        out.append(_strip_yaml_comment(item[2:]))
    return out


class BuilderWorkflow(unittest.TestCase):
    def test_toolchain_concurrency_keeps_every_pending_run(self) -> None:
        conc = job_concurrency(BUILDER.read_text(), "toolchain")
        self.assertEqual(conc.get("group"), "builder-${{ needs.tags.outputs.p2996 }}")
        self.assertEqual(conc.get("cancel-in-progress"), "false")
        self.assertEqual(conc.get("queue"), "max")

    def test_pull_request_paths_include_builder_and_publish_workflows(self) -> None:
        paths = pull_request_paths(BUILDER.read_text())
        self.assertIn(".github/workflows/builder.yml", paths)
        self.assertIn(".github/workflows/publish.yml", paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
