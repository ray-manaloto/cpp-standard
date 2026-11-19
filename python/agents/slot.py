"""The coordinator's heavy-slot grants, one per host, and the Docker guards that read them (#179, #194).
Standard library only.

  python -I slot.py grant <lane> <holder> [--minutes 30] [--host mac|pc]   write the host's grant; fails while
                                                                           another is active on that host
  python -I slot.py release [--holder H] [--host mac|pc]   clear the caller's grant on that host (or an expired one)
  python -I slot.py clear-expired                          clear each host's grant that has expired (coordinator
                                                           check-in)
  python -I slot.py check [--host mac|pc]                  exit 0 when this caller may start container work there now
  python -I slot.py exec --real <docker> <name> <word>...  the agent-bin docker shim's verdict on one docker call
  python -I slot.py hook                                   Claude Code PreToolUse hook: a Bash payload on stdin

--host defaults to mac. check without --host takes pc when DOCKER_HOST, DOCKER_CONTEXT or the Docker CLI's current
context aims at the PC, and check --host mac refuses there: the tasks call check with no flag, so it follows where
their Docker really goes.

Each host has its own grant, so a job on the PC does not wait behind a job on the Mac. The records are in
$XDG_STATE_HOME/slots (else ~/.local/state/slots): grant.json for the Mac and grant-pc.json for the PC, each
written atomically under one shared lock: lane, holder, host, granted_at and expires_at (UTC, ISO 8601). One grant
per host at a time. grant.json was the only record before #194, so a grant held from before reads as the Mac's.

The caller is SLOT_HOLDER, else HC_TERMINAL_ID (every herdr tab has one); with neither set, check refuses. check
passes when the host's record names the caller, has not expired, and the 5-minute load is below the start line
(SLOT_LOAD_LINE, default 9). Heavy work starts only under 9; 11 is the pause line for work already running.
Container work aimed at the PC runner host (the ssh alias `pc`, by its resolved host name) needs the pc grant, and
the load it checks is the PC's: the 5-minute value of its /proc/loadavg and its `nproc`, over one
`ssh -o BatchMode=yes pc` call. It starts only under 0.75 x cores, 0.9 x cores is the pause line, and an ssh call
that fails refuses (owner, 2026-11-18: MVP, the PC treated like the Mac; its isolation is parked in #187). All
other container work needs the mac grant.

Two guards read the grants. The shim (.mise/agent-bin/docker, first on PATH in agent Bash shells) decides at exec
time from docker's real words and environment: `-H`/`--host`, `-c`/`--context`, `--config`, then DOCKER_HOST,
DOCKER_CONTEXT and the current context, in the Docker CLI's order. The hook reads the command text with two coarse
rules only: a command that names ssh and starts heavy docker needs the pc grant (owner's rule), and otherwise each
heavy segment, split at ; & | and newlines as before #194, needs its own host's grant.

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
# The hook's text match for container work that starts something heavy: run, create, build (also buildx, image
# build), compose up (global options such as --context may come before compose). The shim reads words by position
# (HEAVY_ONE, HEAVY_TWO).
HEAVY = re.compile(
    r"\bdocker(?:\s+\S+)*?\s+(?:run|create|build|buildx\s+(?:build|bake)|image\s+build)\b"
    r"|\bdocker(?:-compose\b|(?:\s+\S+)*?\s+compose\b)(?:\s+\S+)*?\s+up\b",
)
PRIVILEGED = re.compile(
    r"--privileged(?:=(?:true|1))?(?![=\w-])|--cap-add[=\s]+ALL\b", re.IGNORECASE
)
DOCKER = re.compile(r"\bdocker(?:-compose)?\b")
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
    if not record.get("holder"):
        msg = f"the grant record {path} has no holder"
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


def clear_expired() -> tuple[str, list[str]]:
    """Clear every host's expired grant. Returns what it cleared and each record it could not read, so one bad
    record does not keep the other host's expired grant in place."""
    cleared, unreadable = [], []
    for host in HOSTS:
        with locked(host) as path:
            try:
                record = read(path)
            except RefusedError as error:
                unreadable.append(str(error))
                continue
            if record is None or not expired(record):
                continue
            path.unlink()
        cleared.append(f"cleared {record.get('holder')}'s expired {host} grant")
    return "; ".join(cleared) or "nothing expired", unreadable


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
    if re.match(r"(?:unix|npipe|fd)://|/", endpoint, re.IGNORECASE):
        return None
    # Docker reads a bare host:port as tcp://host:port.
    match = re.match(
        r"(?:[a-z+]+://)?(?:[^@/]+@)?(\[[^\]]+\]|[^:/]+)", endpoint, re.IGNORECASE
    )
    return match.group(1) if match else None


