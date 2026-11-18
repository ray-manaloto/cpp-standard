"""The coordinator's heavy-slot grant and the Docker launch guard that reads it (#179). Standard library only.

  python -I slot.py grant <lane> <holder> [--minutes 30]   write the grant; fails while another is active
  python -I slot.py release [--holder H]                   clear the caller's grant (or an expired one)
  python -I slot.py clear-expired                          clear the grant when it has expired (coordinator check-in)
  python -I slot.py check                                  exit 0 when this caller may start container work now
  python -I slot.py hook                                   Claude Code PreToolUse hook: a Bash payload on stdin

The grant record is $XDG_STATE_HOME/slots/grant.json (else ~/.local/state/slots/grant.json), written atomically
under a lock: lane, holder, granted_at and expires_at (UTC, ISO 8601). One grant at a time.

The caller is SLOT_HOLDER, else HC_TERMINAL_ID (every herdr tab has one); with neither set, check refuses. check
passes when the record names the caller, has not expired, and the 5-minute load is below the pause line
(SLOT_LOAD_LINE, default 11). Docker aimed at the PC runner host (the ssh alias `pc`, by its resolved host name),
through DOCKER_HOST, DOCKER_CONTEXT, `--context`, `-H` or `ssh <pc> docker ...`, is refused with "owner required"
whatever the grant, until the PC's credential isolation is verified.

This is an accident guard, not a security boundary: any local process can write the grant file.
Exit codes: 0 allowed or done, 1 refused, 2 usage error. hook exits 2 with the reason on stderr to block the call.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

PC_ALIAS = "pc"
LOAD_LINE = 11.0
# Container work that starts something heavy: run, create, build (also buildx, image build), compose up.
HEAVY = re.compile(
    r"\bdocker(?:\s+\S+)*?\s+(?:run|create|build|buildx\s+build|image\s+build)\b"
    r"|\bdocker(?:-compose|\s+compose)\b(?:\s+\S+)*?\s+up\b",
)
DOCKER = re.compile(r"\bdocker(?:-compose)?\b")
SEGMENTS = re.compile(r"&&|\|\||[;|&\n]")
OWNER = "owner required: {reason} reaches the PC runner host, and agent Docker there waits on credential isolation"


class RefusedError(Exception):
    """The call may not start; the message says why."""


def state_file() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "slots" / "grant.json"


@contextlib.contextmanager
def locked() -> Iterator[Path]:
    """Hold the record's lock for one read-modify-write."""
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / "grant.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def read(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        msg = f"the grant record {path} is unreadable: {error}"
        raise RefusedError(msg) from error
    if not isinstance(record, dict):
        msg = f"the grant record {path} is not an object"
        raise RefusedError(msg)
    return record


def write(path: Path, record: dict) -> None:
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=".grant.", delete=False, encoding="utf-8"
    ) as out:
        out.write(json.dumps(record) + "\n")
    Path(out.name).replace(path)


def now() -> datetime:
    return datetime.now(UTC)


def expired(record: dict) -> bool:
    try:
        return datetime.fromisoformat(record["expires_at"]) <= now()
    except (KeyError, TypeError, ValueError):
        return True


def caller() -> str:
    holder = os.environ.get("SLOT_HOLDER") or os.environ.get("HC_TERMINAL_ID")
    if not holder:
        msg = "no holder: set SLOT_HOLDER (outside herdr there is no HC_TERMINAL_ID)"
        raise RefusedError(msg)
    return holder


def grant(lane: str, holder: str, minutes: float) -> str:
    with locked() as path:
        record = read(path)
        if record and not expired(record):
            msg = f"the slot is held by {record.get('holder')} ({record.get('lane')}) until {record.get('expires_at')}"
            raise RefusedError(msg)
        start = now()
        new = {
            "lane": lane,
            "holder": holder,
            "granted_at": start.isoformat(timespec="seconds"),
            "expires_at": (start + timedelta(minutes=minutes)).isoformat(
                timespec="seconds"
            ),
        }
        write(path, new)
    return f"granted to {holder} ({lane}) until {new['expires_at']}"


def release(holder: str) -> str:
    with locked() as path:
        record = read(path)
        if record is None:
            return "no grant to release"
        if record.get("holder") != holder and not expired(record):
            msg = f"the grant is {record.get('holder')}'s, not {holder}'s"
            raise RefusedError(msg)
        path.unlink()
    return f"released {record.get('holder')}'s grant"


def clear_expired() -> str:
    with locked() as path:
        record = read(path)
        if record is None or not expired(record):
            return "nothing expired"
        path.unlink()
    return f"cleared {record.get('holder')}'s expired grant"


def load() -> float:
    return os.getloadavg()[1]


def check() -> str:
    """Refuse unless the caller holds a live grant and the 5-minute load is under the line."""
    holder = caller()
    record = read(state_file())
    if record is None:
        msg = "no slot grant: ask chief-of-staff for the heavy slot"
        raise RefusedError(msg)
    if record.get("holder") != holder:
        msg = f"the slot is granted to {record.get('holder')}, not {holder}"
        raise RefusedError(msg)
    if expired(record):
        msg = f"{holder}'s grant expired at {record.get('expires_at')}: ask chief-of-staff again"
        raise RefusedError(msg)
    line = float(os.environ.get("SLOT_LOAD_LINE") or LOAD_LINE)
    measured = load()
    if measured >= line:
        msg = f"the 5-minute load is {measured:.1f}, at or over the line {line:g}: wait for it to drop"
        raise RefusedError(msg)
    return f"{holder} may start (load {measured:.1f} < {line:g})"


