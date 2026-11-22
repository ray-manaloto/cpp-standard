"""Read native Codex hook discovery and gate a controlled plugin publication."""

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol


class HookCheckError(Exception):
    def __init__(self, reason: str, *, incomplete: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.incomplete = incomplete


@dataclass(frozen=True)
class NativeSocket:
    socket: Path
    home: Path

    def __call__(self, cwd: Path) -> dict[str, Any]:
        """Read discovery over a dedicated, already-running Unix control socket."""
        if not all(path.is_absolute() for path in (self.socket, self.home)):
            raise HookCheckError("absolute_control_context_required", incomplete=True)
        if not self.socket.is_socket():
            raise HookCheckError("control_socket_unavailable", incomplete=True)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
                return _discover(peer, self.socket, cwd, self.home)
        except (OSError, ValueError) as error:
            raise HookCheckError("native_probe_failed", incomplete=True) from error


def _discover(
    peer: socket.socket, address: Path, cwd: Path, home: Path
) -> dict[str, Any]:
    # Codex's Unix transport uses WebSocket messages, unlike stdio JSON lines.
    # Use a single bounded connection without negotiating extensions.
    deadline = monotonic() + 10
    peer.settimeout(10)
    peer.connect(str(address))
    nonce = base64.b64encode(os.urandom(16))
    peer.sendall(
        b"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: "
        + nonce
        + b"\r\n\r\n"
    )
    buffer = bytearray()

    def read(size: int) -> bytes:
        while len(buffer) < size:
            peer.settimeout(max(0.001, deadline - monotonic()))
            chunk = peer.recv(65536)
            if not chunk or monotonic() >= deadline:
                raise ValueError("incomplete control message")
            buffer.extend(chunk)
        part = bytes(buffer[:size])
        del buffer[:size]
        return part

    headers = bytearray()
    while len(headers) < 8192 and not headers.endswith(b"\r\n\r\n"):
        headers.extend(read(1))
    status, *fields = headers.split(b"\r\n")
    accept = base64.b64encode(
        hashlib.sha1(nonce + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
    )
    if not status.startswith(b"HTTP/1.1 101 ") or not any(
        name.lower() == b"sec-websocket-accept" and value.strip() == accept
        for name, _, value in (line.partition(b":") for line in fields)
    ):
        raise ValueError("control upgrade rejected")

    def send_frame(opcode: int, payload: bytes) -> None:
        size = len(payload)
        # Client messages are always below 64 KiB and must be masked.
        if size >= 65536:
            raise ValueError("control request too large")
        length = (
            bytes([128 | size]) if size < 126 else b"\xfe" + size.to_bytes(2, "big")
        )
        mask = os.urandom(4)
        peer.sendall(
            bytes([128 | opcode])
            + length
            + mask
            + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        )

    def send(method, params=None, request_id=None):
        message = {"method": method}
        if request_id is not None:
            message.update(id=request_id, params=params)
        send_frame(1, json.dumps(message).encode())

    def receive(request_id):
        while monotonic() < deadline:
            opcode, size = read(2)
            if opcode not in (0x81, 0x89, 0x8A) or size & 0x80:
                break
            if size in (126, 127):
                size = int.from_bytes(read(2 if size == 126 else 8), "big")
            if size > 4_000_000 or (opcode != 0x81 and size > 125):
                break
            payload = read(size)
            if opcode == 0x89:
                send_frame(10, payload)
            if opcode != 0x81:
                continue
            message = json.loads(payload)
            if not isinstance(message, dict):
                break
            if message.get("id") == request_id:
                result = message.get("result")
                if "error" not in message and isinstance(result, dict):
                    return result
                break
        raise HookCheckError("native_response_unavailable", incomplete=True)

    send(
        "initialize",
        {
            "clientInfo": {"name": "codex-hook-check", "version": "1"},
            "capabilities": {"experimentalApi": True},
        },
        1,
    )
    server = receive(1)
    if server.get("codexHome") != str(home):
        raise HookCheckError("control_home_mismatch", incomplete=True)
    agent = server.get("userAgent")
    if not isinstance(agent, str) or not re.match(r"^[^ /]+/0\.171\.0(?: |$)", agent):
        raise HookCheckError("control_version_unqualified", incomplete=True)
    send("initialized")
    send("config/read", {"cwd": str(cwd), "includeLayers": True}, 2)
    _check_trust_baselines(receive(2), home)
    send("hooks/list", {"cwds": [str(cwd)]}, 3)
    return receive(3)


def _check_trust_baselines(config: dict, home: Path) -> None:
    # In 0.171.0, discovery calls migrate_legacy_trust for both modern and
    # declaration-only approvals. If a baseline is absent it can write one.
    # Inspect every config layer before asking Codex to discover any hooks.
    layers = config.get("layers")
    if not isinstance(layers, list):
        raise HookCheckError("control_layers_unavailable", incomplete=True)
    user_path = home / "config.toml"
    found_user = False
    plugins = set()
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("name"), dict):
            raise HookCheckError("control_layers_unavailable", incomplete=True)
        name = layer["name"]
        if name.get("type") == "user" and name.get("profile") is None:
            if found_user or name.get("file") != str(user_path):
                raise HookCheckError("control_user_layer_mismatch", incomplete=True)
            found_user = True
        table = layer.get("config")
        if not isinstance(table, dict):
            raise HookCheckError("control_layers_unavailable", incomplete=True)
        hooks = table.get("hooks", {})
        state = hooks.get("state", {}) if isinstance(hooks, dict) else None
        if not isinstance(state, dict):
            raise HookCheckError("control_hook_state_unavailable", incomplete=True)
        for key, approval in state.items():
            if not isinstance(approval, dict):
                raise HookCheckError("control_hook_state_unavailable", incomplete=True)
            if approval.get("trusted_hash") is not None:
                plugin_id, _, _ = key.strip().partition(":")
                if "@" in plugin_id and "/" not in plugin_id:
                    plugins.add(plugin_id)
                elif approval.get("trusted_content_hash") is not None:
                    raise HookCheckError(
                        "control_hook_identity_unqualified", incomplete=True
                    )
    if not found_user:
        raise HookCheckError("control_user_layer_mismatch", incomplete=True)
    for plugin in plugins:
        identity = hashlib.sha256()
        for part in (os.fsencode(user_path), os.fsencode(plugin)):
            identity.update(len(part).to_bytes(8, "little"))
            identity.update(part)
        baseline = home / ".hook-trust" / identity.hexdigest()
        if baseline.is_symlink() or not baseline.is_file():
            raise HookCheckError("control_trust_baseline_missing", incomplete=True)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", baseline.read_text()):
            raise HookCheckError("control_trust_baseline_invalid", incomplete=True)


Probe = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class Expected:
    plugin: str
    bundle: Path
    hashes: Mapping[str, str]

    def __post_init__(self):
        if (
            not self.bundle.is_absolute()
            or not isinstance(self.plugin, str)
            or not self.plugin
            or not self.hashes
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
                for key, value in self.hashes.items()
            )
        ):
            raise HookCheckError("invalid_expected_inventory", incomplete=True)