# The docker that `docker context inspect` runs: the shim passes the real one, so the lookup skips the shim.
DOCKER_BIN = "docker"


def context_host(name: str) -> str | None:
    fmt = "{{.Endpoints.docker.Host}}"
    done = subprocess.run(
        [DOCKER_BIN, "context", "inspect", name, "--format", fmt],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if done.returncode != 0:
        # Docker would not start anything in a context it cannot find; neither grant fits it.
        msg = f"the docker context {name} cannot be inspected"
        raise ValueError(msg)
    return host_of(done.stdout.strip())


def is_pc(host: str | None) -> bool:
    return bool(host) and resolved_host(host) == resolved_host(PC_ALIAS)


# Docker's and compose's own options that take a value, so the word after one is not read as the subcommand.
WITH_VALUE = frozenset(
    {
        "--config",
        "-l",
        "--log-level",
        "--tlscacert",
        "--tlscert",
        "--tlskey",
        "-f",
        "--file",
        "-p",
        "--project-name",
        "--profile",
        "--env-file",
        "--project-directory",
        "--ansi",
        "--parallel",
        "--progress",
        "--builder",
    }
)
TARGETS = frozenset({"--context", "--host", "-c", "-H"})


def docker_target(words: list[str]) -> dict[str, str]:
    """Docker's --context, --host and --config as given before the subcommand (compose and buildx take them after
    their own name too). Words after the subcommand belong to the container, not to docker."""
    given: dict[str, str] = {}
    for word, value in options(words):
        name = word.partition("=")[0]
        if name in TARGETS:
            given["context" if name in {"--context", "-c"} else "host"] = value
        elif re.match(r"-[cH].", word):
            given["context" if word[1] == "c" else "host"] = word[2:].removeprefix("=")
        elif name == "--config":
            given["config"] = value
    return given


def options(words: list[str]) -> list[tuple[str, str]]:
    """Each option docker, compose or buildx gets before the subcommand, with its value ("" for a flag)."""
    out: list[tuple[str, str]] = []
    passed: set[str] = set()
    i = 0
    while i < len(words):
        word = words[i]
        if word in {"compose", "buildx"} - passed:
            passed.add(word)
            i += 1
            continue
        if not word.startswith("-") or word == "-":
            break
        name, joined, value = word.partition("=")
        if (
            not joined
            and (name in TARGETS or name in WITH_VALUE)
            and i + 1 < len(words)
        ):
            value = words[i + 1]
            i += 1
        out.append((word, value))
        i += 1
    return out


def positionals(words: list[str], limit: int = 2) -> list[str]:
    """The first plain words of a docker call, skipping options and the values they take: the subcommand path."""
    out: list[str] = []
    i = 0
    while i < len(words) and len(out) < limit:
        word = words[i]
        if word.startswith("-") and word != "-":
            takes = "=" not in word and (word in TARGETS or word in WITH_VALUE)
            i += 2 if takes else 1
            continue
        out.append(word)
        i += 1
    return out


# Main's heavy set by position: run, create, build (also through container, image, builder and buildx), compose up
# and the compose commands main's text match also took (run, create, build).
HEAVY_ONE = frozenset({"run", "create", "build"})
HEAVY_TWO = frozenset(
    {
        ("container", "run"),
        ("container", "create"),
        ("image", "build"),
        ("builder", "build"),
        ("buildx", "build"),
        ("buildx", "bake"),
        ("compose", "up"),
        ("compose", "run"),
        ("compose", "create"),
        ("compose", "build"),
    }
)


def is_heavy(words: list[str]) -> bool:
    path = positionals(words)
    return bool(path) and (path[0] in HEAVY_ONE or tuple(path) in HEAVY_TWO)


def current_context(env: dict[str, str]) -> str | None:
    """The context `docker context use` last stored in the Docker CLI's config file."""
    folder = env.get("DOCKER_CONFIG") or str(Path.home() / ".docker")
    try:
        config = json.loads((Path(folder) / "config.json").read_text(encoding="utf-8"))
        return config.get("currentContext") or None
    except (OSError, ValueError, AttributeError):
        return None


def pc_reason(given: dict[str, str], env: dict[str, str]) -> str | None:
    """Why docker with these options in this environment is aimed at the PC, or None. The order is the Docker
    CLI's own (resolveContextName in its cli/command/cli.go): --context, then --host, then DOCKER_HOST, then
    DOCKER_CONTEXT, then the current context; an empty variable counts as unset. Raises ValueError for a context
    that cannot be inspected."""
    if "config" in given:
        env = env | {"DOCKER_CONFIG": given["config"]}
    context = given.get("context")
    endpoint = None if context else given.get("host") or env.get("DOCKER_HOST")
    if not context and not endpoint:
        context = env.get("DOCKER_CONTEXT") or current_context(env)
    if context == "default":
        # The default context is DOCKER_HOST when set, else the local socket.
        context, endpoint = None, env.get("DOCKER_HOST")
    if endpoint:
        return f"DOCKER_HOST {endpoint}" if is_pc(host_of(endpoint)) else None
    if context and is_pc(context_host(context)):
        return f"docker context {context}"
    return None


def no_privileged_on_pc(text: str) -> None:
    # No --privileged container on the PC, grant or not: one that runs apt can apply its image's kernel settings
    # to the PC itself (the agent rules' "No --privileged containers on the PC").
    if PRIVILEGED.search(text):
        msg = "a --privileged container on the PC is never allowed: pass the one --device or --cap-add it needs"
        raise RefusedError(msg)


def exec_guard(name: str, words: list[str], env: dict[str, str]) -> str | None:
    """The shim's verdict on one docker call: None when it starts nothing heavy, else the check's line for the
    host the call is aimed at. Raises RefusedError to refuse."""
    if os.path.basename(name) == "docker-compose":
        words = ["compose", *words]
    if not is_heavy(words):
        return None
    try:
        aimed = pc_reason(docker_target(words), env)
    except ValueError as error:
        raise RefusedError(str(error)) from error
    if aimed:
        no_privileged_on_pc(shlex.join(words))
    return check("pc" if aimed else "mac")


# The hook's rules read the command text, coarsely: the shim decides at exec time.
SEGMENTS = re.compile(r"&&|\|\||[;|&\n]")
# ssh as a word of its own, also by its path: not --ssh, ~/.ssh or ssh://.
SSH_WORD = re.compile(r"(?:^|[\s;&|(`'\"/])ssh(?=$|[\s;&|)`'\"])")
SEGMENT_WRAPPERS = frozenset(
    {"env", "sudo", "nohup", "time", "exec", "command", "caffeinate", "nice"}
)
ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)


