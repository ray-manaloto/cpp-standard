"""The coordinator's heavy-slot grants, one per host, and the Docker launch guard that reads them (#179, #194).
Standard library only.

  python -I slot.py grant <lane> <holder> [--minutes 30] [--host mac|pc]   write the host's grant; fails while
                                                                           another is active on that host
  python -I slot.py release [--holder H] [--host mac|pc]   clear the caller's grant on that host (or an expired one)
  python -I slot.py clear-expired                          clear each host's grant that has expired (coordinator
                                                           check-in)
  python -I slot.py check [--host mac|pc]                  exit 0 when this caller may start container work there now
  python -I slot.py hook                                   Claude Code PreToolUse hook: a Bash payload on stdin

--host defaults to mac. check without --host takes pc when DOCKER_HOST, DOCKER_CONTEXT or the Docker CLI's current
context aims at the PC, and
check --host mac refuses there: the tasks call check with no flag, so it follows where their Docker really goes.

Each host has its own grant, so a job on the PC does not wait behind a job on the Mac. The records are in
$XDG_STATE_HOME/slots (else ~/.local/state/slots): grant.json for the Mac and grant-pc.json for the PC, each
written atomically under one shared lock: lane, holder, host, granted_at and expires_at (UTC, ISO 8601). One grant
per host at a time. grant.json was the only record before #194, so a grant held from before reads as the Mac's.

The caller is SLOT_HOLDER, else HC_TERMINAL_ID (every herdr tab has one); with neither set, check refuses. check
passes when the host's record names the caller, has not expired, and the 5-minute load is below the start line
(SLOT_LOAD_LINE, default 9). Heavy work starts only under 9; 11 is the pause line for work already running.
Container work aimed at the PC runner host (the ssh alias `pc`, by its resolved host name), through `--context`,
`-H`, DOCKER_HOST, DOCKER_CONTEXT, the current context or `ssh <pc> docker ...`, needs the pc grant, and the load it checks is the PC's:
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
    r"\bdocker(?:\s+\S+)*?\s+(?:run|create|build|buildx\s+(?:build|bake)|image\s+build)\b"
    r"|\bdocker(?:-compose\b|(?:\s+\S+)*?\s+compose\b)(?:\s+\S+)*?\s+up\b",
)
PRIVILEGED = re.compile(
    r"--privileged(?:=(?:true|1))?(?![=\w-])|--cap-add[=\s]+ALL\b", re.IGNORECASE
)
DOCKER = re.compile(r"\bdocker(?:-compose)?\b")
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([^\s'\";|&<>()]+)\2")
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


def context_host(name: str) -> str | None:
    fmt = "{{.Endpoints.docker.Host}}"
    done = subprocess.run(
        ["docker", "context", "inspect", name, "--format", fmt],
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


def ssh_call(words: list[str], body: str = "") -> tuple[str | None, str]:
    """The destination and the remote command text of an `ssh ...` word list whose remote command names docker
    (body is a here-document sent to it); (None, "") when ssh is not running docker."""
    rest = words[1:]
    with_value = set("BbcDEeFIiJLlmOoPpQRSWw")
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        flag = rest[i]
        i += 2 if len(flag) == 2 and flag[1] in with_value else 1
    remote = " ".join(rest[i + 1 :]) + "\n" + body
    if i >= len(rest) or not DOCKER.search(remote):
        return None, ""
    return host_of(rest[i]) if "://" in rest[i] else rest[i].rsplit("@", 1)[-1], remote


SPAN = ("$(", "<(", ">(", "`", "$[")
# What a substitution leaves in its word: no spaces, so the word stays one word, and a $ so a target made of it is
# refused as unexpanded.
HOLE = "$()"


def quote_end(command: str, i: int) -> int:
    """The index after the double quote that opens at i, past any substitution inside it."""
    j = i + 1
    while j < len(command):
        if command[j] == "\\":
            j += 2
        elif command[j] == '"':
            return j + 1
        elif command.startswith(("$(", "`"), j):
            j = span_end(command, j)
        else:
            j += 1
    raise ValueError('a " quote never closes')


def span_end(command: str, i: int) -> int:
    """The index after the substitution that opens at i: $(...), <(...), >(...), `...`, $((...)) or $[...].
    Quotes, nested substitutions and here-documents inside it are stepped over whole, so a ) or a quote in a
    commit message's here-document does not end it early."""
    size = len(command)
    if command[i] == "`":
        j = i + 1
        while j < size and command[j] != "`":
            j += 2 if command[j] == "\\" else 1
        if j >= size:
            raise ValueError("a ` never closes")
        return j + 1
    if command.startswith("$[", i):
        return command.index("]", i) + 1 if "]" in command[i:] else size
    arithmetic = command.startswith(("$((", "(("), i)
    j = command.index("(", i) + 1
    depth = 1
    waiting: list[tuple[str, bool]] = []
    while j < size:
        char = command[j]
        if char == "\\":
            j += 2
        elif char == "'":
            if "'" not in command[j + 1 :]:
                raise ValueError("a ' quote never closes")
            j = command.index("'", j + 1) + 1
        elif char == '"':
            j = quote_end(command, j)
        elif command.startswith(SPAN, j):
            j = span_end(command, j)
        elif not arithmetic and command.startswith("<<<", j):
            j += 3
        elif not arithmetic and (found := HEREDOC.match(command, j)):
            waiting.append((found.group(3).replace("\\", ""), bool(found.group(1))))
            j = found.end()
        elif char == "\n" and waiting:
            for word, tabs in waiting:
                closed = False
                while j < size and not closed:
                    end = command.find("\n", j + 1)
                    end = size if end < 0 else end
                    line = command[j + 1 : end]
                    closed = (line.lstrip("\t") if tabs else line) == word
                    j = end
                if not closed:
                    raise ValueError(UNCLOSED.format(word))
            waiting.clear()
        else:
            depth += (char == "(") - (char == ")")
            j += 1
            if not depth:
                return j
    raise ValueError("a ( never closes")


