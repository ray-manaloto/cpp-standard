"""Artifact names, the artifact wait, image resolution and image verification (M1a PR 2),
and the registry pull a toolchain fetch needs (#254).

environment-standard.md section 2 and the file plan rows of `artifact:names`,
`artifact:check` and `image:verify`; D54, D61, D62, D98, D114, D134, #254. Standard-library
Python 3.11 or later only, like python/pins/pins.py, so the `artifact-check` and `resolve`
jobs install nothing.

The registry and the verifier are passed in, so tests/artifact/ runs every case of the wait
and of `resolve` with no network, Docker or GitHub.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO = "ray-manaloto/cpp-standard"
REGISTRY = "ghcr.io"
# GHCR packages (D98, #254): ghcr.io/ray-manaloto/cpp-standard/{base,tools}.
# Toolchain images have their full artifact tag in the public tools package.
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
        # The public tools package gives an explicit manifest miss before the first build.
        # Only main publishes toolchain tags. A PR's staged build stays in actions/cache (D91).
        image = f"{IMAGE_PREFIX}/tools"
        return {
            "kind": "toolchain",
            "image": image,
            "image_tag": tag,
            "ref": f"{image}:{tag}",
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
            for attempt in range(self.RETRIES + 1):
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        token = json.load(resp)["token"]
                    break
                except urllib.error.HTTPError as exc:
                    exc.close()
                    if (exc.code < 500 and exc.code != 429) or attempt == self.RETRIES:
                        raise ArtifactError(
                            f"registry token request for {path}: HTTP {exc.code}"
                        ) from exc
                except (OSError, http.client.HTTPException) as exc:
                    if attempt == self.RETRIES:
                        raise ArtifactError(
                            f"registry token request for {path} failed"
                        ) from exc
                except (ValueError, KeyError, TypeError) as exc:
                    raise ArtifactError(
                        f"registry token request for {path}: invalid token response"
                    ) from exc
                time.sleep(5 * (attempt + 1))
            if not isinstance(token, str) or not token:
                raise ArtifactError(
                    f"registry token request for {path}: no bearer token"
                )
            self._bearer[path] = token
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
                    digest = resp.headers.get("Docker-Content-Digest", "")
                    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                        raise ArtifactError(
                            f"registry probe of {ref}: missing or invalid digest"
                        )
                    return digest
            except urllib.error.HTTPError as e:
                e.close()
                if e.code == 404:
                    return None
                if e.code == 401 and not fresh:
                    fresh = True
                    continue
                if (e.code < 500 and e.code != 429) or attempt == self.RETRIES:
                    raise ArtifactError(
                        f"registry probe of {ref}: HTTP {e.code}"
                    ) from e
            except (OSError, http.client.HTTPException) as e:
                if attempt == self.RETRIES:
                    raise ArtifactError(f"registry probe of {ref}: {e}") from e
            fresh = False
            time.sleep(5 * (attempt + 1))
        raise ArtifactError(f"registry probe of {ref}: no answer")

    def manifest_bytes(self, ref: str) -> bytes | None:
        """The exact manifest bytes of `ref` (`image:tag` or `image@sha256:<digest>`), or None only for
        "not found"; any other answer is an error (the probe rule, D90). Same retries as
        `digest`, the 401 answered with a fresh pull token first."""
        if "@" in ref:
            image, _, selector = ref.rpartition("@")
        else:
            image, _, selector = ref.rpartition(":")
        path = image.removeprefix(f"{REGISTRY}/")
        fresh = False
        for attempt in range(self.RETRIES + 1):
            req = urllib.request.Request(
                f"https://{REGISTRY}/v2/{path}/manifests/{selector}"
            )
            req.add_header("Accept", ",".join(MANIFEST_TYPES))
            try:
                req.add_header(
                    "Authorization", f"Bearer {self._bearer_for(path, fresh)}"
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                e.close()
                if e.code == 404:
                    return None
                if e.code == 401 and not fresh:
                    fresh = True
                    continue
                if (e.code < 500 and e.code != 429) or attempt == self.RETRIES:
                    raise ArtifactError(f"registry pull of {ref}: HTTP {e.code}") from e
            except (OSError, http.client.HTTPException) as e:
                if attempt == self.RETRIES:
                    raise ArtifactError(f"registry pull of {ref}: {e}") from e
            fresh = False
            time.sleep(5 * (attempt + 1))
        raise ArtifactError(f"registry pull of {ref}: no answer")

    def blob(self, ref: str, digest: str, dest: Path) -> Path:
        """The blob `sha256:<digest>` of the repository `ref` names (`image:tag` or
        `image@sha256:<digest>`), streamed to `dest`. Same probe rule and retries."""
        image = ref.rpartition("@")[0] if "@" in ref else ref.rpartition(":")[0]
        path = image.removeprefix(f"{REGISTRY}/")
        fresh = False
        for attempt in range(self.RETRIES + 1):
            req = urllib.request.Request(f"https://{REGISTRY}/v2/{path}/blobs/{digest}")
            try:
                # GHCR can redirect blobs to signed object storage URLs.
                req.add_unredirected_header(
                    "Authorization", f"Bearer {self._bearer_for(path, fresh)}"
                )
                with (
                    urllib.request.urlopen(req, timeout=600) as resp,
                    open(dest, "wb") as f,
                ):
                    shutil.copyfileobj(resp, f)
                return dest
            except urllib.error.HTTPError as e:
                e.close()
                if e.code == 404:
                    raise ArtifactError(
                        f"registry pull of {ref}: no blob {digest}"
                    ) from e
                if e.code == 401 and not fresh:
                    fresh = True
                    continue
                if (e.code < 500 and e.code != 429) or attempt == self.RETRIES:
                    raise ArtifactError(f"registry pull of {ref}: HTTP {e.code}") from e
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                http.client.HTTPException,
            ) as e:
                if attempt == self.RETRIES:
                    raise ArtifactError(f"registry pull of {ref}: {e}") from e
            fresh = False
            time.sleep(5 * (attempt + 1))
        raise ArtifactError(f"registry pull of {ref}: no answer")


# --- the wait (artifact:check, D61, D62) --------------------------------------


@dataclass
class Clock:
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def candidates(tag: str, pr: int | None, mq: bool) -> list[str]:
    """Where a PR's gate jobs may take a tag from: `main`'s image, else the run's own `pr-`
    image (D54, D62, D134); for a toolchain, `main`'s image (an unattested pr- image is
    never a source, #254), else in a pull-request or merge-queue run the builder's cache
    entry on the run's ref (D83, D91)."""
    n = names(tag, pr, mq)
    if n["kind"] == "toolchain":
        return [n["ref"]] + ([f"cache {CACHE_PREFIX}{tag}"] if pr is not None else [])
    return [n["ref"]] + ([n["pr_ref"]] if "pr_ref" in n else [])