def _inventory(probe: Probe, cwd: Path) -> dict[str, dict[str, Any]]:
    if not cwd.is_absolute() or not cwd.is_dir():
        raise HookCheckError("invalid_cwd", incomplete=True)
    result = probe(cwd)
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise HookCheckError("invalid_discovery", incomplete=True)
    scope = data[0]
    if (
        scope.get("cwd") != str(cwd)
        or scope.get("errors") != []
        or scope.get("warnings") != []
        or not isinstance(scope.get("hooks"), list)
    ):
        raise HookCheckError("incomplete_discovery", incomplete=True)
    hooks = {}
    for row in scope["hooks"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("key"), str)
            or not row["key"]
            or not isinstance(row.get("enabled"), bool)
            or "pluginId" not in row
            or not isinstance(row.get("trustStatus"), str)
            or not isinstance(row.get("currentHash"), str)
            or row["key"] in hooks
        ):
            raise HookCheckError("invalid_hook_row", incomplete=True)
        hooks[row["key"]] = row
    return hooks


def _check(hooks: dict, expected: Expected) -> None:
    selected = {
        key: row for key, row in hooks.items() if row["pluginId"] == expected.plugin
    }
    if selected.keys() != expected.hashes.keys():
        raise HookCheckError("hook_inventory_mismatch")
    for key, row in selected.items():
        if row["trustStatus"] != "trusted" or not row["enabled"]:
            raise HookCheckError("hook_not_enabled_and_trusted")
        if row["currentHash"] != expected.hashes[key]:
            raise HookCheckError("hook_hash_changed")
        path = row.get("sourcePath")
        if (
            row.get("source") != "plugin"
            or not isinstance(path, str)
            or not Path(path).is_relative_to(expected.bundle)
            or not Path(path).resolve().is_relative_to(expected.bundle.resolve())
            or not Path(path).is_file()
        ):
            raise HookCheckError("hook_source_mismatch")


