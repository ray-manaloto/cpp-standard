"""Artifact names, the artifact wait, image resolution and image verification (M1a PR 2).

environment-standard.md section 2 and the file plan rows of `artifact:names`, `artifact:check`
and `image:verify`; D54, D61, D62, D98, D114, D134. Standard-library Python 3.11 or later only,
like python/pins/pins.py, so the `artifact-check` and `resolve` jobs install nothing.

The registry and the verifier are passed in, so tests/artifact/ runs every case of the wait and
of `resolve` with no network, Docker or GitHub.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

REPO = "ray-manaloto/cpp-standard"
REGISTRY = "ghcr.io"
# GHCR packages (D98): ghcr.io/ray-manaloto/cpp-standard/{base,tools}.
IMAGE_PREFIX = f"{REGISTRY}/{REPO}"
PUBLISHER = f"{REPO}/.github/workflows/publish.yml"
MAIN_REF = "refs/heads/main"

IMAGE_TAG = re.compile(
    r"(?P<kind>base|tools)-(?P<arch>arm64|amd64)-(?P<hash>[0-9a-f]{16})"
)
TOOLCHAIN_TAG = re.compile(
    r"(?P<name>[a-z0-9][a-z0-9-]*)-(?P<os>linux|macos)-(?P<arch>arm64|amd64)-(?P<hash>[0-9a-f]{16})"
)
QUEUE_REF = re.compile(r"refs/heads/gh-readonly-queue/[^/]+/pr-(?P<n>[0-9]+)-[0-9a-f]+")
PULL_REF = re.compile(r"refs/pull/(?P<n>[0-9]+)/merge")
PR_EVENTS = ("pull_request", "merge_group")
MANIFEST_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)


class ArtifactError(Exception):
    pass


# --- names (artifact:names, D98) ----------------------------------------------


def names(tag: str, pr: int | None = None, mq: bool = False) -> dict[str, str]:
    """The names of one artifact tag. Without `pr`, exactly what publish.yml computes inline
    for `main` (tests/artifact/ checks that the two agree); with `pr`, also the PR image tag
    (`pr-<n>-<arch>-<hash>`, or `pr-<n>-mq-<arch>-<hash>` in the merge queue, D134)."""
    if m := IMAGE_TAG.fullmatch(tag):
        image = f"{IMAGE_PREFIX}/{m['kind']}"
        out = {
            "kind": "image",
            "image": image,
            "image_tag": f"{m['arch']}-{m['hash']}",
            "ref": f"{image}:{m['arch']}-{m['hash']}",
        }
        if pr is not None:
            pr_tag = f"pr-{pr}-{'mq-' if mq else ''}{m['arch']}-{m['hash']}"
            out |= {"pr_tag": pr_tag, "pr_ref": f"{image}:{pr_tag}"}
        return out
    if TOOLCHAIN_TAG.fullmatch(tag):
        # D134: in M1a a toolchain release's git tag and title are its artifact tag.
        return {
            "kind": "toolchain",
            "release_tag": tag,
            "release_title": tag,
            "archive": f"{tag}.tar.zst",
        }
    raise ArtifactError(f"not an artifact tag: {tag}")


def pr_from_ref(event: str, ref: str) -> tuple[int | None, bool]:
    """The PR number and whether the run is in the merge queue, from GITHUB_REF."""
    if event == "merge_group" and (m := QUEUE_REF.fullmatch(ref)):
        return int(m["n"]), True
    if event == "pull_request" and (m := PULL_REF.fullmatch(ref)):
        return int(m["n"]), False
    if event in PR_EVENTS:
        raise ArtifactError(f"no PR number in {ref} for a {event} run")
    return None, False


# --- the registry -------------------------------------------------------------


class Registry:
    """GHCR manifests by tag. `digest` returns None only for "not found"; any other answer is
    an error (the design's probe rule for the builder, D90)."""

    def __init__(self, token: str | None) -> None:
        self.token = token
        self._bearer: dict[str, str] = {}

    # Transient answers (5xx, 429, network errors) are retried this many times, a few seconds
    # apart, before the probe fails; a 401 first fetches a new pull token, which expires within
    # the 3-hour wait.
    RETRIES = 3

    def _bearer_for(self, path: str, fresh: bool = False) -> str:
        if fresh or path not in self._bearer:
            req = urllib.request.Request(
                f"https://{REGISTRY}/token?service={REGISTRY}&scope=repository:{path}:pull"
            )
            if self.token:
                basic = base64.b64encode(f"x:{self.token}".encode()).decode()
                req.add_header("Authorization", f"Basic {basic}")
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._bearer[path] = json.load(resp)["token"]
        return self._bearer[path]

    def digest(self, ref: str) -> str | None:
        image, _, tag = ref.rpartition(":")
        path = image.removeprefix(f"{REGISTRY}/")
        fresh = False
        for attempt in range(self.RETRIES + 1):
            req = urllib.request.Request(
                f"https://{REGISTRY}/v2/{path}/manifests/{tag}", method="HEAD"
            )
            req.add_header("Accept", ",".join(MANIFEST_TYPES))
            try:
                req.add_header(
                    "Authorization", f"Bearer {self._bearer_for(path, fresh)}"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.headers["Docker-Content-Digest"]
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 401 and not fresh:
                    fresh = True
                    continue
                if (e.code < 500 and e.code != 429) or attempt == self.RETRIES:
                    raise ArtifactError(
                        f"registry probe of {ref}: HTTP {e.code}"
                    ) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.RETRIES:
                    raise ArtifactError(f"registry probe of {ref}: {e}") from e
            fresh = False
            time.sleep(5 * (attempt + 1))
        raise ArtifactError(f"registry probe of {ref}: no answer")


# --- the wait (artifact:check, D61, D62) --------------------------------------


@dataclass
class Clock:
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def candidates(tag: str, pr: int | None, mq: bool) -> list[str]:
    """Where a PR's gate jobs may take a tag from: `main`'s image, else the run's own `pr-`
    image (D54, D62, D134); for a toolchain, `main`'s release, else in a pull-request or
    merge-queue run the builder's cache entry on the run's ref (D83, D91)."""
    n = names(tag, pr, mq)
    if n["kind"] == "toolchain":
        return [f"release {tag}"] + (
            [f"cache {CACHE_PREFIX}{tag}"] if pr is not None else []
        )
    return [n["ref"]] + ([n["pr_ref"]] if "pr_ref" in n else [])


# The actions/cache key builder.yml saves a pull-request or merge-queue toolchain build under, and
# ci.yml's gate jobs restore into .cache/toolchains/<tag>/ (D83, D91).
CACHE_PREFIX = "toolchain-"


class Toolchains:
    """Whether a toolchain tag exists: `main`'s published release with that tag (D134), else, in a
    pull-request or merge-queue run, the builder run's cache entry on `ref` (D91)."""

    def __init__(self, token: str | None, ref: str | None) -> None:
        self.token = token
        self.ref = ref

    # Transient answers (5xx, 429, network errors) are retried, as Registry.digest does, so one
    # bad answer during a 3-hour wait does not fail the check.
    RETRIES = 3

    def _get(self, path: str) -> dict | None:
        for attempt in range(self.RETRIES + 1):
            req = urllib.request.Request(f"https://api.github.com/{path}")
            req.add_header("Accept", "application/vnd.github+json")
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if (e.code < 500 and e.code != 429) or attempt == self.RETRIES:
                    raise ArtifactError(f"GitHub API {path}: HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.RETRIES:
                    raise ArtifactError(f"GitHub API {path}: {e}") from e
            time.sleep(5 * (attempt + 1))
        raise ArtifactError(f"GitHub API {path}: no answer")

    def where(self, tag: str) -> str | None:
        rel = self._get(f"repos/{REPO}/releases/tags/{urllib.parse.quote(tag)}")
        if rel and not rel.get("draft"):
            return f"release {tag}"
        if self.ref:
            key = urllib.parse.quote(CACHE_PREFIX + tag, safe="")
            ref = urllib.parse.quote(self.ref, safe="")
            caches = self._get(f"repos/{REPO}/actions/caches?key={key}&ref={ref}") or {}
            for c in caches.get("actions_caches", []):
                if c.get("key") == CACHE_PREFIX + tag:
                    return f"cache {c['key']} on {self.ref}"
        return None


def check(
    tags: list[str],
    registry: Registry,
    pr: int | None,
    mq: bool,
    timeout: float,
    interval: float,
    clock: Clock | None = None,
    log: Callable[[str], None] = print,
    toolchains: Toolchains | None = None,
) -> list[str]:
    """Wait until every tag exists in one of its places; return the tags still missing when
    the wait ends (empty on success). It never builds anything."""
    clock = clock or Clock()
    deadline = clock.now() + timeout
    waiting = {t: candidates(t, pr, mq) for t in tags}
    while True:
        for tag in list(waiting):
            if names(tag)["kind"] == "toolchain":
                if toolchains is None:
                    raise ArtifactError(f"{tag}: no toolchain lookup given")
                if where := toolchains.where(tag):
                    log(f"found {tag}: {where}")
                    del waiting[tag]
                continue
            for ref in waiting[tag]:
                if registry.digest(ref):
                    log(f"found {tag}: {ref}")
                    del waiting[tag]
                    break
        if not waiting or clock.now() >= deadline:
            return sorted(waiting)
        log(f"waiting for {', '.join(sorted(waiting))}")
        clock.sleep(min(interval, max(0.0, deadline - clock.now())))


def missing_message(
    tag: str, pr: int | None, mq: bool, timeout: float, run: str
) -> str:
    """The failure line of the wait: the missing tag, where it was looked for and the builder
    run that should have made it (D61)."""
    return (
        f"FAIL: {tag} is still missing after {timeout:g}s "
        f"(looked for {', '.join(candidates(tag, pr, mq))}; built by {run})"
    )


# --- verification (image:verify, D114, D116) ----------------------------------


def verify_flags() -> list[str]:
    """The one policy every `main` image is checked against: a build-provenance attestation of
    this repository, signed by publish.yml running on refs/heads/main on a hosted runner."""
    return [
        "--repo",
        REPO,
        "--signer-workflow",
        PUBLISHER,
        "--source-ref",
        MAIN_REF,
        "--deny-self-hosted-runners",
    ]


def gh_verify(image_at_digest: str) -> bool:
    cmd = ["gh", "attestation", "verify", f"oci://{image_at_digest}", *verify_flags()]
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode == 0


# --- resolve (the `resolve` job, D54, D98, D134) ------------------------------


@dataclass(frozen=True)
class Resolved:
    image: str  # image@sha256:<digest>
    source: str  # "main" (attested and verified) or "pr" (the run's own, unattested)


def resolve(
    tag: str,
    event: str,
    pr: int | None,
    mq: bool,
    registry: Registry,
    verifier: Callable[[str], bool],
) -> Resolved:
    n = names(tag, pr, mq)
    if n["kind"] != "image":
        raise ArtifactError(f"{tag} is not an image")
    if digest := registry.digest(n["ref"]):
        pinned = f"{n['image']}@{digest}"
        if not verifier(pinned):
            raise ArtifactError(
                f"{pinned}: its attestation is not publish.yml on {MAIN_REF}; refused"
            )
        return Resolved(pinned, "main")
    if event not in PR_EVENTS:
        raise ArtifactError(
            f"{n['ref']} does not exist and a {event} run uses no unattested image"
        )
    if digest := registry.digest(n["pr_ref"]):
        return Resolved(f"{n['image']}@{digest}", "pr")
    raise ArtifactError(f"neither {n['ref']} nor {n['pr_ref']} exists")


# --- command line -------------------------------------------------------------


def _token() -> str | None:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def _pr_args(args: argparse.Namespace) -> tuple[int | None, bool]:
    if args.pr is not None:
        return args.pr, args.mq
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    return pr_from_ref(event, os.environ.get("GITHUB_REF", ""))


def _write_output(pairs: dict[str, str]) -> None:
    lines = "".join(f"{k}={v}\n" for k, v in sorted(pairs.items()))
    sys.stdout.write(lines)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="artifact")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("names", "check", "resolve"):
        p = sub.add_parser(name)
        p.add_argument("tag", nargs="+" if name == "check" else None)
        p.add_argument("--pr", type=int, help="PR number; default from GITHUB_REF")
        p.add_argument(
            "--mq", action="store_true", help="the run is in the merge queue"
        )
        if name == "check":
            p.add_argument("--timeout", type=float, default=180 * 60)
            p.add_argument("--interval", type=float, default=60)
        if name == "resolve":
            p.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    pr = sub.add_parser(
        "probe",
        help="exists=true|false for an image ref or a toolchain tag; any other answer fails",
    )
    pr.add_argument("ref")
    v = sub.add_parser("verify")
    v.add_argument("image", help="<image>@sha256:<digest>, or <image>:<tag> to look up")
    sub.add_parser("verify-flags")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "names":
            _write_output(names(args.tag, *_pr_args(args)))
        elif args.cmd == "check":
            pr, mq = _pr_args(args)
            # The cache entry counts only in a pull-request or merge-queue run (D91).
            ref = os.environ.get("GITHUB_REF") if pr is not None else None
            missing = check(
                args.tag,
                Registry(_token()),
                pr,
                mq,
                args.timeout,
                args.interval,
                toolchains=Toolchains(_token(), ref),
            )
            if missing:
                run = os.environ.get("BUILDER_RUN", "the builder run for this commit")
                for tag in missing:
                    print(
                        missing_message(tag, pr, mq, args.timeout, run), file=sys.stderr
                    )
                return 1
            print(f"PASS: {len(args.tag)} tag(s) exist")
        elif args.cmd == "resolve":
            pr, mq = _pr_args(args)
            r = resolve(args.tag, args.event, pr, mq, Registry(_token()), gh_verify)
            print(f"resolved {args.tag} to {r.image} ({r.source})", file=sys.stderr)
            _write_output({"image": r.image, "source": r.source})
        elif args.cmd == "probe" and TOOLCHAIN_TAG.fullmatch(args.ref):
            # A toolchain: main's release, or in a pull-request or merge-queue run this ref's
            # cache entry (an earlier run of the same ref already built it).
            event = os.environ.get("GITHUB_EVENT_NAME", "")
            ref = os.environ.get("GITHUB_REF") if event in PR_EVENTS else None
            where = Toolchains(_token(), ref).where(args.ref)
            _write_output(
                {"exists": "true" if where else "false", "where": where or ""}
            )
        elif args.cmd == "probe":
            digest = Registry(_token()).digest(args.ref)
            _write_output(
                {"exists": "true" if digest else "false", "digest": digest or ""}
            )
        elif args.cmd == "verify":
            image = args.image
            if "@" not in image:
                digest = Registry(_token()).digest(image)
                if not digest:
                    raise ArtifactError(f"{image} does not exist")
                image = f"{image.rpartition(':')[0]}@{digest}"
            if not gh_verify(image):
                raise ArtifactError(f"{image}: attestation refused")
            print(image.rpartition("@")[2])
        else:
            print(" ".join(verify_flags()))
    except ArtifactError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
