"""Pack files into a one-manifest OCI image archive (M1a PR 3, #254).

The main builder packs dist/<tag>/<tag>.tar.zst and inputs-hash.txt into a scratch OCI
image whose one gzip layer holds those files. publish.yml uploads and attests the manifest
digest, then publishes ghcr.io/ray-manaloto/cpp-standard/tools:<tag>. toolchain:fetch pulls
by digest and installs the archive it carries (python/toolchain/fetch.py).

Standard-library Python 3.11 or later only, like artifact.py. It needs no Docker or buildx.
The image is byte-for-byte reproducible: fixed mtimes,
uid/gid 0, entries in sorted order, gzip with mtime 0.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO

MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"


class OCIError(Exception):
    pass


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _canonical(data: dict) -> bytes:
    """The exact bytes a descriptor's digest is taken over: compact JSON, sorted keys."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def _entry(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


class _TarWriter:
    def __init__(self, compressed: gzip.GzipFile) -> None:
        self.compressed = compressed
        self.hash = hashlib.sha256()

    def write(self, data: bytes) -> int:
        self.hash.update(data)
        return self.compressed.write(data)


def _layer(files: list[tuple[str, Path]], layer: BinaryIO) -> str:
    """Stream a gzip layer to disk and return the digest of its uncompressed tar."""
    entries = sorted(files)
    names = [name for name, _ in entries]
    if len(set(names)) != len(names):
        raise OCIError(f"duplicate archive paths: {names}")
    # The toolchain archive is already compressed with zstd.
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=layer, compresslevel=1, mtime=0
    ) as gz:
        writer = _TarWriter(gz)
        with tarfile.open(fileobj=writer, mode="w|") as tar:
            for name, path in entries:
                with path.open("rb") as source:
                    tar.addfile(_entry(name, os.fstat(source.fileno()).st_size), source)
    return f"sha256:{writer.hash.hexdigest()}"


def _blob_path(digest: str) -> str:
    return f"blobs/{digest.replace(':', '/')}"


def pack(
    dest: Path,
    files: list[tuple[str, Path]],
    arch: str,
    os_name: str,
    annotations: dict[str, str] | None = None,
) -> str:
    """Write an OCI archive of `files` as one layer and return the manifest digest."""
    with tempfile.TemporaryFile(dir=dest.parent) as layer:
        diff_id = _layer(files, layer)
        size = layer.tell()
        layer.seek(0)
        layer_digest = f"sha256:{hashlib.file_digest(layer, 'sha256').hexdigest()}"
        layer.seek(0)
        return _write_image(
            dest, layer, size, layer_digest, diff_id, arch, os_name, annotations
        )


def _write_image(
    dest: Path,
    layer: BinaryIO,
    size: int,
    layer_digest: str,
    diff_id: str,
    arch: str,
    os_name: str,
    annotations: dict[str, str] | None,
) -> str:
    config = {
        "architecture": arch,
        "os": os_name,
        "config": {},
        "rootfs": {"type": "layers", "diff_ids": [diff_id]},
    }
    config_bytes = _canonical(config)
    manifest: dict = {
        "schemaVersion": 2,
        "mediaType": MANIFEST_MEDIA_TYPE,
        "config": {
            "mediaType": CONFIG_MEDIA_TYPE,
            "digest": _digest(config_bytes),
            "size": len(config_bytes),
        },
        "layers": [
            {
                "mediaType": LAYER_MEDIA_TYPE,
                "digest": layer_digest,
                "size": size,
            }
        ],
    }
    if annotations:
        manifest["annotations"] = dict(sorted(annotations.items()))
    manifest_bytes = _canonical(manifest)
    manifest_digest = _digest(manifest_bytes)
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": MANIFEST_MEDIA_TYPE,
                "digest": manifest_digest,
                "size": len(manifest_bytes),
                "platform": {"architecture": arch, "os": os_name},
            }
        ],
    }
    members = [
        ("oci-layout", b'{"imageLayoutVersion":"1.0.0"}'),
        ("index.json", _canonical(index)),
        (_blob_path(manifest["config"]["digest"]), config_bytes),
        (_blob_path(manifest_digest), manifest_bytes),
    ]
    with tarfile.open(dest, mode="w") as f:  # an OCI archive is an uncompressed tar
        for name, body in members:
            f.addfile(_entry(name, len(body)), io.BytesIO(body))
        f.addfile(_entry(_blob_path(layer_digest), size), layer)
    return manifest_digest


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="oci-pack")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("pack")
    k.add_argument("dest", type=Path)
    k.add_argument("--arch", default="arm64")
    k.add_argument("--os", dest="os_name", default="linux")
    k.add_argument("--annotation", action="append", default=[])
    k.add_argument("files", nargs="+", type=Path)
    args = p.parse_args(argv)
    annotations = {}
    for a in args.annotation:
        key, sep, value = a.partition("=")
        if not sep or not key:
            print(f"FAIL: --annotation {a} is not key=value", file=sys.stderr)
            return 1
        annotations[key] = value
    try:
        digest = pack(
            args.dest,
            [(f.name, f) for f in args.files],
            args.arch,
            args.os_name,
            annotations,
        )
    except (OCIError, OSError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"digest={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
