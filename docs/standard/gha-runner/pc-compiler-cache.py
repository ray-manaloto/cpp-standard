"""Input-addressed store for the Ubuntu amd64 p2996 compiler and its matching IWYU."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECIPE = Path("docs/standard/ubuntu-p2996")
PIN = re.compile(r"^(commit|iwyu_commit)=([0-9a-f]{40})$", re.MULTILINE)
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_packages(rows):
    """Capture installed development packages and the runtime closure of build inputs."""
    packages = {}
    providers = {}
    for line in rows.splitlines():
        status, name, version, requires, provides = line.split("\t")
        if status[:2] != "ii":
            continue
        packages[name] = (version, requires)
        for virtual in provides.split(","):
            if virtual.strip():
                providers.setdefault(virtual.split()[0], []).append(name)
    selected = set()
    pending = [
        name
        for name in packages
        if name.endswith("-dev")
        or name.startswith(
            ("clang-", "llvm-", "gcc-", "g++-", "binutils", "swig", "lld-", "python3")
        )
        or name == "libc6"
    ]
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        for dep in re.split(r"[,|]", packages[name][1]):
            match = re.match(r"\s*([a-z0-9][a-z0-9+.-]*)", dep)
            if match:
                depname = match[1]
                if depname in packages:
                    pending.append(depname)
                pending.extend(providers.get(depname, []))
    return {name: packages[name][0] for name in sorted(selected)}


def inputs(source, base, donor):
    if not DIGEST.fullmatch(base) or not DIGEST.fullmatch(donor):
        raise ValueError("expected immutable base and donor IDs")
    recipe = source / RECIPE
    files = [recipe / "build-linux.sh", *sorted(recipe.glob("*.patch"))]
    pins = dict(PIN.findall(files[0].read_text()))
    if set(pins) != {"commit", "iwyu_commit"}:
        raise ValueError("missing compiler or IWYU source pin")
    fmt = "${db:Status-Abbrev}\t${Package}\t${Version}\t${Pre-Depends},${Depends}\t${Provides}\n"
    packages = build_packages(
        subprocess.check_output(["dpkg-query", "-W", "-f", fmt], text=True)
    )
    tools = {}
    for name in ("clang-23", "clang++-23", "ld.lld", "cmake", "ninja", "sccache"):
        selected = (
            subprocess.check_output(
                ["clang-23", "--print-prog-name=ld.lld"], text=True
            ).strip()
            if name == "ld.lld"
            else name
        )
        binary = shutil.which(selected)
        if not binary:
            raise ValueError(f"missing compiler build input {name}")
        tools[name] = sha(Path(binary))
    return {
        "schema": 1,
        "platform": "linux/amd64",
        "base": base,
        "addon_donor": donor,
        "prefix": "/opt/p2996",
        "pins": pins,
        "packages": packages,
        "tools": tools,
        "recipe": {p.name: sha(p) for p in files},
    }


def tag(key):
    return "p2996-pc-linux-amd64-" + key[:16]


def pack(identity, prefix, out):
    key = sha(identity)
    out.mkdir()
    (out / "inputs.json").write_bytes(identity.read_bytes())
    archive = out / (tag(key) + ".tar.zst")

    def normalized(member):
        member.uid = member.gid = member.mtime = 0
        member.uname = member.gname = ""
        return member

    # Normalize metadata and preserve the installed modes, links and sorted file order.
    with (
        archive.open("wb") as output,
        subprocess.Popen(
            ["zstd", "-T2", "-3", "-q", "-c"], stdin=subprocess.PIPE, stdout=output
        ) as compressor,
    ):
        with compressor.stdin as pipe, tarfile.open(fileobj=pipe, mode="w|") as bundle:
            bundle.add(identity, arcname="inputs.json", filter=normalized)
            bundle.add(prefix, arcname="p2996", filter=normalized)
        if compressor.wait():
            raise ValueError("compiler package compression failed")
    receipt = {"inputs_sha256": key, "archive_sha256": sha(archive)}
    (out / "package.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
    return receipt


def verify(identity, entry):
    key = sha(identity)
    archive = entry / (tag(key) + ".tar.zst")
    receipt = json.loads((entry / "package.json").read_bytes())
    if receipt != {"inputs_sha256": key, "archive_sha256": sha(archive)}:
        raise ValueError(f"package digest mismatch for {key}")
    # The fixed first entry lets us compare the full identity before extracting the prefix.
    with subprocess.Popen(["zstd", "-qdc", archive], stdout=subprocess.PIPE) as decoder:
        try:
            with tarfile.open(fileobj=decoder.stdout, mode="r|") as bundle:
                first = bundle.next()
                if (
                    not first
                    or first.name != "inputs.json"
                    or not first.isreg()
                    or first.size != identity.stat().st_size
                ):
                    raise ValueError(f"invalid compiler identity header for {key}")
                with bundle.extractfile(first) as embedded:
                    if embedded.read() != identity.read_bytes():
                        raise ValueError(f"embedded compiler inputs differ for {key}")
        finally:
            decoder.stdout.close()
            decoder.wait()
    return archive


def remote(identity, store):
    # Reuse the existing protected publisher policy and digest-checked OCI layer reader.
    sys.path.insert(0, str(ROOT / "python/toolchain"))
    import fetch

    key = sha(identity)
    images = fetch.GhImage(fetch.artifact.Registry(None))
    image = images.find(tag(key))
    if image is None:
        return "absent"
    subject = f"oci://{image.ref.rpartition(':')[0]}@{image.digest}"
    if not fetch.gh_verify(subject):
        raise ValueError(f"refused publisher for {subject}")
    with tempfile.TemporaryDirectory(dir=store) as temp:
        scratch = Path(temp)
        archive = images.download(image, tag(key), scratch)
        entry = scratch / "entry"
        entry.mkdir()
        archive = archive.rename(entry / archive.name)
        (entry / "package.json").write_text(
            json.dumps({"inputs_sha256": key, "archive_sha256": sha(archive)})
        )
        (entry / "inputs.json").write_bytes(identity.read_bytes())
        verify(identity, entry)
        (entry / "registry-digest").write_text(image.digest + "\n")
        entry.rename(store / key)
    return image.digest


def publish_files(identity, entry, dest):
    sys.path.insert(0, str(ROOT / "python/artifact"))
    import oci

    key = sha(identity)
    name = tag(key)
    archive = verify(identity, entry)
    dest.mkdir()
    short_hash = dest / "inputs-hash.txt"
    short_hash.write_text(key[:16] + "\n")
    digest = oci.pack(
        dest / "image.tar",
        [(archive.name, archive), (short_hash.name, short_hash)],
        "amd64",
        "linux",
        {
            "org.cpp-standard.inputs-hash": key[:16],
            "org.cpp-standard.toolchain-tag": name,
            "org.cpp-standard.compiler-inputs-sha256": key,
        },
    )
    (dest / "image.txt").write_text(f"tag={name}\ndigest={digest}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    identity = sub.add_parser("identity")
    identity.add_argument("source", type=Path)
    identity.add_argument("base")
    identity.add_argument("donor")
    for name, paths in {
        "pack": ("identity", "prefix", "out"),
        "verify": ("identity", "entry"),
        "restore": ("identity", "entry", "parent"),
        "remote": ("identity", "store"),
        "publish-files": ("identity", "entry", "out"),
    }.items():
        cmd = sub.add_parser(name)
        for path in paths:
            cmd.add_argument(path, type=Path)
    args = parser.parse_args()
    if args.action == "identity":
        print(
            json.dumps(
                inputs(args.source, args.base, args.donor),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    elif args.action == "pack":
        print(json.dumps(pack(args.identity, args.prefix, args.out)))
    elif args.action == "remote":
        print(remote(args.identity, args.store))
    elif args.action == "publish-files":
        publish_files(args.identity, args.entry, args.out)
    else:
        archive = verify(args.identity, args.entry)
        if args.action == "restore":
            if os.path.lexists(args.parent / "p2996"):
                raise ValueError("compiler install prefix already exists")
            subprocess.run(
                ["tar", "--zstd", "-xf", archive, "-C", args.parent, "p2996"],
                check=True,
            )
        print((args.entry / "package.json").read_text().strip())


if __name__ == "__main__":
    main()
