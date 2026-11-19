"""Move every apt pin to the newest version in its index (D165, #193).

The code behind `mise run pins:apt-bump` and the skill of the same name. It reads the Ubuntu 26.10 archive and
apt.llvm.org (the source in .mise/conf.d/apt-sources.toml) for arm64 and amd64, checks each index against the
strongest checksum its release file lists (SHA512 on Ubuntu, SHA256 on apt.llvm.org) and its size, and rewrites
only the version strings of the pin lines in PIN_FILES. The machine setup file's APT::Snapshot date moves with its
Ubuntu pins. Standard library only, like pins.py, so CI's bare python3 runs it.

Subcommands:
  bump [--group G] [--root DIR] [--indexes DIR]   rewrite the pins; print one line per changed package
  check [--root DIR] [--indexes DIR]              fail, naming the package, when a pinned version is gone
  vectors FILE                                    run the offline vectors (tests/apt_bump/vectors.toml)

--indexes DIR reads each source from DIR/<source>/ instead of the network (the vectors use it).
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import http.client
import io
import lzma
import os
import re
import sys
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

# The files whose apt pins move, and the one that also holds the Ubuntu snapshot date.
PIN_FILES = (
    ".mise/conf.d/apt-toolchain-host.toml",
    ".mise/conf.d/apt.toml",
    "mise.ubuntu.toml",
)
SNAPSHOT_FILE = "mise.ubuntu.toml"
SOURCES_FILE = ".mise/conf.d/apt-sources.toml"

ARCHES = ("arm64", "amd64")
# archive.ubuntu.com serves arm64 as well as amd64 (its release files list both), so one host covers both.
UBUNTU_URI = "https://archive.ubuntu.com/ubuntu/"
UBUNTU_SUITES = ("stonking", "stonking-updates", "stonking-security")
UBUNTU_COMPONENTS = ("main", "universe")
GROUPS = ("llvm", "ubuntu")

# Strongest first; a release file that lists neither is refused.
HASHES = ("SHA512", "SHA256")
# Compressed first: the smallest download whose checksum the release file lists.
PACKAGES_FILES = ("Packages.xz", "Packages.gz", "Packages")

# A pin line: `"apt:NAME" = "VERSION"` or `"apt:NAME" = { version = "VERSION", …`. Only the version is rewritten.
PIN = re.compile(
    r'^"apt:(?P<name>[^"]+)" = (?:\{ version = )?"(?P<ver>[^"]+)"', re.MULTILINE
)
SNAPSHOT = re.compile(r'^APT::Snapshot "(?P<ts>[0-9]{8}T[0-9]{6}Z)";$', re.MULTILINE)
USER_AGENT = "cpp-standard-pins-apt-bump"


class AptError(Exception):
    """An index or pin file that cannot be trusted or read; nothing is written."""


# --- dpkg version order -------------------------------------------------------


def _order(c: str) -> int:
    if not c or c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256


def _verrevcmp(a: str, b: str) -> int:
    """dpkg's verrevcmp (lib/dpkg/version.c)."""
    i = j = 0
    while i < len(a) or j < len(b):
        while (i < len(a) and not a[i].isdigit()) or (
            j < len(b) and not b[j].isdigit()
        ):
            ac = _order(a[i] if i < len(a) else "")
            bc = _order(b[j] if j < len(b) else "")
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        first_diff = 0
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def _split(v: str) -> tuple[int, str, str]:
    epoch, sep, rest = v.partition(":")
    if not sep:
        epoch, rest = "0", v
    upstream, sep, revision = rest.rpartition("-")
    if not sep:
        upstream, revision = rest, ""
    return int(epoch), upstream, revision


def compare(a: str, b: str) -> int:
    """Negative, zero or positive as Debian version a sorts before, equal to or after b."""
    ea, ua, ra = _split(a)
    eb, ub, rb = _split(b)
    if ea != eb:
        return ea - eb
    return _verrevcmp(ua, ub) or _verrevcmp(ra, rb)


def newest(versions: list[str]) -> str:
    best = versions[0]
    for v in versions[1:]:
        if compare(v, best) > 0:
            best = v
    return best


# --- indexes ------------------------------------------------------------------


@dataclass
class Source:
    name: str
    base: str  # ends in "/"
    suites: tuple[str, ...]
    components: tuple[str, ...]