# The actions/cache key builder.yml saves a pull-request or merge-queue toolchain build under, and
# ci.yml's gate jobs restore into .cache/toolchains/<tag>/ (D83, D91).
CACHE_PREFIX = "toolchain-"


@dataclass(frozen=True)
class Found:
    """Where a tag was found: `where` names the place for the logs; `digest` is the image's
    digest when it is a registry image, so a consumer can pull exactly what was probed."""

    where: str
    digest: str | None = None


class Toolchains:
    """Whether a toolchain tag exists (#254): `main`'s image in GHCR — the probe rule: any
    registry answer other than "not found" is an error, never a "does not exist" — else, in
    a pull-request or merge-queue run, the builder run's cache entry on `ref` (D91)."""

    def __init__(self, token: str | None, ref: str | None) -> None:
        self.token = token
        self.registry = Registry(token)
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

    def where(self, tag: str) -> Found | None:
        n = names(tag)
        digest = self.registry.digest(n["ref"])
        if digest:
            return Found(f"image {n['ref']}@{digest}", digest)
        if self.ref:
            key = urllib.parse.quote(CACHE_PREFIX + tag, safe="")
            ref = urllib.parse.quote(self.ref, safe="")
            caches = self._get(f"repos/{REPO}/actions/caches?key={key}&ref={ref}") or {}
            for c in caches.get("actions_caches", []):
                if c.get("key") == CACHE_PREFIX + tag:
                    return Found(f"cache {c['key']} on {self.ref}")
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
                    log(f"found {tag}: {where.where}")
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


# The one variable the devcontainer's compose.yaml reads (D93, the file plan's .devcontainer row):
# `image:verify tools --env-file .devcontainer/.env` writes it there, and compose starts exactly
# that digest. The file is generated and gitignored; it is never committed.
DEVCONTAINER_ENV_VAR = "CPPSTD_TOOLS_IMAGE"


def write_env_file(path: str, image_at_digest: str) -> None:
    """Write `<DEVCONTAINER_ENV_VAR>=<image@digest>` to the devcontainer's generated .env file
    (D93), creating parent folders. Compose reads only this one reference back, so the image it
    starts is exactly the digest image:verify verified."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{DEVCONTAINER_ENV_VAR}={image_at_digest}\n")


def _drop_env_file(path: str | None) -> None:
    """The devcontainer starts compose only from the env file image:verify wrote (D93): a refusal
    removes any stale one, so a digest no verification backed cannot survive to compose."""
    if path:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def verify(
    image: str,
    registry: Registry,
    verifier: Callable[[str], bool],
    env_file: str | None = None,
) -> str:
    """image:verify (the D114 policy of gh_verify) with the devcontainer's env file (D93): a tag
    is looked up by digest, image@digest is held to the policy, and with env_file the verified
    reference is written there. Returns image@sha256:<digest>; any failure, a refusal or a probe
    error alike, names the image and leaves no env file behind."""
    try:
        if "@" not in image:
            digest = registry.digest(image)
            if not digest:
                raise ArtifactError(f"{image} does not exist")
            image = f"{image.rpartition(':')[0]}@{digest}"
        if not verifier(image):
            raise ArtifactError(f"{image}: attestation refused")
    except ArtifactError:
        _drop_env_file(env_file)
        raise
    if env_file:
        write_env_file(env_file, image)
    return image


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
    v.add_argument(
        "--env-file",
        help="write CPPSTD_TOOLS_IMAGE=<image@digest> there after verification"
        " (the devcontainer's generated .devcontainer/.env, D93)",
    )
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
            # A toolchain: main's image, the probe rule (any registry answer other than
            # "not found" fails the caller's job, #254), or in a pull-request or merge-queue
            # run this ref's cache entry (an earlier run of the same ref already built it).
            event = os.environ.get("GITHUB_EVENT_NAME", "")
            ref = os.environ.get("GITHUB_REF") if event in PR_EVENTS else None
            where = Toolchains(_token(), ref).where(args.ref)
            _write_output(
                {
                    "exists": "true" if where else "false",
                    "where": where.where if where else "",
                    "digest": (where.digest or "") if where else "",
                }
            )
        elif args.cmd == "probe":
            digest = Registry(_token()).digest(args.ref)
            _write_output(
                {"exists": "true" if digest else "false", "digest": digest or ""}
            )
        elif args.cmd == "verify":
            image = verify(args.image, Registry(_token()), gh_verify, args.env_file)
            print(image.rpartition("@")[2])
        else:
            print(" ".join(verify_flags()))
    except ArtifactError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