def check(probe: Probe, cwd: Path, expected: Expected) -> None:
    _check(_inventory(probe, cwd), expected)


def _unrelated(hooks: dict, plugin: str) -> list[dict]:
    # Codex assigns displayOrder globally. An added hook can shift ordinals
    # without changing the relative order or contents of unrelated hooks.
    return [
        {field: value for field, value in row.items() if field != "displayOrder"}
        for row in hooks.values()
        if row["pluginId"] != plugin
    ]


def _path_chain(path: Path, *, boundary: Path | None = None) -> tuple[Path, ...]:
    """Return the entries traversed when resolving a path in filesystem order."""
    base = Path(path.anchor)
    pending = list(reversed(path.parts[1:]))
    entries: list[Path] = []
    hops = 0
    while pending:
        part = pending.pop()
        if part == "..":
            base = base.parent
            if boundary is not None and not base.is_relative_to(boundary):
                raise HookCheckError("nonportable_bundle_symlink")
            continue
        entry = base / part
        entries.append(entry)
        if not entry.is_symlink():
            base = entry
            continue
        hops += 1
        if hops > 40:
            raise HookCheckError("symlink_chain_too_deep", incomplete=True)
        target = entry.readlink()
        if target.is_absolute():
            if boundary is not None:
                raise HookCheckError("nonportable_bundle_symlink")
            base = Path(target.anchor)
            target = target.relative_to(base)
        pending.extend(reversed(target.parts))
    return tuple(entries)


@dataclass(frozen=True)
class RetainedFile:
    path: Path
    sha256: str
    mode: int

    def verify(self) -> tuple[Path, ...]:
        if not self.path.is_absolute() or not re.fullmatch(
            r"[0-9a-f]{64}", self.sha256
        ):
            raise HookCheckError("invalid_retention_receipt", incomplete=True)
        try:
            chain = _path_chain(self.path)
            if not stat.S_ISREG(self.path.stat().st_mode):
                raise HookCheckError("retained_path_not_regular")
            with self.path.open("rb") as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise HookCheckError("retained_path_not_regular")
                same = hashlib.file_digest(stream, "sha256").hexdigest() == self.sha256
        except FileNotFoundError as error:
            raise HookCheckError("retained_path_missing") from error
        except OSError as error:
            raise HookCheckError("retained_path_unreadable", incomplete=True) from error
        if metadata.st_nlink != 1:
            raise HookCheckError("retained_file_has_hardlinks", incomplete=True)
        if not same or stat.S_IMODE(metadata.st_mode) != self.mode:
            raise HookCheckError("retained_path_changed")
        return (self.path, *chain)


