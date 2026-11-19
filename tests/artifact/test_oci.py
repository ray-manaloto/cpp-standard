"""Offline tests for the toolchain OCI archive the builder uploads."""

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/artifact"))

import oci

HASH = "00112233445566aa"
TAG = f"p2996-linux-arm64-{HASH}"
ARCHIVE = f"{TAG}.tar.zst"
ANNOTATIONS = {
    "org.cpp-standard.toolchain-tag": TAG,
    "org.cpp-standard.inputs-hash": HASH,
}


def digest(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


class Pack(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        payload = self.root / ARCHIVE
        payload.write_bytes(b"toolchain payload")
        marker = self.root / "inputs-hash.txt"
        marker.write_text(f"{HASH}\n")
        self.inputs = [(payload.name, payload), (marker.name, marker)]

    def test_pack_binds_the_payload_and_reproduces_the_same_image(self) -> None:
        first, second = self.root / "first.tar", self.root / "second.tar"
        first_digest = oci.pack(first, self.inputs, "arm64", "linux", ANNOTATIONS)
        os.utime(self.inputs[0][1], (1234, 1234))
        second_digest = oci.pack(
            second, list(reversed(self.inputs)), "arm64", "linux", ANNOTATIONS
        )
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first) as image:

            def member(name: str) -> bytes:
                with image.extractfile(name) as blob:
                    return blob.read()

            def blob(descriptor: dict) -> bytes:
                body = member(f"blobs/{descriptor['digest'].replace(':', '/')}")
                self.assertEqual(digest(body), descriptor["digest"])
                self.assertEqual(len(body), descriptor["size"])
                return body

            self.assertEqual(
                json.loads(member("oci-layout")), {"imageLayoutVersion": "1.0.0"}
            )
            [descriptor] = json.loads(member("index.json"))["manifests"]
            self.assertEqual(descriptor["digest"], first_digest)
            self.assertEqual(
                descriptor["platform"], {"architecture": "arm64", "os": "linux"}
            )
            manifest = json.loads(blob(descriptor))
            self.assertEqual(manifest["annotations"], ANNOTATIONS)
            [layer] = manifest["layers"]
            uncompressed = gzip.decompress(blob(layer))
            config = json.loads(blob(manifest["config"]))
            self.assertEqual(config["rootfs"]["diff_ids"], [digest(uncompressed)])
        with tarfile.open(fileobj=io.BytesIO(uncompressed)) as contents:
            self.assertEqual(contents.getnames(), sorted([ARCHIVE, "inputs-hash.txt"]))
            for name, path in self.inputs:
                with contents.extractfile(name) as entry:
                    self.assertEqual(entry.read(), path.read_bytes())

    def test_cli_reports_the_manifest_digest(self) -> None:
        dest = self.root / "image.tar"
        cmd = [
            sys.executable,
            "-I",
            str(ROOT / "python/artifact/oci.py"),
            "pack",
            str(dest),
            "--arch",
            "arm64",
            "--os",
            "linux",
            "--annotation",
            f"org.cpp-standard.toolchain-tag={TAG}",
            *(str(path) for _, path in self.inputs),
        ]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        with tarfile.open(dest) as image, image.extractfile("index.json") as index:
            [descriptor] = json.load(index)["manifests"]
        self.assertEqual(result.stdout, f"digest={descriptor['digest']}\n")

    def test_duplicate_names_are_refused(self) -> None:
        dest = self.root / "image.tar"
        with self.assertRaisesRegex(oci.OCIError, "duplicate archive paths"):
            oci.pack(dest, self.inputs * 2, "arm64", "linux")
        self.assertFalse(dest.exists())

    def test_privileged_publisher_checks_the_packed_artifact(self) -> None:
        artifact_name = f"toolchain-{TAG}"
        stage = self.root / "dist" / artifact_name
        stage.mkdir(parents=True)
        (stage / "inputs-hash.txt").write_text(f"{HASH}\n")
        expected_digest = oci.pack(
            stage / "image.tar", self.inputs, "arm64", "linux", ANNOTATIONS
        )
        metadata = stage / "image.txt"
        metadata.write_text(f"digest={expected_digest}\n")
        workflow = (ROOT / ".github/workflows/publish.yml").read_text()
        script = workflow.split("# BEGIN toolchain-artifact\n", 1)[1].split(
            "# END toolchain-artifact", 1
        )[0]
        output = self.root / "output"

        def read_artifact() -> subprocess.CompletedProcess:
            return subprocess.run(
                ["bash", "-euo", "pipefail", "-c", script],
                cwd=self.root,
                env={
                    "HOME": os.environ["HOME"],
                    "PATH": os.environ["PATH"],
                    "ARTIFACT": artifact_name,
                    "GITHUB_OUTPUT": str(output),
                },
                capture_output=True,
                check=False,
                text=True,
            )

        result = read_artifact()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"digest={expected_digest}\n", output.read_text())
        metadata.write_text("digest=sha256:" + "b" * 64 + "\n")
        self.assertNotEqual(read_artifact().returncode, 0)


if __name__ == "__main__":
    unittest.main()