def segments(command: str) -> list[tuple[str, str, bool]]:
    """The command's simple commands in order, each with the here-document text sent to it and whether it reads
    the command before it through a pipe. Separators (&& || ;
    | & newlines, parentheses and backquotes) split only outside quotes, so a quoted remote command stays one
    word of its ssh call. Raises ValueError for a quote or a here-document that never closes: the lines after
    it would otherwise be taken for its text and go unread."""
    out: list[tuple[list[str], list[str], bool]] = [([], [], False)]
    waiting: list[
        tuple[str, bool, list[str]]
    ] = []  # delimiter, whether <<-, the owning command's body
    quote = ""
    inside: list[tuple[str, str, bool]] = []  # the commands inside substitutions
    i, size = 0, len(command)
    while i < size:
        char = command[i]
        text = out[-1][0]
        step = 1
        if (quote == '"' and command.startswith(("$(", "`"), i)) or (
            not quote and command.startswith(SPAN, i)
        ):
            # A substitution is part of the word it stands in; its own commands are read after this one.
            step = span_end(command, i) - i
            if not command.startswith("$[", i):
                opened = 1 if char == "`" else 2
                within = command[i + opened : i + step - 1]
                if command.startswith("$((", i):
                    # Arithmetic, or a subshell inside a substitution: a << in it is a shift, and a
                    # substitution inside it still runs.
                    within = within.replace("<<", "  ")
                inside += segments(within)
            text.append(HOLE)
        elif quote:
            if char == "\\" and quote == '"' and i + 1 < size:
                text.append(command[i : i + 2])
                step = 2
            else:
                quote = "" if char == quote else quote
                text.append(char)
        elif char == "\\" and i + 1 < size:
            # A backslash-newline joins two lines; any other escaped character stays in its word.
            if command[i + 1] != "\n":
                text.append(command[i : i + 2])
            step = 2
        elif char in "'\"":
            quote = char
            text.append(char)
        elif char == "#" and (not text or text[-1].isspace()):
            step = (command.find("\n", i) if "\n" in command[i:] else size) - i
        elif command.startswith("((", i) and not "".join(text).strip():
            # An arithmetic command: its << is a shift, not a here-document.
            step = span_end(command, i) - i
        elif command.startswith("<<<", i):
            text.append("<<<")
            step = 3
        elif (found := HEREDOC.match(command, i)) and "".join(text).split()[:1] != [
            "let"
        ]:
            word = found.group(3).replace("\\", "")
            waiting.append((word, bool(found.group(1)), out[-1][1]))
            step = found.end() - i
        elif char == "\n" and waiting:
            lines = command[i + 1 :].split("\n")
            used = 0
            for word, tabs, body in waiting:
                closed = False
                while used < len(lines) and not closed:
                    line = lines[used]
                    used += 1
                    closed = (line.lstrip("\t") if tabs else line) == word
                    if not closed:
                        body.append(line)
                if not closed:
                    raise ValueError(UNCLOSED.format(word))
            waiting.clear()
            out.append(([], [], False))
            step = 1 + sum(len(line) + 1 for line in lines[:used])
        elif command.startswith(("&&", "||"), i):
            out.append(([], [], False))
            step = 2
        elif char == "&" and out[-1][2] and not text:
            pass  # |& is a pipe too
        elif char in ";|&\n()`":
            out.append(([], [], char == "|"))
        else:
            text.append(char)
        i += step
    if quote:
        msg = f"a {quote} quote never closes"
        raise ValueError(msg)
    if waiting:
        raise ValueError(UNCLOSED.format(waiting[0][0]))
    return [
        ("".join(text), "\n".join(body), piped)
        for text, body, piped in out
        if "".join(text).strip()
    ] + inside


