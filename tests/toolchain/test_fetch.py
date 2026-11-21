"""Tests of python/toolchain/fetch.py (tickets #130 and #254): each row of the source table, the
staged copy refused on main and outside Actions, image-only mode, the waiting job that never
builds, the registry probe rule, and the install that never lets a refused archive in. The
verifier and the rebuild are fakes, and the image cases run the real pack-to-fetch round trip
over a fake registry with images from python/artifact/oci.py, so nothing here needs the
network, gh or a real toolchain. Run: python3 -I tests/toolchain/test_fetch.py
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/toolchain"))
sys.path.insert(0, str(ROOT / "python/artifact"))

import artifact
import fetch
import oci

TAG = "p2996-linux-arm64-00112233445566aa"
HASH = "00112233445566aa"
# The public tools package holds the full tag (D98, #254), not an <os>-<arch>-<hash> one.
IMAGE_REF = artifact.names(TAG)["ref"]
DIGEST = "sha256:" + "c" * 64
SUBJECT = f"oci://{IMAGE_REF.rpartition(':')[0]}@{DIGEST}"
HOSTED = {"RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_ACTIONS": "true"}


def make_archive(
    path: Path, content: str, inputs_hash: str | bytes | None = HASH
) -> Path:
    """A stand-in toolchain archive: bin/marker holds `content`."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "bin").mkdir()
        (Path(d) / "bin/marker").write_text(content)
        if isinstance(inputs_hash, bytes):
            (Path(d) / fetch.HASH_FILE).write_bytes(inputs_hash)
        elif inputs_hash is not None:
            (Path(d) / fetch.HASH_FILE).write_text(inputs_hash + "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "--zstd", "-cf", str(path), "-C", d, "."], check=True)
    return path


def sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def recording(seen: list[str]) -> Callable[[str], bool]:
    def check(subject: str) -> bool:
        # A verifier that records every subject it is asked about and passes it.
        seen.append(subject)
        return True

    return check


class PackedImage:
    """The pieces of one toolchain image that the fetch pulls: the manifest bytes, the manifest
    digest the probe answers, and the one layer's descriptor and blob. `packed` runs the real
    packer (python/artifact/oci.py); `of_layer` and `hand_packed` build the images the packer
    refuses, for the refusal cases."""

    def __init__(
        self,
        manifest_digest: str,
        manifest_bytes: bytes,
        layer: dict,
        layer_bytes: bytes,
    ) -> None:
        self.manifest_digest = manifest_digest
        self.manifest_bytes = manifest_bytes
        self.layer = layer  # the descriptor the fetch must check the blob against
        self.layer_bytes = layer_bytes

    @classmethod
    def packed(cls, files: dict[str, bytes]) -> PackedImage:
        """A real image: oci.pack over `files`, then the manifest and layer read back."""
        with tempfile.TemporaryDirectory() as d:
            inputs = []
            for name, data in files.items():
                path = Path(d) / name
                path.write_bytes(data)
                inputs.append((name, path))
            image = Path(d) / "image.tar"
            digest = oci.pack(image, inputs, "arm64", "linux")
            with tarfile.open(image) as f:
                raw = f.extractfile(f"blobs/{digest.replace(':', '/')}").read()
                manifest = json.loads(raw)
                blob = f.extractfile(
                    f"blobs/{manifest['layers'][0]['digest'].replace(':', '/')}"
                ).read()
        return cls(digest, raw, manifest["layers"][0], blob)

    @classmethod
    def of_layer(cls, layer_bytes: bytes) -> PackedImage:
        """A manifest built around a layer blob the way the packer builds one, with a config
        the fetch never reads."""
        layer = {
            "mediaType": oci.LAYER_MEDIA_TYPE,
            "digest": sha256(layer_bytes),
            "size": len(layer_bytes),
        }
        config = json.dumps(
            {
                "architecture": "arm64",
                "os": "linux",
                "config": {},
                "rootfs": {"type": "layers", "diff_ids": [sha256(layer_bytes)]},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        manifest = {
            "schemaVersion": 2,
            "mediaType": oci.MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": oci.CONFIG_MEDIA_TYPE,
                "digest": sha256(config),
                "size": len(config),
            },
            "layers": [layer],
        }
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        return cls(sha256(raw), raw, layer, layer_bytes)

    @classmethod
    def hand_packed(cls, members: list[tuple]) -> PackedImage:
        """A gzip tar written member by member, for archives the packer refuses: two members of
        one name, or a non-regular member where the archive should be. Each member is
        (name, bytes), or (name, bytes, tarfile type, linkname) for a non-regular one."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as f:
            for name, data, *rest in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                if rest:
                    info.type = rest[0]
                if len(rest) > 1:
                    info.linkname = rest[1]
                f.addfile(info, io.BytesIO(data))
        return cls.of_layer(gzip.compress(buf.getvalue(), mtime=0))

    def retag(self) -> None:
        """Re-canonicalize the manifest bytes after a test edits the layer descriptor, and make
        the probe answer the new digest, as a publisher of that manifest would."""
        manifest = json.loads(self.manifest_bytes)
        manifest["layers"] = [self.layer]
        self.manifest_bytes = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode()
        self.manifest_digest = sha256(self.manifest_bytes)


class FakeImages:
    """The image store: one image of TAG when `archive` is given; `error` makes find raise."""

    def __init__(self, archive: Path | None = None, error: Exception | None = None):
        self.archive = archive
        self.error = error

    def find(self, tag: str) -> fetch.Image | None:
        if self.error is not None:
            raise self.error
        if self.archive is None:
            return None
        return fetch.Image(IMAGE_REF, DIGEST)

    def download(self, image: fetch.Image, tag: str, dest: Path) -> Path:
        path = dest / f"{tag}.tar.zst"
        assert self.archive is not None
        path.write_bytes(self.archive.read_bytes())
        return path


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "installed"
        self.staged = self.tmp / "staged"
        self.rebuilt = 0
        self.log: list[str] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def rebuild_ok(self, tag: str) -> Path:
        self.rebuilt += 1
        return make_archive(self.tmp / "dist" / f"{tag}.tar.zst", "rebuilt")

    def rebuild_fails(self, tag: str) -> Path:
        self.rebuilt += 1
        raise subprocess.CalledProcessError(1, ["artifact:build", tag])

    def stage(self, content: str = "staged") -> None:
        make_archive(self.staged / TAG / f"{TAG}.tar.zst", content)

    def run_fetch(self, ctx: str, images, verifier=lambda _: True, builder=None, **kw):
        order = fetch.sources(fetch.Context(ctx), **kw)
        return fetch.fetch(
            TAG,
            self.root,
            order,
            images,
            verifier,
            builder or self.rebuild_ok,
            self.staged,
            self.log.append,
        )

    def installed(self) -> str | None:
        marker = self.root / TAG / "bin/marker"
        return marker.read_text() if marker.exists() else None


class ContextTest(unittest.TestCase):
    def test_contexts(self) -> None:
        C = fetch.Context.from_env
        self.assertEqual(C({}).kind, "outside")
        pr = HOSTED | {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/7/merge",
        }
        self.assertEqual(C(pr).kind, "hosted_pr")
        mq = HOSTED | {
            "GITHUB_EVENT_NAME": "merge_group",
            "GITHUB_REF": "refs/heads/gh-readonly-queue/main/pr-7-" + "a" * 40,
        }
        self.assertEqual(C(mq).kind, "hosted_pr")
        for event in ("push", "workflow_dispatch", "schedule"):
            env = HOSTED | {"GITHUB_EVENT_NAME": event, "GITHUB_REF": "refs/heads/main"}
            self.assertEqual(C(env).kind, "actions", event)
        self.assertEqual(C(pr | {"RUNNER_ENVIRONMENT": "self-hosted"}).kind, "actions")
        # The name ci.yml sets; the runner's own RUNNER_ENVIRONMENT may be absent in a container.
        pr_ours = {k: v for k, v in pr.items() if k != "RUNNER_ENVIRONMENT"}
        self.assertEqual(C(pr_ours).kind, "actions")
        ours = pr_ours | {"CPPSTD_RUNNER_ENVIRONMENT": "github-hosted"}
        self.assertEqual(C(ours).kind, "hosted_pr")

    def test_source_table(self) -> None:
        S = fetch.sources
        self.assertEqual(S(fetch.Context("hosted_pr")), ["image", "staged", "rebuild"])
        self.assertEqual(S(fetch.Context("actions")), ["image", "rebuild"])
        self.assertEqual(S(fetch.Context("outside")), ["image", "rebuild"])
        for kind in ("hosted_pr", "actions", "outside"):
            self.assertEqual(S(fetch.Context(kind), release_only=True), ["image"])
        self.assertEqual(
            S(fetch.Context("hosted_pr"), rebuild=False), ["image", "staged"]
        )


class RowTest(Case):
    """One test per row of the source table, and the staged copy refused on main and outside."""

    def test_pr_row_image_first(self) -> None:
        self.stage()
        img = FakeImages(make_archive(self.tmp / "r.tar.zst", "image"))
        r = self.run_fetch("hosted_pr", img)
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("image", "image", 0)
        )

    def test_pr_row_staged_before_rebuild(self) -> None:
        self.stage()
        r = self.run_fetch("hosted_pr", FakeImages(None))
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("staged", "staged", 0)
        )

    def test_pr_row_rebuild_last(self) -> None:
        r = self.run_fetch("hosted_pr", FakeImages(None))
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("rebuild", "rebuilt", 1)
        )

    def test_main_and_outside_never_take_a_staged_copy(self) -> None:
        for ctx in ("actions", "outside"):
            with self.subTest(ctx):
                self.stage()
                r = self.run_fetch(ctx, FakeImages(None))
                self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))

    def test_main_and_outside_take_the_image(self) -> None:
        img = FakeImages(make_archive(self.tmp / "r.tar.zst", "image"))
        subjects: list[str] = []
        for ctx in ("actions", "outside"):
            with self.subTest(ctx):
                self.root = self.tmp / f"installed-{ctx}"  # a fresh install root each
                r = self.run_fetch(ctx, img, verifier=recording(subjects))
                self.assertEqual((r.source, self.installed()), ("image", "image"))
        self.assertEqual(self.rebuilt, 0)
        # The verifier is asked about the image at its digest, not about a file.
        self.assertEqual(subjects, [SUBJECT, SUBJECT])

    def test_staged_copy_with_wrong_hash_is_refused(self) -> None:
        make_archive(
            self.staged / TAG / f"{TAG}.tar.zst", "staged", inputs_hash="f" * 16
        )
        r = self.run_fetch("hosted_pr", FakeImages(None))
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("inputs-hash.txt", r.refusals[0])


class ReleaseOnlyTest(Case):
    def test_release_only_installs_the_image(self) -> None:
        self.stage()
        img = FakeImages(make_archive(self.tmp / "r.tar.zst", "image"))
        r = self.run_fetch("actions", img, release_only=True)
        self.assertEqual((r.source, self.installed()), ("image", "image"))

    def test_release_only_never_falls_back(self) -> None:
        self.stage()
        r = self.run_fetch("hosted_pr", FakeImages(None), release_only=True)
        self.assertIsNone(r.prefix)
        self.assertEqual((self.installed(), self.rebuilt), (None, 0))

    def test_hosted_release_only_refusals_keep_the_same_install(self) -> None:
        good = FakeImages(make_archive(self.tmp / "good.tar.zst", "baseline"))
        initial = self.run_fetch("actions", good, release_only=True)
        self.assertEqual(initial.source, "image")
        active = self.root / TAG
        target = active.readlink()
        self.stage("must never be selected")
        for verified, payload_hash, reason in (
            (False, HASH, "attestation"),
            (True, "badbadbadbadbad0", "inputs-hash.txt"),
        ):
            with self.subTest(verified=verified):
                rejected = FakeImages(
                    make_archive(self.tmp / "bad.tar.zst", "bad", payload_hash)
                )
                check = mock.Mock(return_value=verified)
                with mock.patch.object(
                    rejected, "download", wraps=rejected.download
                ) as pull:
                    result = self.run_fetch(
                        "actions", rejected, verifier=check, release_only=True
                    )
                check.assert_called_once_with(SUBJECT)
                self.assertEqual(pull.call_count, int(verified))
                self.assertIsNone(result.prefix)
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.refusals), 1)
                self.assertIn(reason, result.refusals[0])
                self.assertEqual(active.readlink(), target)
                self.assertEqual(self.installed(), "baseline")
                self.assertEqual(self.rebuilt, 0)


class WaitTest(Case):
    """A job that waits for the staged copy fails when the wait ends without one and never
    builds: artifact-check's wait for the toolchain tag ends missing, and the job's fetch, which
    runs with the rebuild off, installs nothing."""

    def test_short_wait_then_no_build(self) -> None:
        now = [0.0]
        clock = artifact.Clock(
            now=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)
        )

        class Nothing:
            def digest(self, _ref: str) -> None:
                return None

            def where(self, _tag: str) -> None:
                return None

        missing = artifact.check(
            [TAG],
            Nothing(),
            7,
            True,
            timeout=3,
            interval=1,
            clock=clock,
            log=self.log.append,
            toolchains=Nothing(),
        )
        self.assertEqual(missing, [TAG])
        r = self.run_fetch("hosted_pr", FakeImages(None), rebuild=False)
        self.assertIsNone(r.prefix)
        self.assertEqual(self.rebuilt, 0)


class RefusalTest(Case):
    """The refusal cases of spec #122's table, on the code path used outside Actions."""

    def test_unattested_image_then_rebuild_installs_the_rebuilt_one(self) -> None:
        make_archive(self.root / "seed.tar.zst", "before")
        fetch.install(self.root / "seed.tar.zst", TAG, self.root)
        img = FakeImages(make_archive(self.tmp / "r.tar.zst", "refused"))
        r = self.run_fetch("outside", img, verifier=lambda _: False)
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("attestation", r.refusals[0])

    def test_unattested_image_and_no_rebuild_leaves_the_old_one(self) -> None:
        make_archive(self.root / "seed.tar.zst", "before")
        fetch.install(self.root / "seed.tar.zst", TAG, self.root)
        img = FakeImages(make_archive(self.tmp / "r.tar.zst", "refused"))
        r = self.run_fetch(
            "outside", img, verifier=lambda _: False, builder=self.rebuild_fails
        )
        self.assertIsNone(r.prefix)
        self.assertEqual((self.installed(), self.rebuilt), ("before", 1))

    def test_attested_image_with_wrong_inputs_hash_is_refused(self) -> None:
        img = FakeImages(
            make_archive(self.tmp / "r.tar.zst", "wrong", inputs_hash="e" * 16)
        )
        r = self.run_fetch("outside", img)
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("inputs-hash.txt", r.refusals[0])

    def test_archive_without_inputs_hash_is_refused(self) -> None:
        img = FakeImages(make_archive(self.tmp / "r.tar.zst", "none", inputs_hash=None))
        r = self.run_fetch("outside", img, release_only=True)
        self.assertIsNone(r.prefix)
        self.assertIsNone(self.installed())

    def test_corrupt_archive_is_refused(self) -> None:
        bad = self.tmp / "r.tar.zst"
        bad.write_bytes(b"not an archive")
        r = self.run_fetch("outside", FakeImages(bad), release_only=True)
        self.assertIsNone(r.prefix)
        self.assertIn("does not extract", r.refusals[0])

    def test_invalid_utf8_inputs_hash_is_refused_and_falls_back(self) -> None:
        self.stage()
        img = FakeImages(
            make_archive(self.tmp / "r.tar.zst", "bad-utf8", inputs_hash=b"\xff\xfe\n")
        )
        r = self.run_fetch("hosted_pr", img)
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("staged", "staged", 0)
        )
        self.assertEqual(len(r.refusals), 1)
        self.assertIn("inputs-hash.txt", r.refusals[0])
        self.assertIn("UTF-8", r.refusals[0])


_UNSET = object()


class FakeRegistry:
    """artifact.Registry over one PackedImage: `digest` probes the manifest digest,
    `manifest_bytes` serves the manifest bytes and `blob` streams the layer bytes to `dest`.
    Tests break a request (probe_error, manifest_error, blob_error), replace the manifest
    answer (manifest_answer), or corrupt the image, for the refusal and error cases."""

    def __init__(self, image: PackedImage | None = None) -> None:
        self.image = image
        self.probe_error: Exception | None = None
        self.manifest_error: Exception | None = None
        self.blob_error: Exception | None = None
        self.manifest_answer: object = _UNSET
        self.probed: list[str] = []
        self.manifest_of: list[str] = []
        self.blob_of: list[str] = []

    def digest(self, ref: str) -> str | None:
        self.probed.append(ref)
        if self.probe_error is not None:
            raise self.probe_error
        return self.image.manifest_digest if self.image else None

    def manifest_bytes(self, ref: str) -> bytes | None:
        self.manifest_of.append(ref)
        if self.manifest_error is not None:
            raise self.manifest_error
        if self.manifest_answer is not _UNSET:
            return self.manifest_answer  # type: ignore[return-value]
        return self.image.manifest_bytes if self.image else None

    def blob(self, ref: str, digest: str, dest: Path) -> Path:
        self.blob_of.append(digest)
        if self.blob_error is not None:
            raise self.blob_error
        if self.image is None or digest != self.image.layer["digest"]:
            raise artifact.ArtifactError(f"registry pull of {ref}: no blob {digest}")
        dest.write_bytes(self.image.layer_bytes)
        return dest


class RegistryImageTest(Case):
    """GhImage over a fake registry serving real images from python/artifact/oci.py: the
    probe rule, the digest-pinned pack-to-fetch round trip, and every check that refuses a
    bad one (#254)."""

    def store(self, reg: FakeRegistry) -> fetch.GhImage:
        return fetch.GhImage(reg)  # type: ignore[arg-type]

    def at_digest(self, image: PackedImage) -> str:
        return f"{IMAGE_REF.rpartition(':')[0]}@{image.manifest_digest}"

    def pull(self, image: PackedImage, reg: FakeRegistry | None = None) -> Path:
        """download() into a scratch `pull` directory of this test's tree."""
        dest = self.tmp / "pull"
        dest.mkdir(exist_ok=True)
        reg = reg or FakeRegistry(image)
        return self.store(reg).download(
            fetch.Image(IMAGE_REF, image.manifest_digest), TAG, dest
        )

    def serve_manifest(self, image: PackedImage, raw: bytes) -> Path:
        """download() with the registry serving `raw` as the manifest, self-consistently:
        the probe answers sha256(raw), so the raw-digest check passes and parsing runs."""
        image.manifest_digest = sha256(raw)
        reg = FakeRegistry(image)
        reg.manifest_answer = raw
        return self.pull(image, reg)

    def test_find_probes_the_names_ref(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        reg = FakeRegistry(image)
        found = self.store(reg).find(TAG)
        self.assertEqual(reg.probed, [IMAGE_REF])
        self.assertEqual(found, fetch.Image(IMAGE_REF, image.manifest_digest))

    def test_find_none_when_absent(self) -> None:
        self.assertIsNone(self.store(FakeRegistry()).find(TAG))

    def test_find_never_reads_an_error_as_absent(self) -> None:
        # The faked authentication error: a probe answer other than "not found" is an error,
        # never a "does not exist" (the issue's guard).
        reg = FakeRegistry()
        reg.probe_error = artifact.ArtifactError("registry probe of x: HTTP 401")
        with self.assertRaisesRegex(fetch.SourceError, "HTTP 401"):
            self.store(reg).find(TAG)

    def test_round_trip_from_the_real_packer(self) -> None:
        """The packer's image through the whole fetch: probed by tag, attested at its digest,
        pulled by digest, the layer checked while streaming, and the archive installed with
        its inputs hash before the prefix is switched (D180, D131)."""
        content = make_archive(self.tmp / "packed.tar.zst", "packed")
        payload = content.read_bytes()
        image = PackedImage.packed(
            {f"{TAG}.tar.zst": payload, fetch.HASH_FILE: f"{HASH}\n".encode()}
        )
        reg = FakeRegistry(image)
        subjects: list[str] = []
        r = self.run_fetch("outside", self.store(reg), verifier=recording(subjects))
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("image", "packed", 0)
        )
        self.assertEqual((self.root / TAG / fetch.HASH_FILE).read_text().strip(), HASH)
        self.assertEqual(subjects, [f"oci://{self.at_digest(image)}"])
        self.assertEqual(reg.manifest_of, [self.at_digest(image)])
        self.assertEqual(reg.blob_of, [image.layer["digest"]])

    def test_download_pulls_the_probed_digest(self) -> None:
        content = make_archive(self.tmp / "a.tar.zst", "pulled")
        image = PackedImage.packed({f"{TAG}.tar.zst": content.read_bytes()})
        reg = FakeRegistry(image)
        got = self.pull(image, reg)
        self.assertEqual(got, self.tmp / "pull" / f"{TAG}.tar.zst")
        self.assertEqual(got.read_bytes(), content.read_bytes())
        self.assertEqual(reg.manifest_of, [self.at_digest(image)])
        self.assertEqual(reg.blob_of, [image.layer["digest"]])

    def test_manifest_bytes_with_a_wrong_digest_are_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        reg = FakeRegistry(image)
        reg.manifest_answer = json.dumps(
            {"schemaVersion": 2}, separators=(",", ":")
        ).encode()
        with self.assertRaisesRegex(fetch.Refused, "the probe saw"):
            self.pull(image, reg)
        self.assertEqual(reg.blob_of, [])  # refused before anything else was pulled

    def test_malformed_manifest_is_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        for name, raw in (
            ("not json", b"{oops"),
            ("not utf-8", b"\xff\xfe"),
            ("not an object", b"[1, 2]"),
        ):
            with (
                self.subTest(name),
                self.assertRaisesRegex(fetch.Refused, "malformed manifest"),
            ):
                self.serve_manifest(image, raw)

    def test_manifest_without_exactly_one_layer_is_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        layer = json.loads(image.manifest_bytes)["layers"][0]
        for name, layers, pattern in (
            ("missing", None, "exactly one layer"),
            ("zero", [], "exactly one layer"),
            ("two", [layer, dict(layer)], "exactly one layer"),
            ("not an object", [42], "the layer is 42"),
        ):
            with self.subTest(name):
                raw = json.dumps(
                    {**json.loads(image.manifest_bytes), "layers": layers},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                with self.assertRaisesRegex(fetch.Refused, pattern):
                    self.serve_manifest(image, raw)

    def test_malformed_layer_descriptor_is_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        digest = json.loads(image.manifest_bytes)["layers"][0]["digest"]
        bad = "sha256:" + "g" * 64
        for name, layer, pattern in (
            ("digest missing", {"size": 4}, "digest is None"),
            ("digest malformed", {"digest": bad, "size": 4}, "digest is 'sha256:g"),
            ("size missing", {"digest": digest}, "size is None"),
            ("size negative", {"digest": digest, "size": -1}, "size is -1"),
            ("size boolean", {"digest": digest, "size": True}, "size is True"),
            ("type missing", {"digest": digest, "size": 4}, "type is None"),
        ):
            with self.subTest(name):
                raw = json.dumps(
                    {**json.loads(image.manifest_bytes), "layers": [layer]},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                with self.assertRaisesRegex(fetch.Refused, pattern):
                    self.serve_manifest(image, raw)

    def test_layer_bytes_with_a_wrong_digest_are_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        image.layer_bytes = b"x" + image.layer_bytes[1:]
        with self.assertRaisesRegex(fetch.Refused, "the layer digest is"):
            self.pull(image)

    def test_layer_bytes_with_a_wrong_size_are_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        image.layer["size"] += 1
        image.retag()
        with self.assertRaisesRegex(fetch.Refused, "the layer blob is"):
            self.pull(image)

    def test_image_without_the_archive_is_refused(self) -> None:
        image = PackedImage.packed({fetch.HASH_FILE: f"{HASH}\n".encode()})
        with self.assertRaisesRegex(fetch.Refused, "holds no"):
            self.pull(image)

    def test_ambiguous_archive_members_are_refused(self) -> None:
        image = PackedImage.hand_packed(
            [
                (f"{TAG}.tar.zst", b"one"),
                (fetch.HASH_FILE, b"hash"),
                (f"{TAG}.tar.zst", b"two"),
            ]
        )
        with self.assertRaisesRegex(fetch.Refused, "more than one"):
            self.pull(image)

    def test_a_non_regular_archive_member_is_refused(self) -> None:
        image = PackedImage.hand_packed(
            [(f"{TAG}.tar.zst", b"", tarfile.SYMTYPE, "elsewhere")]
        )
        with self.assertRaisesRegex(fetch.Refused, "not a regular file"):
            self.pull(image)

    def test_malformed_layer_data_is_refused(self) -> None:
        image = PackedImage.of_layer(b"not gzip")
        with self.assertRaisesRegex(fetch.Refused, "malformed layer data"):
            self.pull(image)

    def test_incomplete_gzip_footer_is_refused(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        image = PackedImage.of_layer(image.layer_bytes[:-1])
        with self.assertRaisesRegex(fetch.Refused, "malformed layer data"):
            self.pull(image)

    def test_download_stops_when_the_image_vanished(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        reg = FakeRegistry(image)
        reg.manifest_answer = None
        with self.assertRaisesRegex(fetch.SourceError, "vanished"):
            self.pull(image, reg)

    def test_a_manifest_request_error_is_a_source_error(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        reg = FakeRegistry(image)
        reg.manifest_error = artifact.ArtifactError("registry pull of x: HTTP 500")
        with self.assertRaisesRegex(fetch.SourceError, "HTTP 500"):
            self.pull(image, reg)

    def test_a_blob_request_error_is_a_source_error(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        reg = FakeRegistry(image)
        reg.blob_error = artifact.ArtifactError("registry pull of x: HTTP 500")
        with self.assertRaisesRegex(fetch.SourceError, "HTTP 500"):
            self.pull(image, reg)

    def test_refused_image_leaves_the_rebuild_eligible(self) -> None:
        """A refused image never installs; outside Actions the next allowed source follows."""
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        image.layer["size"] += 1
        image.retag()
        r = self.run_fetch("outside", self.store(FakeRegistry(image)))
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("the layer blob is", r.refusals[0])

    def test_a_registry_error_stops_outside_actions(self) -> None:
        image = PackedImage.packed({f"{TAG}.tar.zst": b"payload"})
        reg = FakeRegistry(image)
        reg.manifest_error = artifact.ArtifactError("registry pull of x: HTTP 500")
        r = fetch.fetch(
            TAG,
            self.root,
            fetch.sources(fetch.Context("outside")),
            self.store(reg),
            lambda _: True,
            self.rebuild_ok,
            self.staged,
            self.log.append,
            stop_on_source_error=True,
        )
        self.assertIsNone(r.prefix)
        self.assertEqual(self.rebuilt, 0)
        self.assertIn("HTTP 500", r.errors[0])
        self.assertTrue(any("stopping, no rebuild" in x for x in self.log))


class SourceErrorTest(Case):
    """An image source that cannot be asked is never read as "no image" (#130 review, #254)."""

    class Broken:
        def find(self, tag: str):
            raise fetch.SourceError("registry probe of ghcr.io/x: HTTP 401")

    def test_outside_actions_stops_without_rebuilding(self) -> None:
        order = fetch.sources(fetch.Context("outside"))
        r = fetch.fetch(
            TAG,
            self.root,
            order,
            self.Broken(),
            lambda _: True,
            self.rebuild_ok,
            self.staged,
            self.log.append,
            stop_on_source_error=True,
        )
        self.assertIsNone(r.prefix)
        self.assertEqual(self.rebuilt, 0)
        self.assertIn("HTTP 401", r.errors[0])
        self.assertTrue(any("stopping, no rebuild" in x for x in self.log))

    def test_in_actions_the_next_source_follows_a_warning(self) -> None:
        self.stage()
        order = fetch.sources(fetch.Context("hosted_pr"), rebuild=False)
        r = fetch.fetch(
            TAG,
            self.root,
            order,
            self.Broken(),
            lambda _: True,
            self.rebuild_ok,
            self.staged,
            self.log.append,
        )
        self.assertEqual((r.source, self.installed()), ("staged", "staged"))
        self.assertTrue(any(x.startswith("::warning::") for x in self.log))

    def test_outside_actions_stops_when_gh_cannot_verify_the_image(self) -> None:
        image = FakeImages(self.tmp / "unused.tar.zst")
        for error in (
            FileNotFoundError("gh"),
            "HTTP 401",
            "HTTP 500",
            "✗ Sigstore verification failed",
        ):
            with self.subTest(error=error):
                with mock.patch.object(fetch.subprocess, "run") as run:
                    if isinstance(error, OSError):
                        run.side_effect = error
                    else:
                        run.return_value = subprocess.CompletedProcess(
                            ["gh"], 1, "", error
                        )
                    result = fetch.fetch(
                        TAG,
                        self.root,
                        fetch.sources(fetch.Context("outside")),
                        image,
                        fetch.gh_verify,
                        self.rebuild_ok,
                        self.staged,
                        self.log.append,
                        stop_on_source_error=True,
                    )
                self.assertIsNone(result.prefix)
                self.assertEqual(self.rebuilt, 0)
                self.assertFalse(result.refusals)
                self.assertIn("gh attestation verify", result.errors[0])


class GhBoundaryTest(unittest.TestCase):
    """The gh call itself, with subprocess.run replaced: the verify policy of an image (#254)."""

    def test_verify_policy_and_verdict(self) -> None:
        calls: list[list[str]] = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404")

        with mock.patch.object(fetch.subprocess, "run", run):
            ok, out = fetch.gh_verify_report(SUBJECT)
            with self.assertRaisesRegex(
                fetch.SourceError, "could not establish provenance"
            ):
                fetch.gh_verify(SUBJECT)
        self.assertFalse(ok)
        self.assertIn("HTTP 404", out)
        cmd = calls[0]
        self.assertEqual(cmd[:4], ["gh", "attestation", "verify", SUBJECT])
        flags = dict(zip(cmd[4::2], cmd[5::2], strict=False))
        self.assertEqual(
            flags["--signer-workflow"],
            "ray-manaloto/cpp-standard/.github/workflows/publish.yml",
        )
        self.assertEqual(flags["--source-ref"], "refs/heads/main")
        self.assertEqual(flags["--repo"], "ray-manaloto/cpp-standard")
        self.assertIn("--deny-self-hosted-runners", cmd)

    def test_verify_refuses_only_identified_attestation_failures(self) -> None:
        for output in (
            f"✗ No attestations found for subject {DIGEST}",
            "✗ Policy verification failed",
        ):
            with (
                self.subTest(output=output),
                mock.patch.object(
                    fetch.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(["gh"], 1, "", output),
                ),
            ):
                self.assertFalse(fetch.gh_verify(SUBJECT))

    def test_verify_passes_on_exit_zero(self) -> None:
        def run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with mock.patch.object(fetch.subprocess, "run", run):
            self.assertTrue(fetch.gh_verify(SUBJECT))


class InstallTest(Case):
    """The install: <root>/<tag> is a symlink to an immutable sibling directory, switched
    atomically, so it resolves to a complete install at every moment (#130 review)."""

    def visible(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if not p.name.startswith("."))

    def targets(self) -> list[str]:
        return sorted(
            p.name
            for p in self.root.iterdir()
            if p.name.startswith(f".{TAG}.") and p.is_dir() and not p.is_symlink()
        )

    def assert_complete(self, content: str) -> None:
        dest = self.root / TAG
        self.assertTrue(dest.is_symlink())
        self.assertEqual(self.installed(), content)
        self.assertEqual((dest / fetch.HASH_FILE).read_text().strip(), HASH)

    def test_reinstall_replaces_and_removes_the_old_target(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        first = os.readlink(self.root / TAG)
        fetch.install(make_archive(self.tmp / "b.tar.zst", "two"), TAG, self.root)
        self.assert_complete("two")
        self.assertNotEqual(os.readlink(self.root / TAG), first)
        self.assertEqual(self.visible(), [TAG])
        self.assertEqual(self.targets(), [os.readlink(self.root / TAG)])

    def test_the_link_is_relative_and_inside_the_root(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        target = os.readlink(self.root / TAG)
        self.assertNotIn("/", target)
        self.assertTrue(target.startswith(f".{TAG}."))

    def test_installed_prefix_is_readable(self) -> None:
        prefix = fetch.install(
            make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root
        )
        self.assertEqual(prefix.stat().st_mode & 0o777, 0o755)
        # What the gate does: paths under the prefix, through the symlink.
        self.assertTrue((prefix / "bin/marker").is_file())
        self.assertEqual(Path(os.path.realpath(prefix)).parent, self.root.resolve())

    def test_failure_at_each_step_keeps_a_complete_install(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        for name in ("symlink", "replace"):
            with self.subTest(name):

                def boom(*a, _step=name, **kw):
                    raise OSError(f"simulated {_step}")

                with (
                    mock.patch.object(fetch.os, name, boom),
                    self.assertRaises(OSError),
                ):
                    fetch.install(
                        make_archive(self.tmp / "b.tar.zst", "two"), TAG, self.root
                    )
                self.assert_complete("one")
                self.assertEqual(self.visible(), [TAG])
        # Removing the old target after the switch may fail; the new one is installed.
        with mock.patch.object(fetch.shutil, "rmtree"):
            fetch.install(make_archive(self.tmp / "c.tar.zst", "three"), TAG, self.root)
        self.assert_complete("three")
        # The next install sweeps what was left.
        fetch.install(make_archive(self.tmp / "d.tar.zst", "four"), TAG, self.root)
        self.assert_complete("four")
        self.assertEqual(self.targets(), [os.readlink(self.root / TAG)])

    def kill_during(self, patch: str) -> None:
        """Install "two" in a child process that kills itself (SIGKILL) at `patch`."""
        archive = make_archive(self.tmp / "b.tar.zst", "two")
        code = f"""
import os, signal, sys
sys.path.insert(0, {str(ROOT / "python/toolchain")!r})
import fetch
def die(*a, **kw):
    os.kill(os.getpid(), signal.SIGKILL)
{patch} = die
fetch.install(fetch.Path({str(archive)!r}), {TAG!r}, fetch.Path({str(self.root)!r}))
"""
        r = subprocess.run([sys.executable, "-I", "-c", code], check=False)
        self.assertEqual(r.returncode, -9)

    def test_killed_before_the_switch_keeps_the_old_install(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        self.kill_during("fetch.os.replace")
        self.assert_complete("one")
        fetch.install(make_archive(self.tmp / "c.tar.zst", "three"), TAG, self.root)
        self.assert_complete("three")
        self.assertEqual(self.targets(), [os.readlink(self.root / TAG)])

    def test_killed_after_the_switch_has_the_new_install(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        self.kill_during("fetch.shutil.rmtree")
        self.assert_complete("two")

    def test_concurrent_installs_of_one_tag(self) -> None:
        archives = [make_archive(self.tmp / f"{i}.tar.zst", f"c{i}") for i in range(4)]
        code = f"""
import sys
sys.path.insert(0, {str(ROOT / "python/toolchain")!r})
import fetch
for _ in range(5):
    fetch.install(fetch.Path(sys.argv[1]), {TAG!r}, fetch.Path({str(self.root)!r}))
"""
        procs = [
            subprocess.Popen([sys.executable, "-I", "-c", code, str(a)])
            for a in archives
        ]
        self.assertEqual([p.wait() for p in procs], [0, 0, 0, 0])
        self.assertIn(self.installed(), {f"c{i}" for i in range(4)})
        self.assertEqual((self.root / TAG / fetch.HASH_FILE).read_text().strip(), HASH)
        self.assertEqual(self.visible(), [TAG])
        self.assertEqual(self.targets(), [os.readlink(self.root / TAG)])

    def legacy(self, content: str) -> None:
        """A real directory at <root>/<tag>, as the earlier install wrote it."""
        d = self.root / TAG
        (d / "bin").mkdir(parents=True)
        (d / "bin/marker").write_text(content)
        (d / fetch.HASH_FILE).write_text(HASH + "\n")

    def test_an_older_real_directory_is_swapped_out(self) -> None:
        self.legacy("legacy")
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        self.assert_complete("one")
        self.assertEqual(self.visible(), [TAG])
        self.assertEqual(self.targets(), [os.readlink(self.root / TAG)])

    def test_no_exchange_leaves_the_older_directory_serving(self) -> None:
        self.legacy("legacy")

        def no_exchange(a, b):
            raise OSError("simulated: no atomic exchange")

        with (
            mock.patch.object(fetch, "_exchange", no_exchange),
            self.assertRaises(OSError),
        ):
            fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        self.assertEqual(self.installed(), "legacy")
        self.assertFalse((self.root / TAG).is_symlink())
        self.assertEqual(self.visible(), [TAG])

    def test_a_failure_after_the_exchange_keeps_the_new_install(self) -> None:
        # The exchange made `dest` the link to the new directory; a failure after it (renaming
        # the swapped-out directory) must not remove the directory `dest` now points at.
        self.legacy("legacy")
        real_rename = os.rename

        def failing_rename(src, dst):
            if ".legacy-" in os.fspath(dst):
                raise OSError("simulated: rename after the exchange fails")
            return real_rename(src, dst)

        with (
            mock.patch.object(fetch.os, "rename", failing_rename),
            self.assertRaises(OSError),
        ):
            fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        self.assert_complete("one")

    def test_exchange_swaps_and_reports_errors(self) -> None:
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir()
        b.symlink_to("a")
        fetch._exchange(a, b)  # this platform's call: renameat2 or renamex_np
        self.assertTrue(a.is_symlink())
        self.assertTrue(b.is_dir() and not b.is_symlink())
        with self.assertRaises(OSError):
            fetch._exchange(self.tmp / "missing-1", self.tmp / "missing-2")

    def test_a_link_to_outside_the_root_is_not_deleted(self) -> None:
        outside = self.tmp / "elsewhere"
        (outside / "bin").mkdir(parents=True)
        (outside / "bin/marker").write_text("mine")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / TAG).symlink_to(outside)
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        self.assert_complete("one")
        self.assertEqual((outside / "bin/marker").read_text(), "mine")

    def test_refused_archive_leaves_no_target(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        bad = make_archive(self.tmp / "b.tar.zst", "bad", inputs_hash="e" * 16)
        with self.assertRaises(fetch.Refused):
            fetch.install(bad, TAG, self.root)
        self.assert_complete("one")
        self.assertEqual(self.targets(), [os.readlink(self.root / TAG)])

    def test_unknown_machine(self) -> None:
        with (
            mock.patch.object(fetch.platform, "machine", return_value="armv7l"),
            self.assertRaises(fetch.FetchError),
        ):
            fetch.host_arch()
        with mock.patch.object(fetch.platform, "machine", return_value="aarch64"):
            self.assertEqual(fetch.host_arch(), "arm64")

    def test_not_a_toolchain_tag(self) -> None:
        with self.assertRaises(fetch.FetchError):
            fetch.tag_hash("tools-arm64-0011223344556677")


class MainTest(unittest.TestCase):
    """main(): the flags map to the source table; nothing installed exits 1."""

    def run_main(self, argv: list[str], result: fetch.Result, env: dict[str, str]):
        seen = {}

        def fake_fetch(tag, root, order, *rest, **kw):
            seen["order"] = order
            return result

        with (
            mock.patch.object(fetch, "compute_tag", return_value=TAG),
            mock.patch.object(fetch, "fetch", fake_fetch),
            mock.patch.dict(fetch.os.environ, env, clear=True),
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            rc = fetch.main([*argv, "--arch", "arm64", "--root", "/tmp/r"])
        return rc, seen["order"], out.getvalue()

    def test_release_only(self) -> None:
        pr = HOSTED | {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/7/merge",
        }
        rc, order, _ = self.run_main(["--release-only"], fetch.Result(), pr)
        self.assertEqual((rc, order), (1, ["image"]))

    def test_no_rebuild(self) -> None:
        pr = HOSTED | {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/7/merge",
        }
        rc, order, _ = self.run_main(["--no-rebuild"], fetch.Result(), pr)
        self.assertEqual((rc, order), (1, ["image", "staged"]))

    def test_outside_default_and_success_output(self) -> None:
        done = fetch.Result(prefix=Path("/tmp/r") / TAG, source="image")
        rc, order, out = self.run_main([], done, {})
        self.assertEqual((rc, order), (0, ["image", "rebuild"]))
        self.assertIn(f"prefix=/tmp/r/{TAG}", out)
        self.assertIn("source=image", out)


if __name__ == "__main__":
    unittest.main()
