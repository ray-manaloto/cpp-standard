"""The coordinator's heavy-slot grants, one per host, and the Docker launch guard that reads them (#179, #194).
Standard library only.

  python -I slot.py grant <lane> <holder> [--minutes 30] [--host mac|pc]   write the host's grant; fails while
                                                                           another is active on that host
  python -I slot.py release [--holder H] [--host mac|pc]   clear the caller's grant on that host (or an expired one)
  python -I slot.py clear-expired                          clear each host's grant that has expired (coordinator
                                                           check-in)
  python -I slot.py check [--host mac|pc]                  exit 0 when this caller may start container work there now
  python -I slot.py hook                                   Claude Code PreToolUse hook: a Bash payload on stdin

--host defaults to mac. check without --host takes pc when DOCKER_HOST or DOCKER_CONTEXT aims at the PC, and
check --host mac refuses there: the tasks call check with no flag, so it follows where their Docker really goes.

Each host has its own grant, so a job on the PC does not wait behind a job on the Mac. The records are in
$XDG_STATE_HOME/slots (else ~/.local/state/slots): grant.json for the Mac and grant-pc.json for the PC, each
written atomically under one shared lock: lane, holder, host, granted_at and expires_at (UTC, ISO 8601). One grant
per host at a time. grant.json was the only record before #194, so a grant held from before reads as the Mac's.

The caller is SLOT_HOLDER, else HC_TERMINAL_ID (every herdr tab has one); with neither set, check refuses. check
passes when the host's record names the caller, has not expired, and the 5-minute load is below the start line
(SLOT_LOAD_LINE, default 9). Heavy work starts only under 9; 11 is the pause line for work already running.
Container work aimed at the PC runner host (the ssh alias `pc`, by its resolved host name), through DOCKER_HOST,
DOCKER_CONTEXT, `--context`, `-H` or `ssh <pc> docker ...`, needs the pc grant, and the load it checks is the PC's:
the 5-minute value of its /proc/loadavg and its `nproc`, over one `ssh -o BatchMode=yes pc` call. It starts only
under 0.75 x cores, 0.9 x cores is the pause line, and an ssh call that fails refuses (owner, 2026-11-18: MVP, the
PC treated like the Mac; its isolation is parked in #187). All other container work needs the mac grant.

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
HOSTS = ("mac", "pc")
LOAD_LINE = 9.0  # the start line; work already running pauses at 11 (PAUSE_LINE)
PAUSE_LINE = 11.0
# Container work that starts something heavy: run, create, build (also buildx, image build), compose up (global
# options such as --context may come before compose).
HEAVY = re.compile(
    r"\bdocker(?:\s+\S+)*?\s+(?:run|create|build|buildx\s+build|image\s+build)\b"
    r"|\bdocker(?:-compose\b|(?:\s+\S+)*?\s+compose\b)(?:\s+\S+)*?\s+up\b",
)
PRIVILEGED = re.compile(
    r"--privileged(?:=(?:true|1))?(?![=\w-])|--cap-add[=\s]+ALL\b", re.IGNORECASE
)
DOCKER = re.compile(r"\bdocker(?:-compose)?\b")
SEGMENTS = re.compile(r"&&|\|\||[;|&\n]")
# On the PC the lines scale with its cores: start under 0.75 x cores, pause at 0.9 x cores.
PC_START = 0.75
PC_PAUSE = 0.9


class RefusedError(Exception):
    """The call may not start; the message says why."""


def state_file(host: str = "mac") -> Path:
    """The host's record. The Mac keeps grant.json, the only record before #194, so an old grant reads as its."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return (
        Path(base) / "slots" / ("grant.json" if host == "mac" else f"grant-{host}.json")
    )


def other(host: str) -> str:
    return "pc" if host == "mac" else "mac"