UNCLOSED = "the here-document {} never closes"
# Commands that run the command after them, each with its own options that take a value: a container started
# through timeout with -k, or caffeinate with -i, starts just as it does from the bare command.
WRAPPERS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-P", "-S"}),
    "sudo": frozenset(
        {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t"}
    ),
    "nohup": frozenset(),
    "time": frozenset({"-o", "-f"}),
    "exec": frozenset({"-a"}),
    "command": frozenset(),
    "builtin": frozenset(),
    "coproc": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "ionice": frozenset({"-c", "-n", "-p"}),
    "caffeinate": frozenset({"-t", "-w"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-k", "--kill-after", "-s", "--signal"}),
    "xargs": frozenset(
        {"-I", "-n", "-P", "-L", "-s", "-E", "-d", "-a", "-R", "-S", "-J"}
    ),
    "sshpass": frozenset({"-p", "-f", "-d", "-P"}),
    "flock": frozenset({"-w", "--timeout", "-E", "--conflict-exit-code"}),
    "arch": frozenset({"-arch", "-e"}),
}
# Wrappers whose first plain word is their own (a duration, a lock file), not the command.
OWN_WORD = frozenset({"timeout", "flock"})
# Launchers that run the words after their `--`.
LAUNCHERS = frozenset({"mise", "fnox"})
REDIRECT = re.compile(r"\d*(?:>>?|<|&>>?)&?(.*)", re.DOTALL)
# Builtins that set a variable for the commands after them, as export does.
DECLARES = frozenset({"export", "declare", "typeset", "readonly", "local"})
# Commands whose words or here-document go down a pipe to the command after them.
PRINTS = frozenset({"echo", "printf", "cat", "tee"})
UNEXPANDED = "the docker target {} holds a variable or a ~, which is not expanded here"
# Commands whose here-document is handled by their own rule (a shell or ssh runs it, docker and the printers pass
# it on as data); every other command's here-document is read as commands.
# Commands that take a here-document as text and run none of it: a commit message, an issue body.
TEXT_ONLY = frozenset({"git", "gh"})
READS_BODY = (
    [["eval"], ["ssh"], ["docker"], ["docker-compose"]]
    + [[name] for name in sorted(PRINTS | TEXT_ONLY)]
    + [[name] for name in ("bash", "sh", "zsh", "dash", "ksh")]
)
# Shells that run the text given after -c, or a here-document sent to them.
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
# Shell words that come before a command without being one: `do docker run x`, `then docker run x`, `{ docker ...`.
RESERVED = frozenset({"do", "then", "else", "elif", "if", "while", "until", "{", "!"})
ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
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
    }
)
# The context `docker context use` set earlier in the same command; not a name a shell variable can have.
CURRENT = "docker context use"


