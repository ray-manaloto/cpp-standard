"""toolchain:fetch: install a toolchain by its artifact tag (M1a PR 3, ticket #130).

environment-standard.md section 2 step 5 and the toolchain/fetch row of the file plan; D72, D83,
D91, D111, D116, D122, D131, D134. Standard-library Python 3.11 or later, like
python/artifact/artifact.py; the release store, the attestation verifier and the rebuild are passed
in, so tests/toolchain/ runs every row of the source table with no network or build.

Where a toolchain may come from depends on where the fetch runs (ticket #130):

    hosted pull-request or merge-queue job   release, else this run's staged copy, else a rebuild
    any other Actions run (main, dispatch)   release, else a rebuild; never a staged copy
    outside Actions (the owner's machines)   release, else a rebuild; never a staged copy

A staged copy is `.cache/toolchains/<tag>/<tag>.tar.zst`, put there by a workflow step of the same
run (actions/cache/restore, D91). A miss never fails the fetch while a later source remains (D83).
`--release-only` turns both fallbacks off; `--no-rebuild` turns the rebuild off, for the jobs that
wait for the one job of a hosted run that builds.

Every source is checked the same way before anything is installed: a release must be the only
non-draft release whose title or tag is the artifact tag (D122), and its archive must pass
`gh attestation verify` as publish.yml on refs/heads/main (D116, the image policy of
artifact.verify_flags). Every archive is extracted into a new immutable directory
`<root>/.<tag>.<unique>` and must hold an `inputs-hash.txt` equal to the tag's hash (D131) before
the public prefix `<root>/<tag>`, a symlink, is switched to it in one atomic step. So a refused
archive is never installed, a toolchain installed before a refusal is left as it was, and
`<root>/<tag>` resolves to a complete install at every moment.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifact"))

import artifact

REPO = artifact.REPO
TAG = artifact.TOOLCHAIN_TAG
HASH_FILE = "inputs-hash.txt"
# The atomic exchange of two paths: renameat2(AT_FDCWD, ..., RENAME_EXCHANGE) on Linux,
# renamex_np(..., RENAME_SWAP) on macOS (both 1 << 1).
AT_FDCWD = -100
RENAME_EXCHANGE = 2
RENAME_SWAP = 2
PR_EVENTS = artifact.PR_EVENTS

RELEASE, STAGED, REBUILD = "release", "staged", "rebuild"


class FetchError(Exception):
    pass


class Refused(Exception):
    """A source had the toolchain, but it failed a check: never installed."""


class SourceError(Exception):
    """The release source could not be asked at all (no gh, no token, an API failure). It is
    never read as "no release": outside Actions the fetch stops with the reason instead of
    starting a rebuild; in Actions the next source is tried, with a warning (D83)."""


# --- where the fetch runs -----------------------------------------------------


@dataclass(frozen=True)
class Context:
    """`hosted_pr` (a hosted pull-request or merge-queue job), `actions` (any other Actions run,
    `main` included) or `outside` (outside Actions)."""

    kind: str

    @staticmethod
    def from_env(env: dict[str, str]) -> Context:
        if env.get("GITHUB_ACTIONS") != "true":
            return Context("outside")
        if (
            env.get("GITHUB_EVENT_NAME") in PR_EVENTS
            # ci.yml sets CPPSTD_RUNNER_ENVIRONMENT from runner.environment: a workflow cannot
            # set the reserved RUNNER_* names, and a job container may not see the runner's own.
            and (env.get("CPPSTD_RUNNER_ENVIRONMENT") or env.get("RUNNER_ENVIRONMENT"))
            == "github-hosted"
            and env.get("GITHUB_REF", "") != artifact.MAIN_REF
        ):
            return Context("hosted_pr")
        return Context("actions")


def sources(
    ctx: Context, release_only: bool = False, rebuild: bool = True
) -> list[str]:
    """The source table: the sources this context may use, in order."""
    if release_only:
        return [RELEASE]
    order = [RELEASE]
    if ctx.kind == "hosted_pr":
        order.append(STAGED)
    if rebuild:
        order.append(REBUILD)
    return order


# --- the release store (D122, D134) -------------------------------------------


@dataclass(frozen=True)
class Release:
    tag: str
    title: str
    assets: tuple[str, ...]


def pick_release(tag: str, releases: list[dict]) -> Release | None:
    """The one published release of `tag`, from the full list of the repository's releases. A
    title or tag that matches more than one release is refused (D122); drafts never count (D131)."""
    hits = [
        r
        for r in releases
        if not r.get("draft") and tag in (r.get("name"), r.get("tag_name"))
    ]
    if len(hits) > 1:
        raise Refused(
            f"{len(hits)} releases match {tag}: "
            + ", ".join(f"{r.get('tag_name')} ({r.get('name')})" for r in hits)
        )
    if not hits:
        return None
    r = hits[0]
    if r.get("tag_name") != tag or r.get("name") != tag:
        raise Refused(
            f"release {r.get('tag_name')} is titled {r.get('name')}; both must be {tag}"
        )
    return Release(tag, r["name"], tuple(a["name"] for a in r.get("assets", [])))


class GhReleases:
    """GitHub Releases through the gh CLI (GH_TOKEN in Actions, the owner's login outside)."""

    def __init__(self, repo: str = REPO) -> None:
        self.repo = repo

    def find(self, tag: str) -> Release | None:
        # Every page (D122): an exact match outside the newest page still counts.
        try:
            out = subprocess.run(
                [
                    "gh",
                    "api",
                    "--paginate",
                    "--slurp",
                    f"repos/{self.repo}/releases?per_page=100",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            pages = json.loads(out)
        except subprocess.CalledProcessError as e:
            raise SourceError(
                f"gh api could not list the releases of {self.repo}: {e.stderr.strip()} "
                "(no token? run gh auth login or set GH_TOKEN)"
            ) from e
        except FileNotFoundError as e:
            raise SourceError("gh is not on PATH") from e
        except json.JSONDecodeError as e:
            raise SourceError(f"gh api returned no release list: {e}") from e
        return pick_release(tag, [r for page in pages for r in page])

    def download(self, release: Release, asset: str, dest: Path) -> Path:
        subprocess.run(
            [
                "gh",
                "release",
                "download",
                release.tag,
                "--repo",
                self.repo,
                "--pattern",
                asset,
                "--dir",
                str(dest),
                "--clobber",
            ],
            check=True,
        )
        return dest / asset


def gh_verify_report(path: Path) -> tuple[bool, str]:
    """`gh attestation verify` of a release archive, the policy every main image is held to:
    whether it passed, and gh's output (the must-fail fixture checks why it was refused)."""
    cmd = ["gh", "attestation", "verify", str(path), *artifact.verify_flags()]
    print("+ " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, check=False, capture_output=True, text=True)
    out = r.stdout + r.stderr
    print(out, end="", flush=True)
    return r.returncode == 0, out


def gh_verify(path: Path) -> bool:
    return gh_verify_report(path)[0]


# --- installing ---------------------------------------------------------------


def tag_hash(tag: str) -> str:
    m = TAG.fullmatch(tag)
    if not m:
        raise FetchError(f"not a toolchain tag: {tag}")
    return m["hash"]


# The platform's call; coverage counts neither arm, so the floor is the same on Linux and macOS
# (tests/toolchain/ calls _exchange directly on whichever platform runs them).
if sys.platform == "linux":  # pragma: no cover

    def _exchange_call(libc, a: bytes, b: bytes) -> int:
        fn = libc.renameat2
        fn.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        return fn(AT_FDCWD, a, AT_FDCWD, b, RENAME_EXCHANGE)

else:  # pragma: no cover

    def _exchange_call(libc, a: bytes, b: bytes) -> int:
        fn = libc.renamex_np
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        return fn(a, b, RENAME_SWAP)


def _exchange(a: Path, b: Path) -> None:
    """Swap two paths atomically: renameat2(RENAME_EXCHANGE) on Linux, renamex_np(RENAME_SWAP)
    on macOS. Used once per root, to turn an older install's real directory at `<root>/<tag>`
    into the symlink with no moment where that path is missing."""
    libc = ctypes.CDLL(None, use_errno=True)
    if _exchange_call(libc, os.fsencode(a), os.fsencode(b)) != 0:
        err = ctypes.get_errno()
        raise OSError(err, f"exchange {a} <-> {b}: {os.strerror(err)}")


def _switch(dest: Path, target_name: str) -> Path | None:
    """Point the symlink `dest` at `target_name` (a sibling directory) atomically; return the
    directory it pointed at before (to remove), or None. A real directory at `dest`, left by an
    older install, is swapped out with `_exchange` and returned for removal; if the swap is not
    possible, it is left in place and the switch fails, so `dest` never goes missing."""
    link = dest.parent / f".{dest.name}.link-{uuid.uuid4().hex}"
    os.symlink(target_name, link)
    try:
        if dest.is_symlink() or not dest.exists():
            previous = dest.parent / os.readlink(dest) if dest.is_symlink() else None
            os.replace(link, dest)
            return previous
        # An older install's real directory: swap it with the new link in one step.
        _exchange(link, dest)
        legacy = dest.parent / f".{dest.name}.legacy-{uuid.uuid4().hex}"
        os.rename(link, legacy)  # `link` now names the old directory
        return legacy
    finally:
        if link.is_symlink():
            link.unlink()


@contextlib.contextmanager
def _locked(root: Path, tag: str):
    """One writer per tag and root at a time (fcntl lock file under root)."""
    with open(root / f".{tag}.lock", "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def install(archive: Path, tag: str, root: Path) -> Path:
    """Install `archive` as `root/<tag>`, a symlink to an immutable sibling directory
    `root/.<tag>.<unique>`. The archive is extracted into that new directory and its
    inputs-hash.txt checked before the symlink is switched (an atomic os.replace), and the
    directory it pointed at before is removed only after the switch. So `root/<tag>` always
    resolves to a complete install, the old one or the new one, also when the process is killed
    at any point; a refused archive never becomes the target. Writers of the same tag are
    serialized by a lock file; leftovers of a killed writer are removed by the next one."""
    root.mkdir(parents=True, exist_ok=True)
    dest = root / tag
    with _locked(root, tag):
        _sweep(root, tag, keep=_target(dest))
        new = Path(tempfile.mkdtemp(prefix=f".{tag}.", dir=root))
        try:
            r = subprocess.run(
                [
                    "tar",
                    "--zstd",
                    "--no-same-owner",
                    "--no-same-permissions",
                    "-xf",
                    str(archive),
                    "-C",
                    str(new),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                raise Refused(f"{archive.name} does not extract: {r.stderr.strip()}")
            hash_file = new / HASH_FILE
            got = hash_file.read_text().strip() if hash_file.is_file() else None
            if got != tag_hash(tag):
                raise Refused(
                    f"{archive.name}: {HASH_FILE} is {got!r}, the tag's hash is {tag_hash(tag)}"
                )
            # mkdtemp makes the directory 0700; the installed prefix is read by other users too.
            new.chmod(0o755)
            previous = _switch(dest, new.name)
        except BaseException:
            # Never remove what `dest` already points at: after a successful exchange of an
            # older real directory, a later step of _switch can still fail with the switch made.
            current = _target(dest)
            if current is None or current.name != new.name:
                shutil.rmtree(new, ignore_errors=True)
            raise
        if previous is not None and previous.name != new.name:
            if _ours(previous, root, tag):
                shutil.rmtree(previous, ignore_errors=True)
            else:  # a link made by hand or another tool: never delete what it pointed at
                print(
                    f"{tag}: left the previous target {previous} in place",
                    file=sys.stderr,
                )
    return dest


def _ours(path: Path, root: Path, tag: str) -> bool:
    """Whether `path` is an install directory this module made: `<root>/.<tag>.*`."""
    return (
        os.path.abspath(path.parent) == os.path.abspath(root)
        and path.name.startswith(f".{tag}.")
        and path.name != f".{tag}.lock"
    )


def _target(dest: Path) -> Path | None:
    return dest.parent / os.readlink(dest) if dest.is_symlink() else None


def _sweep(root: Path, tag: str, keep: Path | None) -> None:
    """Remove what a killed writer of `tag` left: every `.<tag>.*` entry but the lock file and
    the current target. Called under the lock, so no other writer is mid-install."""
    for p in root.glob(f".{tag}.*"):
        if p.name == f".{tag}.lock" or (keep is not None and p.name == keep.name):
            continue
        if p.is_symlink() or p.is_file():
            p.unlink(missing_ok=True)
        else:
            shutil.rmtree(p, ignore_errors=True)


# --- the fetch ----------------------------------------------------------------


@dataclass
class Result:
    prefix: Path | None = None
    source: str | None = None
    refusals: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def fetch(
    tag: str,
    root: Path,
    order: list[str],
    releases,
    verifier: Callable[[Path], bool],
    rebuild: Callable[[str], Path],
    staged_dir: Path,
    log: Callable[[str], None] = print,
    stop_on_source_error: bool = False,
) -> Result:
    """Install `tag` under `root` from the first source of `order` that passes its checks. When
    the release source cannot be asked, `stop_on_source_error` (outside Actions) stops there;
    otherwise the next source is tried after a warning."""
    result = Result()
    archive_name = f"{tag}.tar.zst"
    for source in order:
        try:
            if source == RELEASE:
                rel = releases.find(tag)
                if rel is None:
                    log(f"{tag}: no release")
                    continue
                if archive_name not in rel.assets:
                    raise Refused(f"release {tag} has no {archive_name}")
                with tempfile.TemporaryDirectory() as d:
                    path = releases.download(rel, archive_name, Path(d))
                    if not verifier(path):
                        raise Refused(
                            f"release {tag}: the attestation of {archive_name} is not "
                            f"publish.yml on {artifact.MAIN_REF}"
                        )
                    result.prefix = install(path, tag, root)
            elif source == STAGED:
                path = staged_dir / tag / archive_name
                if not path.is_file():
                    log(f"{tag}: no staged copy at {path}")
                    continue
                result.prefix = install(path, tag, root)
            elif source == REBUILD:
                log(f"{tag}: rebuilding")
                result.prefix = install(rebuild(tag), tag, root)
            else:
                raise FetchError(f"unknown source {source}")
        except Refused as e:
            result.refusals.append(f"{source}: {e}")
            log(f"REFUSED ({source}): {e}")
            continue
        except SourceError as e:
            result.errors.append(f"{source}: {e}")
            if stop_on_source_error:
                log(f"ERROR ({source}): {e}; stopping, no rebuild")
                return result
            log(f"::warning::{tag}: the {source} could not be asked: {e}")
            continue
        except (subprocess.CalledProcessError, OSError) as e:
            log(f"{tag}: {source} failed: {e}")
            continue
        result.source = source
        log(f"installed {tag} from the {source} at {result.prefix}")
        return result
    return result


# --- command line -------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def host_arch() -> str:
    machine = platform.machine().lower()
    arches = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}
    if machine not in arches:
        raise FetchError(f"no toolchain for machine {machine}; pass --arch")
    return arches[machine]


def default_root(env: dict[str, str]) -> Path:
    data = env.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(data) / "cpp-standard/toolchains"


def compute_tag(name: str, os_name: str, arch: str, root: Path = ROOT) -> str:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(root / "python/pins/pins.py"),
            "tag",
            f"{name}-{os_name}-{arch}",
            "--root",
            str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def mise_rebuild(tag: str) -> Path:
    """`mise run artifact:build <name>-<os>-<arch>`: dist/<tag>/<tag>.tar.zst."""
    m = TAG.fullmatch(tag)
    assert m
    subprocess.run(
        ["mise", "run", "artifact:build", f"{m['name']}-{m['os']}-{m['arch']}"],
        check=True,
        cwd=ROOT,
    )
    return ROOT / "dist" / tag / f"{tag}.tar.zst"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="toolchain-fetch")
    p.add_argument("name", nargs="?", default="p2996")
    p.add_argument("--os", default="linux", choices=["linux", "macos"])
    p.add_argument("--arch", choices=["arm64", "amd64"])
    p.add_argument("--root", type=Path, help="install root (default: XDG data dir)")
    p.add_argument(
        "--release-only", action="store_true", help="no staged copy, no rebuild"
    )
    p.add_argument("--no-rebuild", action="store_true", help="never rebuild")
    p.add_argument("--staged-dir", type=Path, default=ROOT / ".cache/toolchains")
    args = p.parse_args(argv)
    env = dict(os.environ)
    ctx = Context.from_env(env)
    try:
        tag = compute_tag(
            args.name, args.os, args.arch or host_arch()
        )  # Linux until M3
        order = sources(ctx, args.release_only, not args.no_rebuild)
        print(f"{tag}: {ctx.kind}, sources {', '.join(order)}", flush=True)
        r = fetch(
            tag,
            args.root or default_root(env),
            order,
            GhReleases(),
            gh_verify,
            mise_rebuild,
            args.staged_dir,
            stop_on_source_error=ctx.kind == "outside",
        )
    except (FetchError, subprocess.CalledProcessError) as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    if r.prefix is None:
        why = f": {'; '.join(r.errors)}" if r.errors else ""
        print(
            f"FAIL: {tag} not installed from {', '.join(order)}{why}", file=sys.stderr
        )
        return 1
    lines = f"prefix={r.prefix}\nsource={r.source}\ntag={tag}\n"
    sys.stdout.write(lines)
    if path := env.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
