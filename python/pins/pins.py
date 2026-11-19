"""Pin validation (D51, D72) and artifact tags (D90) for cpp-standard.

The code behind `mise run pins:validate` and `mise run artifact:tag`
(environment-standard.md sections 2 and 3). Standard library only, so it runs
on any Python 3.11 or later without a virtual environment.

Subcommands:
  validate [--root DIR]                  check the pins of a tree
  tag NAME [--arch A] [--commit C]       print the artifact tag of NAME
  vectors pins|tags FILE                 run golden vectors
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- pins:validate (D51, D72, section 3) -------------------------------------

# The pin fragments under .mise/conf.d/ and the one section each may hold.
TOOLS_FRAGMENTS = ("tools.toml", "lint.toml")
APT_FRAGMENTS = ("apt.toml", "apt-toolchain-host.toml")
SOURCES_FRAGMENT = "apt-sources.toml"
PIN_FRAGMENTS = (*TOOLS_FRAGMENTS, *APT_FRAGMENTS, SOURCES_FRAGMENT)

ALLOWLIST = "pins-allowlist.toml"
LOCK = ".mise/mise.lock"
BASE_INPUTS = "image/base.inputs.toml"
# The pinned actions/runner version and its release archives (D164).
RUNNER_INPUTS = "image/runner.inputs.toml"
RUNNER_PLATFORMS = ("linux-x64", "osx-arm64")
RUNNER_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# Pins files whose schema arrives with a later milestone (vm: M3, canary: M1b).
LATER_PINS = ("vm/inputs.toml", "canary/pins.toml")

APT_SOURCE_KEYS = {"uris", "suites", "components", "key", "fingerprint"}
APT_PACKAGE_KEYS = {"version", "os"}
TOOLCHAIN_KEYS = {"upstream", "source", "host_tools", "apt_compiler", "salt", "macos"}
TOOLCHAIN_REQUIRED = {"upstream", "source", "host_tools", "apt_compiler", "salt"}
SOURCE_KEYS = {"url", "sha256", "commit"}

# Every pattern below is applied with fullmatch, so a trailing newline fails.
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX40 = re.compile(r"[0-9a-f]{40}")
FINGERPRINT = re.compile(r"[0-9A-F]{40}")
# A URL anywhere in a value, not only at its start (e.g. after a space).
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]*")
# The only URL form a pin may hold: https, a plain host and optional port, and a
# path with no backslash and no query or fragment. No userinfo, so `@` can only
# appear in the path.
STRICT_URL = re.compile(
    r"https://(?P<host>[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*)"
    r"(:[0-9]{1,5})?(/[A-Za-z0-9._~%!$&()*+,;=:@/-]*)?"
)
BASE_INPUTS_SCHEMA = {
    "image": re.compile(r"ubuntu:26\.10@sha256:[0-9a-f]{64}"),
    "mise": re.compile(r"[0-9]{4}\.[0-9]{1,2}\.[0-9]+"),
    "mise_signer": re.compile(r"ps1_[A-Za-z0-9]+"),
    "packslip_image": re.compile(r"ghcr\.io/jdx/packslip@sha256:[0-9a-f]{64}"),
}
# Toolchain pins (D51, D85): a semver-like upstream version, and for GCC on macOS
# a [macos] table whose every key has a schema. Free text (recorded host
# versions) has no `=` and starts with a letter, digit or `/`, so a flag fails.
UPSTREAM = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?")
RECORDED = re.compile(r"[A-Za-z0-9/][A-Za-z0-9 .()/_+,-]*")
ARCHIVE = re.compile(r"[a-z0-9][a-z0-9.-]*\.tar\.(gz|bz2|xz)")
MACOS_SCHEMA: dict[str, re.Pattern[str] | str] = {
    "patch_url": "url",
    "patch_sha256": HEX64,
    "homebrew_core_commit": HEX40,
    "prerequisites_url": "url",
    "prerequisites": "archives",
    # GCC's --with-zstd/--without-zstd choice is recorded here; build.sh applies it.
    "zstd": re.compile(r"with|without"),
    "make": RECORDED,
    "xcode": RECORDED,
    "sdk_major": re.compile(r"[0-9]+"),
    "bootstrap_cc": RECORDED,
    "ld": RECORDED,
}


@dataclass(frozen=True, order=True)
class Problem:
    """One failed rule: `rule` is the stable code the vectors match."""

    rule: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"FAIL [{self.rule}] {self.path}: {self.message}"


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _strings(value: Any) -> list[str]:
    """Every string anywhere in a TOML value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _version(spec: Any) -> str | None:
    """The version of a [tools] entry: a string, or a table's `version`."""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict) and isinstance(spec.get("version"), str):
        return spec["version"]
    return None