@dataclass
class Index:
    """One source's packages per architecture, and the newest Date of its release files."""

    packages: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    date: datetime | None = None


class _HttpsRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another https URL, so no index is ever read in the clear."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise AptError(
                f"{req.full_url}: redirected to {newurl}, which is not https; refused"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsRedirects)


def fetch(url: str) -> bytes:
    if not url.startswith(("https://", "file:")):
        raise AptError(f"{url}: only https (or the vectors' file: indexes) is read")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _OPENER.open(req, timeout=120) as resp:
        return resp.read()


def sources(root: Path, indexes: Path | None) -> list[Source]:
    data = tomllib.loads((root / SOURCES_FILE).read_text(encoding="utf-8"))
    llvm = data["bootstrap"]["apt"]["sources"]["llvm"]
    found = [
        Source(
            "llvm", llvm["uris"], (llvm["suites"],), tuple(llvm["components"].split())
        ),
        Source("ubuntu", UBUNTU_URI, UBUNTU_SUITES, UBUNTU_COMPONENTS),
    ]
    for s in found:
        if indexes is not None:
            s.base = (indexes / s.name).resolve().as_uri()
        s.base = s.base.rstrip("/") + "/"
    return found


def _release_text(raw: bytes) -> str:
    """The Release body of an InRelease file (clearsigned) or a plain Release file."""
    text = raw.decode("utf-8")
    if text.startswith("-----BEGIN PGP SIGNED MESSAGE-----"):
        body = text.split("\n\n", 1)[1]
        return body.split("\n-----BEGIN PGP SIGNATURE-----", 1)[0]
    return text


def parse_release(
    raw: bytes, url: str
) -> tuple[datetime, str, dict[str, tuple[str, int]]]:
    """Return the Date, the strongest hash's name and its {path: (digest, size)}."""
    fields: dict[str, list[str]] = {}
    current = ""
    for line in _release_text(raw).splitlines():
        if line.startswith(" ") and current:
            fields[current].append(line.strip())
        elif ":" in line:
            current, _, value = line.partition(":")
            fields[current] = [value.strip()] if value.strip() else []
    if not fields.get("Date"):
        raise AptError(f"{url}: the release file has no Date")
    try:
        date = parsedate_to_datetime(fields["Date"][0]).astimezone(UTC)
    except (TypeError, ValueError) as e:
        raise AptError(f"{url}: the release file's Date is malformed: {e}") from e
    for algo in HASHES:
        if algo in fields:
            sums = {}
            for entry in fields[algo]:
                try:
                    digest, size, path = entry.split()
                    sums[path] = (digest.lower(), int(size))
                except ValueError as e:
                    raise AptError(
                        f"{url}: malformed {algo} line {entry!r}; refused"
                    ) from e
            return date, algo, sums
    raise AptError(
        f"{url}: the release file lists no {' or '.join(HASHES)} checksums; refused"
    )


def _decompress(name: str, data: bytes) -> str:
    if name.endswith(".xz"):
        data = lzma.decompress(data)
    elif name.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8")