def segment_words(segment: str) -> tuple[dict[str, str], list[str]]:
    """A segment's leading assignments and its words from the command word on, as main read them."""
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    assigned: dict[str, str] = {}
    while words and (ASSIGNMENT.fullmatch(words[0]) or words[0] in SEGMENT_WRAPPERS):
        if found := ASSIGNMENT.fullmatch(words[0]):
            assigned[found.group(1)] = found.group(2)
        words = words[1:]
    if words[:1] == ["timeout"]:
        words = words[2:]
    return assigned, words


def heavy(segment: str) -> bool:
    """Whether a segment runs heavy container work with docker as its command word, so `grep "docker run" notes.md`
    is not container work."""
    words = segment_words(segment)[1]
    return (
        bool(words)
        and DOCKER.fullmatch(words[0]) is not None
        and HEAVY.search(shlex.join(words)) is not None
    )


def segment_reason(segment: str, env: dict[str, str]) -> str | None:
    """Why this segment's docker is aimed at the PC, or None. A context that cannot be inspected reads as not the
    PC, as on main: the shim refuses it at exec time."""
    assigned, words = segment_words(segment)
    if words[0] == "docker-compose":
        words = ["docker", "compose", *words[1:]]
    try:
        return pc_reason(docker_target(words[1:]), env | assigned)
    except ValueError:
        return None