class Validator:
    """Collects the problems of one tree."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.problems: list[Problem] = []

    def fail(self, rule: str, path: str, message: str) -> None:
        self.problems.append(Problem(rule, path, message))

    def run(self) -> list[Problem]:
        allow = _load(self.root / ALLOWLIST)
        self.hosts = set(allow.get("hosts", []))
        self.tool_names = set(allow.get("tools", []))
        self.apt_names = set(allow.get("apt", []))
        self.other_fragments = set(allow.get("other_fragments", []))
        self.apt_sources = allow.get("apt_sources", {})
        self.toolchains = sorted(
            p.parent.name for p in (self.root / "toolchains").glob("*/pins.toml")
        )
        configured = self.fragments()
        self.mise_toml()
        self.lock(configured)
        self.base_inputs()
        self.runner_inputs()
        for path in sorted((self.root / "toolchains").glob("*/pins.toml")):
            self.toolchain_pins(path)
        for rel in LATER_PINS:
            if (self.root / rel).exists():
                self.fail("schema", rel, "no pins schema before its milestone")
        return sorted(set(self.problems))

    def urls(self, rel: str, data: Any) -> None:
        """D51: every URL is https from an allowlisted host."""
        for s in _strings(data):
            for m in URL.finditer(s):
                url = m.group(0)
                strict = STRICT_URL.fullmatch(url)
                if "\\" in s or not strict or strict["host"] not in self.hosts:
                    self.fail("host", rel, f"URL not an allowlisted https URL: {url}")
            if "://" in s and not URL.search(s):
                self.fail("host", rel, f"malformed URL: {s}")

    def sections(self, rel: str, data: dict[str, Any], allowed: str) -> None:
        """D51: a pin fragment holds only its one section."""
        want = tuple(allowed.split("."))
        for key, value in data.items():
            if key != want[0] or not isinstance(value, dict):
                self.fail("section", rel, f"[{key}] is not allowed; only [{allowed}]")
            elif len(want) == 2:
                for sub in value:
                    if sub != want[1]:
                        self.fail(
                            "section",
                            rel,
                            f"[{key}.{sub}] is not allowed; only [{allowed}]",
                        )

    def fragments(self) -> dict[str, str]:
        """Check each .mise/conf.d fragment; return every configured tool and version."""
        configured: dict[str, str] = {}
        conf = self.root / ".mise/conf.d"
        for path in sorted(conf.glob("*.toml")):
            rel = f".mise/conf.d/{path.name}"
            data = _load(path)
            for name, spec in data.get("tools", {}).items():
                configured[name] = _version(spec) or ""
            if path.name in TOOLS_FRAGMENTS:
                self.sections(rel, data, "tools")
                self.urls(rel, data)
                for name in data.get("tools", {}):
                    if name not in self.tool_names:
                        self.fail("name", rel, f"tool {name} is not in {ALLOWLIST}")
            elif path.name in APT_FRAGMENTS:
                self.sections(rel, data, "bootstrap.packages")
                self.urls(rel, data)
                packages = data.get("bootstrap", {}).get("packages", {})
                for name, spec in packages.items():
                    apt = name.removeprefix("apt:")
                    if name == apt or apt not in self.apt_names:
                        self.fail(
                            "name",
                            rel,
                            f"package {name} is not apt:<name> with a name in {ALLOWLIST}",
                        )
                    if isinstance(spec, dict) and not set(spec) <= APT_PACKAGE_KEYS:
                        self.fail(
                            "schema",
                            rel,
                            f"{name} holds keys other than version and os",
                        )
            elif path.name == SOURCES_FRAGMENT:
                self.sections(rel, data, "bootstrap.apt")
                sources = data.get("bootstrap", {}).get("apt", {})
                for sub in sources:
                    if sub != "sources":
                        self.fail(
                            "section", rel, f"[bootstrap.apt.{sub}] is not allowed"
                        )
                before = len(self.problems)
                for name, src in sources.get("sources", {}).items():
                    if not set(src) <= APT_SOURCE_KEYS:
                        self.fail("schema", rel, f"source {name} holds unknown keys")
                    if not FINGERPRINT.fullmatch(str(src.get("fingerprint", ""))):
                        self.fail(
                            "schema", rel, f"source {name} fingerprint is not 40 hex"
                        )
                self.urls(rel, data)
                # Each source must equal the allowlist's [apt_sources.<name>] in all five keys; a
                # source the allowlist does not name differs. Checked once the file passes the
                # shape checks above, so a failing file names one rule and still fails.
                if len(self.problems) == before:
                    for name, src in sources.get("sources", {}).items():
                        if src != self.apt_sources.get(name):
                            self.fail(
                                "source",
                                rel,
                                f"source {name} differs from [apt_sources.{name}] in {ALLOWLIST}",
                            )
            elif path.name in self.other_fragments:
                # Host fragments (D161): not pins, but every URL still comes from
                # an allowlisted https host.
                self.urls(rel, data)
            else:
                self.fail(
                    "fragment", rel, f"neither a pin fragment nor listed in {ALLOWLIST}"
                )
        return configured

    def mise_toml(self) -> None:
        """D72, D74: mise.toml holds no tools, so no toolchain version."""
        data = _load(self.root / "mise.toml")
        if "tools" in data:
            self.fail(
                "toolchain-version", "mise.toml", "[tools] is not allowed (D72, D74)"
            )

    def is_toolchain(self, tool: str) -> bool:
        tail = re.split(r"[:/]", tool)[-1]
        return tail in self.toolchains or "ray-manaloto/cpp-standard" in tool

    def lock(self, configured: dict[str, str]) -> None:
        """D51: every URL allowlisted; pins and lock agree; D72: no toolchain."""
        lock = _load(self.root / LOCK)
        self.urls(LOCK, lock)
        locked = lock.get("tools", {})
        for name, entries in locked.items():
            if self.is_toolchain(name):
                self.fail("toolchain-version", LOCK, f"{name} is a toolchain (D72)")
            elif name not in configured:
                self.fail(
                    "lock",
                    LOCK,
                    f"{name} is locked but no .mise/conf.d fragment pins it",
                )
            elif configured[name] not in [e.get("version") for e in entries]:
                self.fail(
                    "lock",
                    LOCK,
                    f"{name} pins {configured[name]} but the lock has another version",
                )
        for name in configured:
            if name not in locked:
                self.fail("lock", LOCK, f"{name} is pinned but not locked")

    def base_inputs(self) -> None:
        if not (self.root / BASE_INPUTS).exists():
            return
        data = _load(self.root / BASE_INPUTS)
        if set(data) != set(BASE_INPUTS_SCHEMA):
            self.fail(
                "inputs",
                BASE_INPUTS,
                f"keys must be exactly {sorted(BASE_INPUTS_SCHEMA)}",
            )
        for key, pattern in BASE_INPUTS_SCHEMA.items():
            if key in data and not (
                isinstance(data[key], str) and pattern.fullmatch(data[key])
            ):
                self.fail(
                    "inputs", BASE_INPUTS, f"{key} does not match {pattern.pattern}"
                )
        self.urls(BASE_INPUTS, data)

    def runner_inputs(self) -> None:
        """D164: the exact actions/runner version, and per platform only the
        release URL and its sha256. Checked when present (runner/ lands in M2)."""
        if not (self.root / RUNNER_INPUTS).exists():
            return
        data = _load(self.root / RUNNER_INPUTS)
        self.urls(RUNNER_INPUTS, data)
        if set(data) != {"version", *RUNNER_PLATFORMS}:
            self.fail(
                "inputs",
                RUNNER_INPUTS,
                f"keys must be exactly version and {', '.join(RUNNER_PLATFORMS)}",
            )
        if not RUNNER_VERSION.fullmatch(str(data.get("version", ""))):
            self.fail("inputs", RUNNER_INPUTS, "version is not an exact N.N.N")
        for platform in RUNNER_PLATFORMS:
            table = data.get(platform)
            if not isinstance(table, dict) or set(table) != {"url", "sha256"}:
                self.fail(
                    "inputs", RUNNER_INPUTS, f"{platform} holds only url and sha256"
                )
                continue
            if not STRICT_URL.fullmatch(str(table["url"])):
                self.fail(
                    "inputs", RUNNER_INPUTS, f"{platform}.url is not an https URL"
                )
            if not HEX64.fullmatch(str(table["sha256"])):
                self.fail("inputs", RUNNER_INPUTS, f"{platform}.sha256 is not 64 hex")

    def toolchain_pins(self, path: Path) -> None:
        """D51, D85: versions, URLs and checksums only; flags live in build.sh."""
        rel = path.relative_to(self.root).as_posix()
        data = _load(path)
        self.urls(rel, data)
        for key in sorted(set(data) - TOOLCHAIN_KEYS):
            self.fail(
                "inputs", rel, f"{key} is not a toolchain pin (flags live in build.sh)"
            )
        for key in sorted(TOOLCHAIN_REQUIRED - set(data)):
            self.fail("inputs", rel, f"{key} is missing")
        if not UPSTREAM.fullmatch(str(data.get("upstream", ""))):
            self.fail("inputs", rel, "upstream is not a version like 16.2.0")
        source = data.get("source", {})
        if not isinstance(source, dict) or not set(source) <= SOURCE_KEYS:
            self.fail("inputs", rel, "source holds only url, sha256 and commit")
        elif not STRICT_URL.fullmatch(str(source.get("url", ""))):
            self.fail("inputs", rel, "source.url is not an https URL")
        elif not HEX64.fullmatch(str(source.get("sha256", ""))):
            self.fail("inputs", rel, "source.sha256 is not 64 hex")
        elif "commit" in source and not HEX40.fullmatch(str(source["commit"])):
            self.fail("inputs", rel, "source.commit is not 40 hex")
        elif "commit" in source and str(source["commit"]) not in str(source["url"]):
            # The tarball must be the pinned commit's (#130): a bumped commit with a stale url
            # would build other source under the new pin.
            self.fail("inputs", rel, "source.commit is not the commit in source.url")
        self.macos(rel, data.get("macos"))
        if "apt_compiler" in data and not isinstance(data["apt_compiler"], bool):
            self.fail("inputs", rel, "apt_compiler is not true or false (D162)")
        salt = data.get("salt", 0)
        if not isinstance(salt, int) or isinstance(salt, bool):
            self.fail("inputs", rel, "salt is not an integer")
        tools = (
            _load(self.root / ".mise/conf.d/tools.toml").get("tools", {})
            if (self.root / ".mise/conf.d/tools.toml").exists()
            else {}
        )
        host_tools = data.get("host_tools", [])
        if not isinstance(host_tools, list) or not all(
            isinstance(t, str) for t in host_tools
        ):
            self.fail("inputs", rel, "host_tools is not a list of tool names")
            host_tools = []
        for tool in host_tools:
            if tool not in tools:
                self.fail("inputs", rel, f"host tool {tool} is not in tools.toml")
        for s in _strings(data):
            if s.startswith("-"):
                self.fail("inputs", rel, f"{s!r} looks like a build flag")

    def macos(self, rel: str, table: Any) -> None:
        """The GCC [macos] table (D85): each key has a schema; nothing else."""
        if table is None:
            return
        if not isinstance(table, dict):
            self.fail("inputs", rel, "[macos] is not a table")
            return
        for key, value in table.items():
            rule = MACOS_SCHEMA.get(key)
            if rule is None:
                self.fail("inputs", rel, f"macos.{key} is not a toolchain pin")
            elif rule == "url":
                ok = isinstance(value, str) and STRICT_URL.fullmatch(value)
            elif rule == "archives":
                ok = isinstance(value, list) and all(
                    isinstance(v, str) and ARCHIVE.fullmatch(v) for v in value
                )
            else:
                assert isinstance(rule, re.Pattern)
                ok = isinstance(value, str) and rule.fullmatch(value)
            if rule is not None and not ok:
                self.fail("inputs", rel, f"macos.{key} does not match its schema")


def validate(root: Path) -> list[Problem]:
    return Validator(root).run()


# --- artifact:tag (D90, section 2) -------------------------------------------

SCHEMA_LINE = "schema = 1\n"
BUILD_TASK = ".mise/tasks/artifact/build"
# Each toolchain's pins.toml says whether its build.sh bootstraps with an apt
# compiler; when true, its hash also covers apt.toml (section 2, D162).
APT_COMPILER_KEY = "apt_compiler"
APT_TOML = ".mise/conf.d/apt.toml"
RUNNER_HOOK = "runner/hook/job-started.sh"
LOCK_ARCH = {"arm64": "arm64", "amd64": "x64"}


class TagError(Exception):
    pass


class GitTree:
    """Files of one commit, read from git so no filters apply (section 2)."""

    def __init__(self, root: Path, commit: str) -> None:
        if commit.startswith("-"):
            raise TagError(f"not a commit: {commit}")
        self.root = root
        self.commit = commit

    def _git(self, *args: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        if out.returncode != 0:
            raise TagError(out.stderr.strip() or f"git {' '.join(args)} failed")
        return out.stdout

    def blob(self, path: str) -> str:
        return self._git(
            "rev-parse", "--verify", "--quiet", f"{self.commit}:{path}"
        ).strip()

    def text(self, path: str) -> str:
        return self._git("show", f"{self.commit}:{path}")

    def has(self, path: str) -> bool:
        return (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "cat-file",
                    "-e",
                    f"{self.commit}:{path}",
                ],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    def files_under(self, prefix: str) -> list[str]:
        out = self._git(
            "ls-tree", "-r", "--name-only", self.commit, "--", prefix.rstrip("/") + "/"
        )
        return [line for line in out.splitlines() if line]


def lock_slice(lock: dict[str, Any], platform: str, tools: list[str]) -> str:
    """The sha256 of the canonical JSON of the lock entries of `tools` on `platform`.

    Each entry keeps its platform-independent fields and replaces every
    `platforms.<p>` table by one `platform` field: that platform's table, or
    null. Sorted keys, no spaces.
    """
    locked = lock.get("tools", {})
    chosen: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        if tool not in locked:
            raise TagError(f"{tool} is not in {LOCK}")
        chosen[tool] = [
            {
                **{k: v for k, v in entry.items() if not k.startswith("platforms.")},
                "platform": entry.get(f"platforms.{platform}"),
            }
            for entry in locked[tool]
        ]
    canonical = json.dumps(
        chosen, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def inputs_hash(lines: dict[str, str]) -> str:
    """`schema = 1`, then the sorted `key\\0value` lines; sha256, 16 hex."""
    body = SCHEMA_LINE + "".join(sorted(f"{k}\0{v}\n" for k, v in lines.items()))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _toml(tree: GitTree, path: str) -> dict[str, Any]:
    return tomllib.loads(tree.text(path))


def _add_files(tree: GitTree, lines: dict[str, str], paths: list[str]) -> None:
    for path in paths:
        if not tree.has(path):
            raise TagError(f"input {path} is not in commit {tree.commit}")
        lines[path] = tree.blob(path)


def _add_slice(
    tree: GitTree, lines: dict[str, str], platform: str, tools: list[str]
) -> None:
    tools = sorted(tools)
    key = f"{LOCK}#{platform}:{','.join(tools)}"
    lines[key] = lock_slice(_toml(tree, LOCK), platform, tools)


def base_tag(tree: GitTree, arch: str) -> str:
    return f"base-{arch}-{inputs_hash(base_lines(tree))}"


def base_lines(tree: GitTree) -> dict[str, str]:
    lines: dict[str, str] = {}
    _add_files(
        tree,
        lines,
        [
            "image/base.Dockerfile",
            BASE_INPUTS,
            ".mise/conf.d/apt.toml",
            ".mise/conf.d/apt-toolchain-host.toml",
            ".mise/conf.d/apt-sources.toml",
            BUILD_TASK,
        ],
    )
    return lines


def tools_tag(tree: GitTree, arch: str) -> str:
    return f"tools-{arch}-{inputs_hash(tools_lines(tree, arch))}"


def tools_lines(tree: GitTree, arch: str) -> dict[str, str]:
    platform = f"linux-{LOCK_ARCH[arch]}"
    lines: dict[str, str] = {"base-tag": base_tag(tree, arch)}
    _add_files(
        tree, lines, ["image/tools.Dockerfile", ".mise/conf.d/tools.toml", BUILD_TASK]
    )
    tools = sorted(_toml(tree, ".mise/conf.d/tools.toml").get("tools", {}))
    _add_slice(tree, lines, platform, tools)
    # The PyPI sidecars the slice names (`uv = { path = ... }`, relative to .mise/).
    locked = _toml(tree, LOCK).get("tools", {})
    for tool in tools:
        for entry in locked.get(tool, []):
            sidecar = (
                entry.get("uv", {}).get("path")
                if isinstance(entry.get("uv"), dict)
                else None
            )
            if sidecar:
                files = tree.files_under(f".mise/{sidecar}")
                if not files:
                    raise TagError(
                        f"sidecar .mise/{sidecar} of {tool} is not in the commit"
                    )
                _add_files(tree, lines, files)
    return lines


def image_inputs(tree: GitTree, name: str, arch: str) -> list[str]:
    """The repository files an image's hash covers, which are all its Docker build may read
    (artifact:build puts only these in the build context). A lock slice brings in the whole
    .mise/mise.lock; the base tag line names no file."""
    if name == "base":
        lines = base_lines(tree)
    elif name == "tools":
        lines = tools_lines(tree, arch)
    else:
        raise TagError(f"{name} is not an image built by artifact:build: base or tools")
    return sorted({key.split("#", 1)[0] for key in lines if key != "base-tag"})


def toolchain_tag(tree: GitTree, name: str, os_name: str, arch: str) -> str:
    """The Linux and macOS toolchain rows of the hash-input table (section 2)."""
    base = f"toolchains/{name}"
    if not tree.has(f"{base}/pins.toml"):
        raise TagError(
            f"no toolchain {name}: {base}/pins.toml is not in commit {tree.commit}"
        )
    pins = _toml(tree, f"{base}/pins.toml")
    apt_compiler = pins.get(APT_COMPILER_KEY)
    if not isinstance(apt_compiler, bool):
        raise TagError(f"{base}/pins.toml: {APT_COMPILER_KEY} is not true or false")
    lines: dict[str, str] = {}
    _add_files(tree, lines, [f"{base}/pins.toml", f"{base}/build.sh", BUILD_TASK])
    if os_name == "linux":
        platform = f"linux-{LOCK_ARCH[arch]}"
        _add_files(
            tree,
            lines,
            [".mise/conf.d/apt-toolchain-host.toml", ".mise/conf.d/apt-sources.toml"],
        )
        _add_files(tree, lines, tree.files_under(f"{base}/linux"))
    else:
        if arch != "arm64":
            raise TagError("macOS toolchains are built for arm64 only")
        platform = "macos-arm64"
        _add_files(tree, lines, ["vm/inputs.toml"])
        _add_files(tree, lines, tree.files_under(f"{base}/macos"))
    if apt_compiler:
        _add_files(tree, lines, [APT_TOML])
    _add_slice(tree, lines, platform, pins.get("host_tools", []))
    return f"{name}-{os_name}-{arch}-{inputs_hash(lines)}"


def runner_pc_tag(tree: GitTree) -> str:
    """The PC runner image (qcow2): the tools-amd64 tag, runner/pc/**, the hook
    and the pinned actions/runner version (section 2, D164). No arch: the PC is
    amd64."""
    lines: dict[str, str] = {"tools-tag": tools_tag(tree, "amd64")}
    files = tree.files_under("runner/pc")
    if not files:
        raise TagError("runner/pc/ has no files in the commit")
    _add_files(tree, lines, files)
    _add_files(tree, lines, [RUNNER_HOOK, RUNNER_INPUTS, BUILD_TASK])
    return f"runner-pc-{inputs_hash(lines)}"


def golden_tag(tree: GitTree) -> str:
    """The Mac golden image (section 2, D164): the Tart base, the mise pin, the
    tools and their macos-arm64 lock slice, vm:golden, the hook and the pinned
    actions/runner version."""
    lines: dict[str, str] = {}
    _add_files(
        tree,
        lines,
        [
            "vm/inputs.toml",
            BASE_INPUTS,
            ".mise/conf.d/tools.toml",
            ".mise/tasks/vm/golden",
            RUNNER_HOOK,
            RUNNER_INPUTS,
            BUILD_TASK,
        ],
    )
    tools = sorted(_toml(tree, ".mise/conf.d/tools.toml").get("tools", {}))
    _add_slice(tree, lines, "macos-arm64", tools)
    return f"golden-macos-arm64-{inputs_hash(lines)}"


def artifact_tag(tree: GitTree, name: str, arch: str = "arm64") -> str:
    """The tag of `base`, `tools`, `runner-pc`, `golden` or `<toolchain>-<os>-<arch>`."""
    if name == "base":
        return base_tag(tree, arch)
    if name == "tools":
        return tools_tag(tree, arch)
    if name == "runner-pc":
        return runner_pc_tag(tree)
    if name == "golden":
        return golden_tag(tree)
    match = re.fullmatch(
        r"(?P<name>[a-z0-9][a-z0-9-]*)-(?P<os>linux|macos)-(?P<arch>arm64|amd64)", name
    )
    if not match:
        raise TagError(
            f"unknown artifact {name}: base, tools, runner-pc, golden or <toolchain>-<os>-<arch>"
        )
    return toolchain_tag(tree, match["name"], match["os"], match["arch"])


# --- golden vectors -----------------------------------------------------------


def _materialize(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _vector_files(spec: dict[str, Any], vector: dict[str, Any]) -> dict[str, str]:
    files = dict(spec["tree"])
    files.update(vector.get("change", {}))
    for rel in vector.get("remove", []):
        files.pop(rel)
    return files


def run_pin_vectors(spec: dict[str, Any]) -> list[str]:
    failures = []
    for vector in spec["vector"]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize(root, _vector_files(spec, vector))
            got = {p.rule for p in validate(root)}
        want = {vector["reject"]} if "reject" in vector else set()
        if got != want:
            failures.append(
                f"{vector['name']}: want rules {sorted(want)}, got {sorted(got)}"
            )
    return failures


GIT_ENV = {
    "GIT_AUTHOR_NAME": "v",
    "GIT_AUTHOR_EMAIL": "v@invalid",
    "GIT_COMMITTER_NAME": "v",
    "GIT_COMMITTER_EMAIL": "v@invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}


def _commit(root: Path) -> GitTree:
    env = {**os.environ, **GIT_ENV}
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["commit", "-q", "--no-verify", "-m", "v"],
    ):
        subprocess.run(
            ["git", "-C", str(root), *args], check=True, env=env, capture_output=True
        )
    return GitTree(root, "HEAD")


def run_tag_vectors(spec: dict[str, Any]) -> list[str]:
    failures = []
    baseline: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for vector in spec["vector"]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _materialize(root, _vector_files(spec, vector))
            tree = _commit(root)
            arch = vector.get("arch", "arm64")
            try:
                got = artifact_tag(tree, vector["artifact"], arch)
            except TagError as e:
                got = f"error: {e}"
            # `inputs`: the files artifact:build puts in an image's build context.
            if "inputs" in vector:
                try:
                    files = image_inputs(tree, vector["artifact"], arch)
                except TagError as e:
                    files = [f"error: {e}"]
                if files != vector["inputs"]:
                    failures.append(
                        f"{vector['name']}: want inputs {vector['inputs']}, got {files}"
                    )
        by_name[vector["name"]] = got
        key = f"{vector['artifact']}/{vector.get('arch', 'arm64')}"
        if got != vector["tag"]:
            failures.append(f"{vector['name']}: want {vector['tag']}, got {got}")
        if not vector.get("change") and not vector.get("remove"):
            baseline.setdefault(key, got)
            continue
        other = (
            by_name.get(vector["against"]) if "against" in vector else baseline.get(key)
        )
        if other is None:
            failures.append(f"{vector['name']}: nothing to compare with")
        elif vector.get("same", False) != (got == other):
            how = "differs from" if vector.get("same") else "equals"
            failures.append(f"{vector['name']}: tag {how} the vector it changes")
    return failures


# --- command line -------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pins")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--root", type=Path, default=Path.cwd())
    t = sub.add_parser("tag")
    t.add_argument("name")
    t.add_argument("--arch", choices=sorted(LOCK_ARCH), default="arm64")
    t.add_argument("--commit", default="HEAD")
    t.add_argument("--root", type=Path, default=Path.cwd())
    t.add_argument(
        "--inputs",
        action="store_true",
        help="print the files of a base or tools build context instead of the tag",
    )
    g = sub.add_parser("vectors")
    g.add_argument("kind", choices=["pins", "tags"])
    g.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        try:
            problems = validate(args.root)
        except (OSError, tomllib.TOMLDecodeError) as e:
            problems = [Problem("parse", str(getattr(e, "filename", "") or ""), str(e))]
        for p in problems:
            print(p, file=sys.stderr)
        if not problems:
            print("PASS: pins")
        return 1 if problems else 0
    if args.cmd == "tag":
        try:
            out = (image_inputs if args.inputs else artifact_tag)(
                GitTree(args.root, args.commit), args.name, args.arch
            )
        except TagError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 1
        print(out if isinstance(out, str) else "\n".join(out))
        return 0
    spec = _load(args.file)
    if not isinstance(spec.get("vector"), list) or not spec["vector"]:
        print(f"FAIL: {args.file} holds no [[vector]]", file=sys.stderr)
        return 1
    failures = (run_pin_vectors if args.kind == "pins" else run_tag_vectors)(spec)
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    if not failures:
        print(f"PASS: {len(spec['vector'])} {args.kind} vectors")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