def parse_packages(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for stanza in text.split("\n\n"):
        name = version = None
        for line in stanza.splitlines():
            if line.startswith("Package:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
        if name and version:
            found.setdefault(name, []).append(version)
    return found


def read_index(src: Source, get: Any = fetch) -> Index:
    index = Index({arch: {} for arch in ARCHES})
    for suite in src.suites:
        url = f"{src.base}dists/{suite}/InRelease"
        date, algo, sums = parse_release(get(url), url)
        index.date = max(index.date or date, date)
        for comp in src.components:
            for arch in ARCHES:
                path = next(
                    (
                        f"{comp}/binary-{arch}/{n}"
                        for n in PACKAGES_FILES
                        if f"{comp}/binary-{arch}/{n}" in sums
                    ),
                    None,
                )
                if path is None:
                    raise AptError(
                        f"{url}: no {comp}/binary-{arch} Packages index listed"
                    )
                purl = f"{src.base}dists/{suite}/{path}"
                data = get(purl)
                digest, size = sums[path]
                if (
                    len(data) != size
                    or hashlib.new(algo.lower(), data).hexdigest() != digest
                ):
                    raise AptError(
                        f"{purl}: does not match the {algo} checksum and size in its release file; refused"
                    )
                for name, versions in parse_packages(_decompress(path, data)).items():
                    index.packages[arch].setdefault(name, []).extend(versions)
    return index


# --- pin files ----------------------------------------------------------------


@dataclass
class Pin:
    file: str
    name: str
    version: str
    start: int  # the version's span in the file's text
    end: int


def read_pins(root: Path) -> tuple[dict[str, str], list[Pin]]:
    """Every file's text and its pins; refuse a file whose pin lines the TOML does not confirm."""
    texts: dict[str, str] = {}
    pins: list[Pin] = []
    for rel in PIN_FILES:
        with (root / rel).open(encoding="utf-8", newline="") as f:
            text = f.read()
        texts[rel] = text
        found = [
            Pin(rel, m["name"], m["ver"], m.start("ver"), m.end("ver"))
            for m in PIN.finditer(text)
        ]
        packages = tomllib.loads(text).get("bootstrap", {}).get("packages", {})
        want = {
            k.removeprefix("apt:"): v["version"] if isinstance(v, dict) else v
            for k, v in packages.items()
            if k.startswith("apt:")
        }
        if {p.name: p.version for p in found} != want or len(found) != len(want):
            raise AptError(
                f"{rel}: its apt pin lines are not one per line in a form this task rewrites"
            )
        pins.extend(found)
    return texts, pins


# --- bump and check -----------------------------------------------------------


@dataclass
class Result:
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _where(name: str, indexes: dict[str, Index]) -> list[str]:
    return [
        s for s, idx in indexes.items() if any(name in idx.packages[a] for a in ARCHES)
    ]


def _target(
    name: str, indexes: dict[str, Index], failed: tuple[str, ...] = ()
) -> tuple[str | None, str | None, str | None]:
    """(group, newest version, problem) for one package."""
    where = _where(name, indexes)
    if not where and len(failed) == 1:
        # Most likely the package of the one source that could not be read: that group is refused already.
        return failed[0], None, None
    if len(where) != 1:
        return (
            None,
            None,
            f"{name}: in {'no index' if not where else 'both ' + ' and '.join(where)}; refused",
        )
    group = where[0]
    best = {}
    for arch in ARCHES:
        versions = indexes[group].packages[arch].get(name)
        if not versions:
            return group, None, f"{name}: not in the {group} index for {arch}; refused"
        best[arch] = newest(versions)
    if len(set(best.values())) != 1:
        detail = ", ".join(f"{best[a]} on {a}" for a in ARCHES)
        return (
            group,
            None,
            f"{name}: the newest version differs between architectures ({detail}); refused",
        )
    return group, best[ARCHES[0]], None


def bump(
    root: Path,
    indexes: dict[str, Index],
    groups: tuple[str, ...],
    failed: dict[str, str] | None = None,
) -> Result:
    texts, pins = read_pins(root)
    result = Result()
    failed = failed or {}
    targets = {}
    # A source that could not be read refuses its own group only (and is a problem only when that group was asked).
    refused: set[str | None] = set(failed)
    result.problems.extend(err for g, err in failed.items() if g in groups)
    for name in sorted({p.name for p in pins}):
        group, version, problem = _target(name, indexes, tuple(failed))
        if problem:
            # Only the groups asked for report their problems, so `--group llvm` is not failed by an Ubuntu
            # refusal; a package in no index (or in both) has no group and blocks, and fails, every group.
            if group is None or group in groups:
                result.problems.append(problem)
            refused.add(group)
        targets[name] = (group, version)
    # A pin never moves backwards: an index whose newest version is older than the pin refuses the group.
    for p in pins:
        group, version = targets[p.name]
        if version is not None and compare(version, p.version) < 0:
            if group in groups:
                result.problems.append(
                    f"{p.file}: {p.name} {p.version} is newer than the index's newest {version}; refused"
                )
            refused.add(group)
    # A group with any refused package changes nothing.
    live = [g for g in groups if g not in refused and None not in refused]
    edits: dict[str, list[tuple[int, int, str]]] = {}
    changed: dict[tuple[str, str], str] = {}
    snapshot_moves = False
    for p in pins:
        group, version = targets[p.name]
        if group in live and version is not None and compare(version, p.version) > 0:
            edits.setdefault(p.file, []).append((p.start, p.end, version))
            changed[(p.name, p.version)] = version
            snapshot_moves |= p.file == SNAPSHOT_FILE and group == "ubuntu"
    # The snapshot date moves only with a machine-file Ubuntu pin, to the newest Ubuntu release file's Date, so
    # snapshot.ubuntu.com serves exactly the indexes the pins were read from.
    if snapshot_moves:
        m = SNAPSHOT.search(texts[SNAPSHOT_FILE])
        if m is None:
            raise AptError(f"{SNAPSHOT_FILE}: no APT::Snapshot line")
        date = indexes["ubuntu"].date
        if date is None:
            raise AptError("the Ubuntu indexes have no release file Date")
        ts = date.strftime("%Y%m%dT%H%M%SZ")
        # Never backwards: the format sorts as text.
        if ts > m["ts"]:
            edits.setdefault(SNAPSHOT_FILE, []).append((m.start("ts"), m.end("ts"), ts))
            result.lines.append(f"APT::Snapshot {m['ts']} -> {ts}")
    for rel, spans in edits.items():
        text = texts[rel]
        for start, end, new in sorted(spans, reverse=True):
            text = text[:start] + new + text[end:]
        _replace(root / rel, text)
    result.lines[:0] = [
        f"{name} {old} -> {new}" for (name, old), new in sorted(changed.items())
    ]
    return result


def _replace(path: Path, text: str) -> None:
    """Write through a temporary file in the same folder, so a pin file is never left half written."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def check(root: Path, indexes: dict[str, Index]) -> Result:
    _, pins = read_pins(root)
    result = Result()
    for p in pins:
        where = _where(p.name, indexes)
        if not where:
            result.problems.append(f"{p.file}: {p.name} is in no index")
            continue
        for arch in ARCHES:
            if not any(
                p.version in indexes[s].packages[arch].get(p.name, []) for s in where
            ):
                result.problems.append(
                    f"{p.file}: {p.name} {p.version} is no longer in the {where[0]} index for {arch}"
                )
    return result


# What reading an index or a pin file can raise; each becomes one FAIL line.
READ_ERRORS = (
    AptError,
    OSError,
    EOFError,
    http.client.HTTPException,
    ValueError,
    KeyError,
    IndexError,
    lzma.LZMAError,
    tomllib.TOMLDecodeError,
)


def run(cmd: str, root: Path, idx_root: Path | None, group: str) -> int:
    try:
        indexes: dict[str, Index] = {}
        failed: dict[str, str] = {}
        for s in sources(root, idx_root):
            try:
                indexes[s.name] = read_index(s)
            except READ_ERRORS as e:
                failed[s.name] = f"{s.name}: {e}"
        if cmd == "check":
            # The check covers every pin, so any unreadable source fails it.
            result = Result(problems=list(failed.values()))
            if not failed:
                result = check(root, indexes)
        else:
            groups = GROUPS if group == "all" else (group,)
            result = bump(root, indexes, groups, failed)
    except READ_ERRORS as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    for line in result.lines:
        print(line)
    for problem in result.problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if cmd == "check" and not result.problems:
        print("PASS: every apt pin is in its index")
    return 1 if result.problems else 0


# --- offline vectors ----------------------------------------------------------


# What a tampered index adds: a newer version of every pinned package the vectors use.
EVIL = "".join(
    f"\nPackage: {p}\nVersion: 99:0-evil\n" for p in ("curl", "g++-16", "clang-23")
)


def _pack(name: str, text: str) -> bytes:
    if name.endswith(".xz"):
        return lzma.compress(text.encode())
    return gzip.compress(text.encode(), mtime=0)


def _write_indexes(
    top: Path, spec: dict[str, Any], vector: dict[str, Any], srcs: list[Source]
) -> list[str]:
    """Build each source's dists/ tree from the vector's Packages stanzas, with release files to match."""
    problems: list[str] = []
    stanzas = {**spec.get("index", {}), **vector.get("index", {})}
    date = vector.get("date", spec.get("date", "Wed, 18 Nov 2026 14:41:27 UTC"))
    for s in srcs:
        algo = "SHA512" if s.name == "ubuntu" else vector.get("algo", "SHA256")
        digest_name = "md5" if algo == "MD5Sum" else algo.lower()
        name = "Packages.xz" if s.name == "ubuntu" else "Packages.gz"
        for suite in s.suites:
            dist = top / s.name / "dists" / suite
            sums = []
            for comp in s.components:
                for arch in ARCHES:
                    key = f"{s.name}/{suite}/{comp}/{arch}"
                    text = stanzas.get(key, "")
                    data = _pack(name, text)
                    rel = f"{comp}/binary-{arch}/{name}"
                    sums.append(
                        f" {hashlib.new(digest_name, data).hexdigest()} {len(data)} {rel}"
                    )
                    # A tampered index: well-formed, but not the one the release file lists.
                    if vector.get("corrupt") == key:
                        data = _pack(name, text + EVIL)
                    # Tampered at the same size, so only the digest comparison can catch it.
                    if vector.get("tamper") == key:
                        tampered = _pack(name, text.replace("11.1", "11.9", 1))
                        if len(tampered) != len(data) or tampered == data:
                            problems.append(
                                "the tampered index is not a same-size change"
                            )
                        data = tampered
                    (dist / rel).parent.mkdir(parents=True, exist_ok=True)
                    (dist / rel).write_bytes(data)
            release = (
                f"Suite: {suite}\nDate: {date}\nArchitectures: {' '.join(ARCHES)}\n{algo}:\n"
                + "\n".join(sums)
            )
            # `release_extra`: lines added to a source's release files (a malformed one, say).
            release += vector.get("release_extra", {}).get(s.name, "")
            if s.name == "ubuntu":
                release = (
                    "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n"
                    + release
                    + "\n-----BEGIN PGP SIGNATURE-----\nfixture\n-----END PGP SIGNATURE-----\n"
                )
            (dist / "InRelease").write_text(release, encoding="utf-8")
    return problems


def run_vectors(spec: dict[str, Any]) -> list[str]:
    failures = []
    for o in spec.get("order", []):
        got = compare(o["a"], o["b"])
        got = (got > 0) - (got < 0)
        if got != o["want"]:
            failures.append(f"order {o['a']} vs {o['b']}: want {o['want']}, got {got}")
    for vector in spec["vector"]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tree"
            files = {**spec["tree"], **vector.get("change", {})}
            for rel, content in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(content, encoding="utf-8")
            idx = Path(tmp) / "indexes"
            setup = _write_indexes(idx, spec, vector, sources(root, idx))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = run(vector["cmd"], root, idx, vector.get("group", "all"))
            after = {rel: (root / rel).read_text(encoding="utf-8") for rel in files}
            # `rerun`: the same command again must change nothing and print nothing.
            again = io.StringIO()
            if vector.get("rerun"):
                with (
                    contextlib.redirect_stdout(again),
                    contextlib.redirect_stderr(again),
                ):
                    code2 = run(vector["cmd"], root, idx, vector.get("group", "all"))
                second = {
                    rel: (root / rel).read_text(encoding="utf-8") for rel in files
                }
                if code2 != 0 or again.getvalue() or second != after:
                    setup.append(
                        f"the second run was not a no-op: {again.getvalue().strip()}"
                    )
        n = vector["name"]
        failures.extend(f"{n}: {p}" for p in setup)
        if code != vector.get("exit", 0):
            failures.append(
                f"{n}: want exit {vector.get('exit', 0)}, got {code}: {err.getvalue().strip()}"
            )
        if "stdout" in vector and out.getvalue().splitlines() != vector["stdout"]:
            failures.append(
                f"{n}: want stdout {vector['stdout']}, got {out.getvalue().splitlines()}"
            )
        for needle in vector.get("stderr", []):
            if needle not in err.getvalue():
                failures.append(
                    f"{n}: stderr lacks {needle!r}: {err.getvalue().strip()}"
                )
        if vector.get("unchanged") and after != files:
            failures.append(f"{n}: a file changed")
        for rel, wants in vector.get("contains", {}).items():
            for want in wants:
                if want not in after[rel]:
                    failures.append(f"{n}: {rel} lacks {want!r}")
    return failures


# --- command line -------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="apt_bump")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("bump", "check"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, default=Path.cwd())
        p.add_argument("--indexes", type=Path, default=None)
        if name == "bump":
            p.add_argument("--group", choices=("all", *GROUPS), default="all")
    v = sub.add_parser("vectors")
    v.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "vectors":
        spec = tomllib.loads(args.file.read_text(encoding="utf-8"))
        failures = run_vectors(spec)
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        if not failures:
            print(
                f"PASS: {len(spec['vector'])} apt-bump vectors, {len(spec.get('order', []))} order vectors"
            )
        return 1 if failures else 0
    return run(args.cmd, args.root, args.indexes, getattr(args, "group", "all"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