@contextlib.contextmanager
def locked(host: str = "mac") -> Iterator[Path]:
    """Hold the one lock both records share for one read-modify-write of the host's record."""
    path = state_file(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / "grant.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def holds(holder: str, host: str) -> bool:
    """Whether holder has a live grant on host; an unreadable record counts as none."""
    try:
        record = read(state_file(host))
    except RefusedError:
        return False
    return bool(record) and record.get("holder") == holder and not expired(record)


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


def grant(lane: str, holder: str, minutes: float, host: str = "mac") -> str:
    with locked(host) as path:
        record = read(path)
        if record and not expired(record):
            msg = (
                f"the {host} slot is held by {record.get('holder')} ({record.get('lane')})"
                f" until {record.get('expires_at')}"
            )
            raise RefusedError(msg)
        start = now()
        new = {
            "lane": lane,
            "holder": holder,
            "host": host,
            "granted_at": start.isoformat(timespec="seconds"),
            "expires_at": (start + timedelta(minutes=minutes)).isoformat(
                timespec="seconds"
            ),
        }
        write(path, new)
    return f"granted the {host} slot to {holder} ({lane}) until {new['expires_at']}"


def release(holder: str, host: str = "mac") -> str:
    with locked(host) as path:
        record = read(path)
        if record is None:
            if holds(holder, other(host)):
                # Without this a holder of the other host's grant would read "no grant" and keep holding it.
                msg = (
                    f"no {host} grant to release, and {holder} holds the {other(host)} grant:"
                    f" release it with --host {other(host)}"
                )
                raise RefusedError(msg)
            return f"no {host} grant to release"
        if record.get("holder") != holder and not expired(record):
            msg = f"the {host} grant is {record.get('holder')}'s, not {holder}'s"
            raise RefusedError(msg)
        path.unlink()
    return f"released {record.get('holder')}'s {host} grant"


def clear_expired() -> str:
    """Clear every host's expired grant."""
    cleared = []
    for host in HOSTS:
        with locked(host) as path:
            record = read(path)
            if record is None or not expired(record):
                continue
            path.unlink()
        cleared.append(f"cleared {record.get('holder')}'s expired {host} grant")
    return "; ".join(cleared) or "nothing expired"


def load() -> float:
    return os.getloadavg()[1]


def pc_load() -> tuple[float, int]:
    """The PC's 5-minute load and core count, from one ssh call; any failure refuses."""
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", PC_ALIAS, "cat /proc/loadavg; nproc"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        msg = f"cannot read the PC's load over ssh: {error}"
        raise RefusedError(msg) from error
    lines = done.stdout.split("\n")
    try:
        if done.returncode != 0:
            raise ValueError(done.stderr.strip() or f"exit {done.returncode}")
        return float(lines[0].split()[1]), int(lines[1])
    except (IndexError, ValueError) as error:
        msg = f"cannot read the PC's load over ssh: {error}"
        raise RefusedError(msg) from error


def check(host: str = "mac") -> str:
    """Refuse unless the caller holds the host's live grant and that host's 5-minute load is under its line."""
    holder = caller()
    record = read(state_file(host))
    # A grant on the other host does not cover this one; say so, since the caller may think it holds "the slot".
    only = (
        f" ({holder} holds only the {other(host)} grant)"
        if holds(holder, other(host))
        else ""
    )
    if record is None:
        msg = f"no {host} slot grant{only}: ask chief-of-staff for the {host} slot"
        raise RefusedError(msg)
    if record.get("holder") != holder:
        msg = (
            f"the {host} slot is granted to {record.get('holder')}, not {holder}{only}"
        )
        raise RefusedError(msg)
    if expired(record):
        msg = f"{holder}'s {host} grant expired at {record.get('expires_at')}: ask chief-of-staff again"
        raise RefusedError(msg)
    if host == "pc":
        measured, cores = pc_load()
        line, pause, where = (
            PC_START * cores,
            PC_PAUSE * cores,
            f"the PC's ({cores} cores) ",
        )
    else:
        line = float(os.environ.get("SLOT_LOAD_LINE") or LOAD_LINE)
        measured, pause, where = load(), PAUSE_LINE, ""
    if measured >= line:
        over = (
            f", over the pause line {pause:g}"
            if measured >= pause
            else f"; the pause line is {pause:g}"
        )
        msg = (
            f"{where}5-minute load is {measured:.1f}, at or over the start line {line:g}{over}: wait for it to drop"
            " (work already running pauses at the pause line)"
        )
        raise RefusedError(msg)
    return f"{holder} may start on {host} ({where}load {measured:.1f} < {line:g}; pause line {pause:g})"


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
    """Refuse a shell command that starts container work without the live grant of the host it is aimed at, or
    under too high a load there: the pc grant and the PC's load for work aimed at the PC, else the Mac's."""
    if not DOCKER.search(command):
        return
    started = [segment for segment in SEGMENTS.split(command) if heavy(segment)]
    if not started:
        return
    aimed = [segment for segment in started if pc_reason(segment, env)]
    # No --privileged container on the PC, grant or not: one that runs apt can apply its image's kernel settings
    # to the PC itself (the agent rules' "No --privileged containers on the PC").
    if any(PRIVILEGED.search(segment) for segment in aimed):
        msg = "a --privileged container on the PC is never allowed: pass the one --device or --cap-add it needs"
        raise RefusedError(msg)
    # A command may start work in both places; each needs its own host's grant and is checked against its load.
    if aimed:
        check("pc")
    if len(aimed) < len(started):
        check("mac")


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
    except (OSError, subprocess.SubprocessError) as error:
        # ssh -G or docker context inspect could not run: block rather than let an unchecked call through.
        sys.stderr.write(f"slot guard: cannot tell where docker is aimed: {error}\n")
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    give = sub.add_parser("grant")
    give.add_argument("lane")
    give.add_argument("holder")
    give.add_argument("--minutes", type=float, default=30)
    give.add_argument("--host", choices=HOSTS, default="mac")
    give_back = sub.add_parser("release")
    give_back.add_argument("--holder")
    give_back.add_argument("--host", choices=HOSTS, default="mac")
    sub.add_parser("clear-expired")
    sub.add_parser("check").add_argument("--host", choices=HOSTS)
    sub.add_parser("hook")
    args = parser.parse_args()
    if args.action == "hook":
        hook()
        return
    try:
        if args.action == "grant":
            out = grant(args.lane, args.holder, args.minutes, args.host)
        elif args.action == "release":
            out = release(args.holder or caller(), args.host)
        elif args.action == "clear-expired":
            out = clear_expired()
        else:
            # Without --host, a caller that exported DOCKER_HOST or DOCKER_CONTEXT at the PC is doing PC work.
            aimed = pc_reason("docker", dict(os.environ))
            if aimed and args.host == "mac":
                # The mac grant must never cover Docker that this environment sends to the PC.
                msg = f"--host mac, but Docker here is aimed at the PC ({aimed}): check --host pc"
                raise RefusedError(msg)
            out = check(args.host or ("pc" if aimed else "mac"))
    except RefusedError as error:
        sys.stderr.write(f"slot: refused: {error}\n")
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"slot: refused: cannot tell where docker is aimed: {error}\n")
        sys.exit(1)
    sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