def wrapped(name: str, words: list[str], assigned: dict[str, str]) -> list[str]:
    """The words after a wrapper's own options (and timeout's duration). `env -u NAME` and `env -i` clear a
    variable for the command, which is read as assigning it the empty value."""
    takes = WRAPPERS[name]
    i = 0
    while i < len(words) and words[i].startswith("-") and words[i] != "--":
        word = words[i]
        if name == "env" and word in {"-u", "--unset"} and i + 1 < len(words):
            assigned[words[i + 1]] = ""
        elif name == "env" and word.startswith("--unset="):
            assigned[word.partition("=")[2]] = ""
        elif name == "env" and word in {"-", "-i", "--ignore-environment"}:
            assigned.update(DOCKER_HOST="", DOCKER_CONTEXT="")
        # -iu root: the last letter of a group of short options may take the value.
        short = "-" + word[-1] if not word.startswith("--") else word
        i += 2 if word in takes or short in takes else 1
    if i < len(words) and words[i] == "--":
        i += 1
    return words[i + 1 :] if name in OWN_WORD else words[i:]


def command_words(text: str) -> tuple[dict[str, str], list[str]]:
    """A simple command's leading assignments and its words from the command word on, wrappers such as env and
    timeout dropped with their options and the command word without its folder, so /usr/bin/ssh reads as ssh."""
    words = shlex.split(text)
    assigned: dict[str, str] = {}
    while words:
        found = ASSIGNMENT.fullmatch(words[0])
        name = os.path.basename(words[0])
        if found:
            assigned[found.group(1)] = found.group(2)
            words = words[1:]
        elif words[0] in RESERVED:
            words = words[1:]
        elif words[0] == "function":
            words = words[2:]
        elif (found := REDIRECT.fullmatch(words[0])) and not words[0].startswith("<("):
            # A redirection before the command word: >log docker run x.
            words = words[1 if found.group(1) else 2 :]
        elif name in LAUNCHERS and "--" in words:
            words = words[words.index("--") + 1 :]
        elif words[:2] == ["tailscale", "ssh"]:
            words = words[1:]
        elif name == "autossh":
            # autossh -M PORT HOST: the monitor port is its own, the rest is ssh's.
            words = ["ssh", *words[3 if words[1:2] == ["-M"] else 1 :]]
        elif name == "mosh":
            # mosh HOST -- COMMAND: read as ssh HOST COMMAND.
            rest = [w for w in words[1:] if not w.startswith("-") or w == "--"]
            words = ["ssh", *(w for w in rest if w != "--")]
        elif name in WRAPPERS:
            words = wrapped(name, words[1:], assigned)
        else:
            words[0] = name
            break
    return assigned, words


def shell_text(words: list[str], body: str) -> str:
    """The command text a shell or eval is given: eval's words, the word after a shell's -c, or the
    here-document sent to a shell that names no script."""
    if words[0] == "eval":
        return " ".join(words[1:])
    i = 1
    while i < len(words) and words[i].startswith(("-", "+")) and words[i] != "--":
        word = words[i]
        # -o and -O take the next word: bash -euo pipefail -c '...'.
        named = not word.startswith("--") and ("o" in word or "O" in word)
        if word.startswith("-") and not word.startswith("--") and "c" in word:
            return "\n".join(words[i + 1 + named : i + 2 + named] + [body])
        i += 1 + named
    # A shell reads a here-document as commands whether or not it is also given words (bash -s a b).
    return body