def resolved_host(name: str) -> str:
    """The host name ssh would connect to for an alias or host (ssh -G reads config only, never connects)."""
    done = subprocess.run(
        ["ssh", "-G", name], capture_output=True, text=True, timeout=10, check=False
    )
    for line in done.stdout.splitlines():
        key, _, value = line.partition(" ")
        if key == "hostname":
            return value.strip().lower()
    return name.lower()


def host_of(endpoint: str) -> str | None:
    """The host of a Docker endpoint such as ssh://user@host:22 or tcp://host:2376; None for a local socket."""
    match = re.match(r"(?:ssh|tcp|https?)://(?:[^@/]+@)?(\[[^\]]+\]|[^:/]+)", endpoint)
    return match.group(1) if match else None


def context_host(name: str) -> str | None:
    fmt = "{{.Endpoints.docker.Host}}"
    done = subprocess.run(
        ["docker", "context", "inspect", name, "--format", fmt],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return host_of(done.stdout.strip()) if done.returncode == 0 else None


def is_pc(host: str | None) -> bool:
    return bool(host) and resolved_host(host) == resolved_host(PC_ALIAS)


def option(words: list[str], *names: str) -> str | None:
    for i, word in enumerate(words):
        for name in names:
            if word == name and i + 1 < len(words):
                return words[i + 1]
            if word.startswith(name + "="):
                return word.split("=", 1)[1]
    return None


def ssh_target(words: list[str]) -> str | None:
    """The destination of an `ssh ... docker ...` word list, or None when ssh is not running docker."""
    if "ssh" not in words:
        return None
    rest = words[words.index("ssh") + 1 :]
    with_value = set("BbcDEeFIiJLlmOoPpQRSWw")
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        flag = rest[i]
        i += 2 if len(flag) == 2 and flag[1] in with_value else 1
    if i >= len(rest) or not DOCKER.search(" ".join(rest[i + 1 :])):
        return None
    return rest[i].rsplit("@", 1)[-1]


def pc_reason(segment: str, env: dict[str, str]) -> str | None:
    """Why this command segment aims docker at the PC, or None."""
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    inline = dict(
        w.split("=", 1) for w in words if re.fullmatch(r"DOCKER_(HOST|CONTEXT)=\S*", w)
    )
    target = ssh_target(words)
    if target and is_pc(target):
        return f"docker over ssh to {target}"
    if not DOCKER.search(segment):
        return None
    endpoint = (
        option(words, "-H", "--host")
        or inline.get("DOCKER_HOST")
        or env.get("DOCKER_HOST")
    )
    if endpoint and is_pc(host_of(endpoint)):
        return f"DOCKER_HOST {endpoint}"
    context = (
        option(words, "--context", "-c")
        or inline.get("DOCKER_CONTEXT")
        or env.get("DOCKER_CONTEXT")
    )
    if context and is_pc(context_host(context)):
        return f"docker context {context}"
    return None


def guard_command(command: str, env: dict[str, str]) -> None:
    """Refuse a shell command that aims docker at the PC, or starts container work without a live grant."""
    if not DOCKER.search(command):
        return
    segments = SEGMENTS.split(command)
    for segment in segments:
        reason = pc_reason(segment, env)
        if reason:
            raise RefusedError(OWNER.format(reason=reason))
    if any(heavy(segment) for segment in segments):
        check()


WRAPPERS = frozenset(
    {"env", "sudo", "nohup", "time", "exec", "command", "caffeinate", "nice"}
)


def heavy(segment: str) -> bool:
    """Whether a command segment runs heavy container work: docker (or ssh running docker) as the command word,
    so `grep "docker run" notes.md` is not container work."""
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    while words and (
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", words[0]) or words[0] in WRAPPERS
    ):
        words = words[1:]
    if words[:1] == ["timeout"]:
        words = words[2:]
    if words[:1] == ["ssh"]:
        # The remote command is opaque to the word rules here; any heavy docker in it counts.
        return (
            ssh_target(words) is not None
            and HEAVY.search(" ".join(words[1:])) is not None
        )
    return (
        bool(words)
        and DOCKER.fullmatch(words[0]) is not None
        and HEAVY.search(shlex.join(words)) is not None
    )


def hook() -> None:
    try:
        payload = json.load(sys.stdin)
        command = (payload.get("tool_input") or {}).get("command") or ""
        guard_command(command, dict(os.environ))
    except RefusedError as error:
        sys.stderr.write(f"slot guard: {error}. This is an accident guard (#179).\n")
        sys.exit(2)
    except (ValueError, AttributeError) as error:
        sys.stderr.write(f"slot guard: unreadable hook payload: {error}\n")
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    give = sub.add_parser("grant")
    give.add_argument("lane")
    give.add_argument("holder")
    give.add_argument("--minutes", type=float, default=30)
    give_back = sub.add_parser("release")
    give_back.add_argument("--holder")
    sub.add_parser("clear-expired")
    sub.add_parser("check")
    sub.add_parser("hook")
    args = parser.parse_args()
    if args.action == "hook":
        hook()
        return
    try:
        if args.action == "grant":
            out = grant(args.lane, args.holder, args.minutes)
        elif args.action == "release":
            out = release(args.holder or caller())
        elif args.action == "clear-expired":
            out = clear_expired()
        else:
            refuse_pc_env()
            out = check()
    except RefusedError as error:
        sys.stderr.write(f"slot: refused: {error}\n")
        sys.exit(1)
    sys.stdout.write(out + "\n")


def refuse_pc_env() -> None:
    """check also refuses when this environment points docker at the PC (the build tasks export DOCKER_HOST)."""
    reason = pc_reason("docker", dict(os.environ))
    if reason:
        raise RefusedError(OWNER.format(reason=reason))


if __name__ == "__main__":
    main()