def remote_start(command: str) -> bool:
    """Whether heavy docker follows an ssh word: what ssh may run on the far side."""
    return any(
        HEAVY.search(command, found.end()) for found in SSH_WORD.finditer(command)
    )


def guard_command(command: str, env: dict[str, str]) -> None:
    """Refuse a shell command that starts container work without the live grant of the host it is aimed at, or
    under too high a load there. Rule 1: heavy docker after an ssh word needs the pc grant; a Mac start in the same
    command is the shim's. Rule 2: main's split, each heavy segment needing the grant of the host it is aimed at.
    A docker start before the ssh word (`docker build . && ssh pc docker pull i`) is read by rule 2, as on main."""
    if not DOCKER.search(command) or not HEAVY.search(command):
        return
    if remote_start(command):
        no_privileged_on_pc(command)
        check("pc")
        return
    started = [segment for segment in SEGMENTS.split(command) if heavy(segment)]
    aimed = [segment for segment in started if segment_reason(segment, env)]
    for segment in aimed:
        no_privileged_on_pc(segment)
    # A command may start work in both places; each is checked against its own machine's load.
    if aimed:
        check("pc")
    if len(aimed) < len(started):
        check("mac")


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
        # ssh -G could not run: block rather than let an unchecked call through.
        sys.stderr.write(f"slot guard: cannot tell where docker is aimed: {error}\n")
        sys.exit(2)


def shim(args: list[str]) -> None:
    """slot.py exec --real <docker> <name> <word>...: exit 0 lets the shim exec real docker, 1 refuses. Read
    before argparse, which would take docker's own -H and --context for its options."""
    global DOCKER_BIN
    if len(args) < 3 or args[0] != "--real":
        sys.stderr.write("usage: slot.py exec --real <docker> <name> <word>...\n")
        sys.exit(2)
    DOCKER_BIN = args[1]
    try:
        exec_guard(args[2], args[3:], dict(os.environ))
    except RefusedError as error:
        sys.stderr.write(
            f"slot shim: refused: {error}. This is an accident guard (#194).\n"
        )
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as error:
        sys.stderr.write(
            f"slot shim: refused: cannot tell where docker is aimed: {error}\n"
        )
        sys.exit(1)


def main() -> None:
    if sys.argv[1:2] == ["exec"]:
        shim(sys.argv[2:])
        return
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
            out, unreadable = clear_expired()
            if unreadable:
                sys.stdout.write(out + "\n")
                raise RefusedError("; ".join(unreadable))
        else:
            # Without --host, a caller whose Docker goes to the PC (DOCKER_HOST, DOCKER_CONTEXT or the current
            # context) is doing PC work.
            aimed = pc_reason({}, dict(os.environ))
            if aimed and args.host == "mac":
                # The mac grant must never cover Docker that this environment sends to the PC.
                msg = f"--host mac, but Docker here is aimed at the PC ({aimed}): check --host pc"
                raise RefusedError(msg)
            out = check(args.host or ("pc" if aimed else "mac"))
    except (RefusedError, ValueError) as error:
        # ValueError: a docker context that cannot be inspected (verify finding 4).
        sys.stderr.write(f"slot: refused: {error}\n")
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"slot: refused: cannot tell where docker is aimed: {error}\n")
        sys.exit(1)
    sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