@dataclass(frozen=True)
class PublishPlan:
    cwd: Path
    cache_scope: Path
    stage: Expected
    live: Expected
    source: str
    revision: str
    write_roots: tuple[Path, ...]
    # Each entry covers the complete path set needed by one active/resumable session.
    # None expresses unknown inventory. An empty mapping expresses verified no dependents.
    retained: Mapping[str, tuple[RetainedFile, ...]] | None
    reviewed_root_digest: str | None = None


def _bundle_home(expected: Expected) -> Path:
    plugin, separator, marketplace = expected.plugin.partition("@")
    parts = expected.bundle.parts
    if (
        not expected.bundle.is_absolute()
        or not separator
        or len(parts) < 6
        or parts[-5:-1] != ("plugins", "cache", marketplace, plugin)
    ):
        raise HookCheckError("cache_layout_unqualified", incomplete=True)
    return expected.bundle.parents[4]


def _pinned_checkout(stage: Expected, source: str, revision: str) -> Path:
    if not source or not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", revision):
        raise HookCheckError("full_git_pin_required", incomplete=True)
    _, _, marketplace = stage.plugin.partition("@")
    checkout = _bundle_home(stage) / ".tmp/marketplaces" / marketplace
    receipt = checkout / ".codex-marketplace-install.json"
    try:
        if receipt != receipt.resolve() or not receipt.is_file():
            raise HookCheckError("install_provenance_unavailable", incomplete=True)
        metadata = json.loads(receipt.read_text())
    except (OSError, ValueError) as error:
        raise HookCheckError(
            "install_provenance_unavailable", incomplete=True
        ) from error
    if not isinstance(metadata, dict) or any(
        metadata.get(key) != value
        for key, value in {
            "source_type": "git",
            "source": source,
            "ref_name": revision,
            "revision": revision,
        }.items()
    ):
        raise HookCheckError("install_provenance_mismatch")
    return checkout


def _pinned_package(
    checkout: Path, plugin: str, revision: str
) -> tuple[Path, dict[Path, tuple[int, bytes | None]]]:
    git_dir = checkout / ".git"
    if git_dir != git_dir.resolve() or not git_dir.is_dir():
        raise HookCheckError("pinned_git_objects_unavailable", incomplete=True)
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def git(*args: str) -> bytes:
        return subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "--no-lazy-fetch",
                "--git-dir",
                str(git_dir),
                *args,
            ],
            cwd=checkout,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=10,
        ).stdout

    catalogs = (
        ".agents/plugins/marketplace.json",
        ".agents/plugins/api_marketplace.json",
        ".claude-plugin/marketplace.json",
        ".cursor-plugin/marketplace.json",
    )
    try:
        if git("cat-file", "-t", revision) != b"commit\n":
            raise HookCheckError("git_pin_not_commit")
        if (
            git("rev-parse", "--verify", f"{revision}^{{commit}}").strip()
            != revision.encode()
        ):
            raise HookCheckError("git_pin_not_exact")
        pinned_catalogs = git("ls-tree", "-z", "--name-only", revision, "--", *catalogs)
        pinned_paths = set(os.fsdecode(pinned_catalogs).split("\0"))
        manifest = next((path for path in catalogs if path in pinned_paths), None)
        if manifest is None:
            raise ValueError("missing marketplace manifest")
        catalog = json.loads(git("show", f"{revision}:{manifest}"))
        (entry,) = (entry for entry in catalog["plugins"] if entry["name"] == plugin)
        local = entry["source"]
        if isinstance(local, dict) and local.get("source") == "local":
            local = local["path"]
        relative = Path(local)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("marketplace plugin is not a local checkout directory")
        tree = (
            f"{revision}^{{tree}}"
            if relative == Path(".")
            else f"{revision}:{relative}"
        )
        entries = git("ls-tree", "-rtz", tree)
        expected = {Path("."): (stat.S_IFDIR | 0o755, None)}
        for entry in entries.split(b"\0")[:-1]:
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            path = Path(os.fsdecode(name))
            if kind == b"tree":
                expected[path] = (stat.S_IFDIR | 0o755, None)
            elif mode in (b"100644", b"100755"):
                data = git("cat-file", "blob", oid.decode("ascii"))
                expected[path] = (int(mode, 8), hashlib.sha256(data).digest())
            elif mode != b"120000":
                raise ValueError("unsupported Git tree entry")
        if len(expected) == 1:
            raise ValueError("empty Git plugin tree")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        raise HookCheckError(
            "pinned_plugin_source_unavailable", incomplete=True
        ) from error
    return relative, expected