def docker_target(words: list[str]) -> tuple[dict[str, str], list[str]]:
    """Docker's --context and --host as given before the subcommand (compose takes them after its own name too),
    and the words from the subcommand on. Words after the subcommand belong to the container, not to docker."""
    given: dict[str, str] = {}
    in_compose = False
    i = 0
    while i < len(words):
        word = words[i]
        if word == "compose" and not in_compose:
            in_compose = True
            i += 1
            continue
        if not word.startswith("-") or word == "-":
            break
        name, joined, value = word.partition("=")
        if name in {"--context", "--host", "-c", "-H"}:
            key = "context" if name in {"--context", "-c"} else "host"
            if joined:
                given[key] = value
            elif i + 1 < len(words):
                given[key] = words[i + 1]
                i += 1
        elif re.match(r"-[cH].", word):
            given["context" if word[1] == "c" else "host"] = word[2:].removeprefix("=")
        elif name == "--config":
            given["config"] = value if joined else "".join(words[i + 1 : i + 2])
            i += 0 if joined else 1
        elif word in WITH_VALUE:
            i += 1
        i += 1
    return given, words[i:]


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
    DOCKER_CONTEXT, then the current context; an empty variable counts as unset."""
    context = given.get("context")
    endpoint = None if context else given.get("host") or env.get("DOCKER_HOST")
    if not context and not endpoint:
        context = env.get("DOCKER_CONTEXT") or env.get(CURRENT) or current_context(env)
    if context == "default":
        # The default context is DOCKER_HOST when set, else the local socket.
        context, endpoint = None, env.get("DOCKER_HOST")
    if endpoint:
        return f"DOCKER_HOST {endpoint}" if is_pc(host_of(endpoint)) else None
    if context and is_pc(context_host(context)):
        return f"docker context {context}"
    return None


def unexpanded(target: str) -> None:
    """Refuse a target the shell would expand (a variable, a leading ~): read as written it would look like
    Mac work."""
    if "$" in target or target.startswith("~"):
        raise ValueError(UNEXPANDED.format(target))


def loose(text: str, env: dict[str, str]) -> list[tuple[str, str | None]]:
    """The starts in text that may be commands or may be prose, read a line at a time: a line that cannot be
    read as a command (an apostrophe in a commit message) is read again without its quotes, then left out."""
    out: list[tuple[str, str | None]] = []
    for line in text.split("\n"):
        for attempt in (line, re.sub(r"[\"'`()]", " ", line)):
            try:
                out += started(attempt, env)
            except ValueError as error:
                if "not expanded" in str(error) or "inspected" in str(error):
                    raise
                continue
            break
    return out


def started(command: str, env: dict[str, str]) -> list[tuple[str, str | None]]:
    """Each heavy container start in the command, in order: its text, and why it is aimed at the PC (None when
    it runs here). A target an earlier command sets (export, a bare assignment, unset, docker context use) holds
    for the ones after it. docker or ssh must be the command word, so `grep "docker run" notes.md` starts
    nothing; the text given to `bash -c`, to eval or to a shell as a here-document is read as a command too. Raises ValueError when the quoting cannot be read."""
    shell = dict(env)
    out: list[tuple[str, str | None]] = []
    sent = ""  # what the command before writes to a pipe, as far as it can be read
    for text, body, piped in segments(command):
        assigned, words = command_words(text)
        fed = "\n".join(filter(None, (body, sent if piped else "")))
        sent = ""
        if body and words[:1] not in READS_BODY:
            # Any other receiver may run its here-document (sudo -s, su, fish, at): read each line as a command.
            out += loose(body, shell | assigned)
        if not words:
            shell.update(assigned)
        elif words[0] in PRINTS:
            sent = fed if words[0] in {"cat", "tee"} else " ".join(words[1:])
        elif words[0] in DECLARES:
            shell.update(w.split("=", 1) for w in words[1:] if "=" in w)
        elif words[0] == "unset":
            for word in words[1:]:
                shell.pop(word, None)
        elif words[0] == "eval" or words[0] in SHELLS:
            found = started(shell_text(words, fed), shell | assigned)
            if not found and piped and HEAVY.search(fed):
                # echo -e '...' | bash, printf '%s\n' '...' | sh: the words are not the text the shell gets,
                # but a start among them counts.
                found = [(fed, pc_reason({}, shell | assigned))]
            out += found
        elif words[0] == "ssh":
            # The remote command is opaque to the word rules here; any heavy docker in it counts.
            target, remote = ssh_call(words, fed)
            if target and HEAVY.search(remote):
                unexpanded(target)
                aimed = f"docker over ssh to {target}" if is_pc(target) else None
                out.append((remote, aimed))
        elif DOCKER.fullmatch(words[0]):
            given, rest = docker_target(words[1:])
            if rest[:2] == ["context", "use"] and len(rest) > 2:
                shell[CURRENT] = rest[2]
            elif HEAVY.search(shlex.join(words)):
                around = shell | assigned
                if "config" in given:
                    around["DOCKER_CONFIG"] = given["config"]
                for name in ("context", "host"):
                    unexpanded(given.get(name, ""))
                for name in ("DOCKER_HOST", "DOCKER_CONTEXT"):
                    unexpanded(around.get(name, ""))
                out.append((text, pc_reason(given, around)))
    return out


PLAIN = re.compile(r"&&|\|\||[;|&\n]")
# The -c of a shell (sh -c, bash -c) is not docker's -c, so it is no hint.
PC_HINT = re.compile(
    r"ssh|mosh|DOCKER_HOST|DOCKER_CONTEXT|--context|--host|(?<!\S)(?<!sh\s)-[cH]"
)


def plain_start(piece: str) -> bool:
    """Whether a piece of the command text, split with no regard for quotes, has docker (or ssh running docker)
    as its command word and starts container work."""
    words = piece.split()
    while words and (ASSIGNMENT.fullmatch(words[0]) or words[0] in WRAPPERS):
        words = words[1:]
    if words[:1] == ["ssh"]:
        return bool(HEAVY.search(" ".join(words[1:])))
    return bool(words and DOCKER.fullmatch(words[0]) and HEAVY.search(" ".join(words)))


NOT_FLAT = re.compile(r"[(){}&|`]|\$\(|\b(?:if|while|until|case|for|select|function)\b")
# A change of the docker target that outlasts its own command: unset, export and the like, a bare assignment,
# docker context use. An assignment in front of a command is not one.
TARGET_MOVE = re.compile(
    r"\b(?:unset|export|declare|typeset|readonly|local)\b[^;&|\n]*DOCKER_(?:HOST|CONTEXT)"
    r"|context\s+use"
    r"|(?:^|[;&|\n({])\s*DOCKER_(?:HOST|CONTEXT)=\S*\s*(?:$|[;&|\n)}])"
)
BUILDER = re.compile(r"--builder[=\s]+(\S+)|\bBUILDX_BUILDER=(\S+)")
BUILDER_USE = re.compile(r"\bbuildx\s+use\b")
LOCAL_BUILDERS = frozenset({"", "default", "desktop-linux"})


def points_at_pc(command: str, env: dict[str, str]) -> bool:
    """Whether anything in the command's text or the environment names the PC."""
    return bool(PC_HINT.search(command) or is_pc_word(command) or pc_reason({}, env))