def _bundle_snapshot(root: Path) -> dict[Path, tuple[int, bytes | None]]:
    snapshot = {}

    try:
        mode = root.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise OSError("bundle missing")
        snapshot[Path(".")] = (mode, None)
        for directory, dirs, files in os.walk(root, onerror=_raise_walk_error):
            for name in (*dirs, *files):
                path = Path(directory) / name
                mode = path.lstat().st_mode
                value = None
                if stat.S_ISLNK(mode):
                    _path_chain(path, boundary=root)
                    raise HookCheckError("unexpected_bundle_symlink")
                if stat.S_ISREG(mode):
                    with path.open("rb") as stream:
                        if os.fstat(stream.fileno()).st_nlink != 1:
                            raise HookCheckError("bundle_file_has_hardlinks")
                        value = hashlib.file_digest(stream, "sha256").digest()
                elif not stat.S_ISDIR(mode):
                    raise OSError("unexpected file type in bundle")
                snapshot[path.relative_to(root)] = (mode, value)
    except OSError as error:
        raise HookCheckError("plugin_bundle_unreadable", incomplete=True) from error
    return snapshot


def _snapshot_digest(snapshot: dict[Path, tuple[int, bytes | None]]) -> str:
    digest = hashlib.sha256()
    for path, (mode, content) in sorted(snapshot.items()):
        name = os.fsencode(path)
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(mode.to_bytes(4, "big"))
        if content is not None:
            digest.update(content)
    return digest.hexdigest()


def reviewed_root_bundle_digest(bundle: Path) -> str:
    """Record the exact independently reviewed native install of a repo-root plugin."""
    return _snapshot_digest(_bundle_snapshot(bundle))


def _check_candidate(plan: PublishPlan, candidate: dict) -> None:
    checkout = _pinned_checkout(plan.stage, plan.source, plan.revision)
    plugin, _, _ = plan.stage.plugin.partition("@")
    relative, expected = _pinned_package(checkout, plugin, plan.revision)
    if relative == Path("."):
        # Native root installs also copy generated Git and marketplace metadata.
        # The Git tree cannot establish the exact bytes of these generated files.
        if not plan.reviewed_root_digest:
            raise HookCheckError("reviewed_root_digest_required", incomplete=True)
        if _snapshot_digest(candidate) != plan.reviewed_root_digest:
            raise HookCheckError("root_bundle_differs_from_review")
        generated = {(".git",), (".codex-marketplace-install.json",)}
        candidate = {
            path: entry
            for path, entry in candidate.items()
            if path.parts[:1] not in generated
        }
    if candidate != expected:
        raise HookCheckError("staged_bundle_differs_from_pinned_source")