def unplaced(
    command: str, env: dict[str, str], mac_work: bool, pc_work: bool
) -> str | None:
    """Why this command's work needs both grants, or None. The parser's reading of where docker is aimed is
    trusted only in a flat list of commands separated by ; or newlines. In anything else (a subshell, a
    pipeline, &&, a loop, a function) a command that points at the PC needs both grants when some work was read
    as the Mac's or when it changes the docker target. A buildx builder is never followed."""
    if (
        NOT_FLAT.search(command)
        and (mac_work or TARGET_MOVE.search(command))
        and (pc_work or points_at_pc(command, env))
    ):
        return "a command that points at the PC and is not a flat list"
    if BUILDER_USE.search(command):
        return "a buildx builder change, which this guard cannot place"
    named = [a or b for a, b in BUILDER.findall(command)] + [
        env.get("BUILDX_BUILDER", "")
    ]
    for name in named:
        if name.strip("\"'") not in LOCAL_BUILDERS:
            return f"buildx builder {name}, which this guard cannot place"
    return None


def is_pc_word(command: str) -> bool:
    return PC_ALIAS in re.split(r"[^\w.-]+", command)


def without_text(command: str) -> str:
    """The command less the here-documents that are text and nothing runs: one given to git or gh, and one
    given to cat, tee, echo or printf that does not go on down a pipe."""
    parts = segments(command)
    for i, (text, body, _) in enumerate(parts):
        words = command_words(text)[1]
        onward = i + 1 < len(parts) and parts[i + 1][2]
        if (
            body
            and words
            and (words[0] in TEXT_ONLY or (words[0] in PRINTS and not onward))
        ):
            command = command.replace(body, "", 1)
    return command