def _entry_identity(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    return metadata.st_dev, metadata.st_ino


def _existing_identities(paths) -> set[tuple[int, int]]:
    return {_entry_identity(path) for path in paths if path.exists()}


def _raise_walk_error(error: OSError) -> None:
    raise error


def _subtree_identities(root: Path) -> set[tuple[int, int]]:
    """Include physical identities of everything a recursive publisher could remove."""
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError:
        return set()
    identities = {_entry_identity(root)}
    if stat.S_ISDIR(mode):
        for directory, dirs, files in os.walk(root, onerror=_raise_walk_error):
            identities.update(
                _entry_identity(Path(directory) / name) for name in (*dirs, *files)
            )
    return identities


def _stage_overlaps_live(plan: PublishPlan, stage_home: Path, live_home: Path) -> bool:
    try:
        for home, other in ((stage_home, live_home), (live_home, stage_home)):
            if _existing_identities((home,)) & _existing_identities(other.parents):
                return True

        def cache_identities(bundles: tuple[Path, ...], home: Path):
            return _existing_identities(
                part
                for path in bundles
                for part in (path, *path.parents)
                if part.is_relative_to(home)
            )

        if plan.stage.bundle != plan.stage.bundle.resolve() or (
            cache_identities((plan.stage.bundle,), stage_home)
            & cache_identities((plan.live.bundle, *plan.write_roots), live_home)
        ):
            return True
        staged = _subtree_identities(stage_home)
        return bool(staged) and any(
            staged & _subtree_identities(root) for root in plan.write_roots
        )
    except OSError as error:
        raise HookCheckError("publication_roots_unreadable", incomplete=True) from error


def _retention(plan: PublishPlan) -> None:
    if plan.retained is None or any(
        not key or not files for key, files in plan.retained.items()
    ):
        raise HookCheckError("retention_inventory_unknown", incomplete=True)
    roots = (*plan.write_roots, plan.stage.bundle)
    try:
        identities = (
            set().union(*(_subtree_identities(root) for root in roots))
            if plan.retained
            else set()
        )
    except OSError as error:
        raise HookCheckError("publication_roots_unreadable", incomplete=True) from error
    for files in plan.retained.values():
        for file in files:
            # Even temporarily replacing an approved old path can strand a running hook.
            for path in file.verify():
                try:
                    overlaps = any(path.is_relative_to(root) for root in roots) or (
                        _entry_identity(path) in identities
                    )
                except OSError as error:
                    raise HookCheckError(
                        "retained_path_unreadable", incomplete=True
                    ) from error
                if overlaps:
                    raise HookCheckError("publication_overlaps_retained_path")


class PublicationProbe(Protocol):
    @property
    def home(self) -> Path: ...

    def __call__(self, cwd: Path) -> dict[str, Any]: ...


def guarded_publish(
    plan: PublishPlan,
    stage_probe: PublicationProbe,
    live_probe: PublicationProbe,
    publish: Callable[[], None],
) -> None:
    """Call a scoped publisher only after retention and candidate trust pass.

    The caller serializes writers, declares every affected root (including prunes),
    and supplies an isolated stage and the intended live control context. A raised
    error after callback entry holds restarts; publication may already have happened.
    """
    scope = plan.cache_scope
    roots = plan.write_roots
    if (
        not scope.is_absolute()
        or scope != scope.resolve()
        or not scope.is_relative_to(plan.live.bundle.parent)
        or not roots
        or any(
            root != root.resolve() or not root.is_relative_to(scope) for root in roots
        )
        or plan.live.bundle != plan.live.bundle.resolve()
        or not plan.live.bundle.is_relative_to(scope)
        or not any(plan.live.bundle.is_relative_to(root) for root in roots)
        or plan.stage.bundle != plan.stage.bundle.resolve()
        or plan.stage.bundle.is_relative_to(scope)
        or scope.is_relative_to(plan.stage.bundle)
        or plan.live.plugin != plan.stage.plugin
        or plan.live.hashes != plan.stage.hashes
        or plan.live.bundle.parts[-5:] != plan.stage.bundle.parts[-5:]
    ):
        raise HookCheckError("invalid_publication_scope", incomplete=True)
    stage_home, live_home = _bundle_home(plan.stage), _bundle_home(plan.live)
    if _stage_overlaps_live(plan, stage_home, live_home):
        raise HookCheckError("stage_overlaps_live_cache")
    if stage_probe.home != stage_home or live_probe.home != live_home:
        raise HookCheckError("publication_probe_home_mismatch", incomplete=True)
    _retention(plan)
    candidate = _bundle_snapshot(plan.stage.bundle)
    before = _inventory(live_probe, plan.cwd)
    check(stage_probe, plan.cwd, plan.stage)
    _check_candidate(plan, candidate)
    for key, digest in plan.live.hashes.items():
        previous = before.get(key)
        if (
            previous
            and previous["trustStatus"] == "trusted"
            and previous["currentHash"] != digest
        ):
            raise HookCheckError("live_approval_would_change")
    unrelated = _unrelated(before, plan.live.plugin)
    _retention(plan)
    try:
        publish()
        _retention(plan)
        if plan.live.bundle != plan.live.bundle.resolve(strict=True):
            raise HookCheckError("published_bundle_path_changed")
        if _stage_overlaps_live(plan, stage_home, live_home):
            raise HookCheckError("stage_overlaps_live_cache")
        if _bundle_snapshot(plan.live.bundle) != candidate:
            raise HookCheckError("published_bundle_differs_from_pinned_source")
        after = _inventory(live_probe, plan.cwd)
        _check(after, plan.live)
        if unrelated != _unrelated(after, plan.live.plugin):
            raise HookCheckError("unrelated_discovery_changed")
    except HookCheckError as error:
        raise HookCheckError(
            "post_publication:" + error.reason, incomplete=error.incomplete
        ) from error
    except OSError as error:
        raise HookCheckError(
            "post_publication:publication_failed", incomplete=True
        ) from error


def _check_additive_destination(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise HookCheckError("destination_already_exists")

    def stable_version(name: str) -> tuple[int, ...]:
        if not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,19})(?:\.(?:0|[1-9][0-9]{0,19})){2}", name
        ):
            raise HookCheckError("additive_version_unqualified", incomplete=True)
        parts = tuple(map(int, name.split(".")))
        if any(part >= 2**64 for part in parts):
            raise HookCheckError("additive_version_unqualified", incomplete=True)
        return parts

    try:
        with os.scandir(destination.parent) as entries:
            versions = {
                entry.name
                for entry in entries
                if entry.is_dir(follow_symlinks=False)
                and re.fullmatch(r"[A-Za-z0-9._+-]+", entry.name)
            }
    except OSError as error:
        raise HookCheckError("publication_roots_unreadable", incomplete=True) from error
    # Native 0.171.0 prefers local, then compares versions. Qualify stable
    # semantic versions only to avoid guessing native fallback ordering.
    if destination.name == "local":
        return
    if "local" in versions:
        raise HookCheckError("destination_would_be_inactive")
    wanted = stable_version(destination.name)
    if any(stable_version(version) >= wanted for version in sorted(versions)):
        raise HookCheckError("destination_would_be_inactive")


def publish_bundle(
    plan: PublishPlan, stage_probe: PublicationProbe, live_probe: PublicationProbe
) -> None:
    """Publish an additive version directory under the caller's exclusive writer lock."""
    if plan.write_roots != (plan.live.bundle,):
        raise HookCheckError(
            "additive_publication_requires_one_version", incomplete=True
        )

    _check_additive_destination(plan.live.bundle)

    def move():
        _check_additive_destination(plan.live.bundle)
        plan.stage.bundle.rename(plan.live.bundle)

    guarded_publish(plan, stage_probe, live_probe, move)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only native discovery for one Codex plugin."
    )
    for flag in ("socket", "home", "cwd", "expect"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    try:
        spec = json.loads(args.expect.read_text())
        expected = Expected(spec["plugin"], Path(spec["bundle"]), spec["hashes"])
        check(NativeSocket(args.socket, args.home), args.cwd, expected)
    except HookCheckError as error:
        print(json.dumps({"runtime": "NOT_RUN", "reason": error.reason}))
        return 2 if error.incomplete else 1
    except (OSError, TypeError, AttributeError, ValueError, KeyError):
        print(json.dumps({"runtime": "NOT_RUN", "reason": "unreadable_expectation"}))
        return 2
    print(
        json.dumps(
            {"runtime": "NOT_RUN", "discovery": "pass", "hooks": len(expected.hashes)}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