def placed(command: str, env: dict[str, str]) -> list[tuple[str, str | None]]:
    """Each start in the command with why it is the PC's (None: the Mac's). A command that is both gets a row
    of each kind, so it needs both grants."""
    work = started(command, env)
    missed = sum(map(plain_start, PLAIN.split(without_text(command)))) - len(work)
    if missed > 0:
        # The guard this one replaced split the text at every ; & | and newline and looked at each piece. A
        # start it finds that the parser above did not is not let through: it needs this machine's grant, and
        # the PC's too when anything in the command or the environment points there.
        work.append((command, None))
        if points_at_pc(command, env):
            work.append((command, "a start this guard could not place"))
    if work and (
        why := unplaced(
            command,
            env,
            any(not reason for _, reason in work),
            any(reason for _, reason in work),
        )
    ):
        work += [(command, None), (command, why)]
    return work


def guard_command(command: str, env: dict[str, str]) -> None:
    """Refuse a shell command that starts container work without the live grant of the host it is aimed at, or
    under too high a load there: the pc grant and the PC's load for work aimed at the PC, else the Mac's."""
    if not DOCKER.search(command):
        return
    try:
        work = placed(command, env)
    except ValueError as error:
        # Guessing here is how PC work was once read as Mac work; a command that names docker and cannot be
        # read does not run.
        msg = (
            f"cannot read this command ({error}), so cannot tell where its docker runs"
        )
        raise RefusedError(msg) from error
    aimed = [text for text, reason in work if reason]
    # No --privileged container on the PC, grant or not: one that runs apt can apply its image's kernel settings
    # to the PC itself (the agent rules' "No --privileged containers on the PC").
    if any(PRIVILEGED.search(text) for text in aimed):
        msg = "a --privileged container on the PC is never allowed: pass the one --device or --cap-add it needs"
        raise RefusedError(msg)
    # A command may start work in both places; each needs its own host's grant and is checked against its load.
    if aimed:
        check("pc")
    if len(aimed) < len(work):
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
    except RefusedError as error:
        sys.stderr.write(f"slot: refused: {error}\n")
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"slot: refused: cannot tell where docker is aimed: {error}\n")
        sys.exit(1)
    sys.stdout.write(out + "\n")


if __name__ == "__main__":
    main()
