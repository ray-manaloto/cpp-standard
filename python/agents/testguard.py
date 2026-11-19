"""PreToolUse guard for a live-test Claude tab: only the run's listed tools, and SendMessage only to the run's own tabs.

  python -I testguard.py <log.jsonl> --tools <A,B,...> [--allow-monitor CMD] <allowed-name> [<allowed-name> ...]

testtab.py installs it as the tab's first PreToolUse hook (matcher "*"). Any tool not in --tools is denied (Bash,
Monitor, MCP tools, ...), so a test tab cannot reach another session through a shell, sockets or scripts. A listed
SendMessage may go only to an allowed name, or to a uds:<dir>/<pid>.sock whose process was started with
`-n <allowed-name>`. A shell tool is refused even if listed. Any error denies, and so does a log that cannot be
written. With --allow-monitor CMD, the one exception to Monitor's refusal is a Monitor call whose command is exactly
CMD (no WebSocket watch); Bash and PowerShell stay refused. The guard still exits 0 with the deny: it fails closed. testtab.py also sets "onFailure": "block" on the
hook, for the failures the script cannot catch (it cannot start, or times out).
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

NEVER = frozenset({"Bash", "Monitor", "PowerShell"})


def name_of_pid(pid: str) -> str | None:
    """The `-n`/`--name` value of a running process, read from its command line."""
    out = subprocess.run(
        ["ps", "-o", "command=", "-p", pid],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    argv = out.stdout.split()
    for i, arg in enumerate(argv[:-1]):
        if arg in {"-n", "--name"}:
            return argv[i + 1]
    for arg in argv:
        if arg.startswith("--name="):
            return arg.split("=", 1)[1]
    return None


def decide(
    payload: dict, tools: set[str], names: set[str], monitor: str | None = None
) -> tuple[bool, str]:
    """Allow or deny one tool call, with the reason."""
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or not tool:
        return False, "no tool name"
    if tool == "Monitor" and monitor is not None:
        tool_input = payload.get("tool_input") or {}
        if tool_input.get("command") == monitor and "ws" not in tool_input:
            return True, "the run's allowed Monitor command"
        return False, "Monitor is allowed here only for the run's exact command"
    if tool in NEVER:
        return False, f"{tool} is never allowed in a test tab"
    if tool not in tools:
        return False, f"{tool} is not on this run's tool list"
    if tool != "SendMessage":
        return True, f"listed tool {tool}"
    tool_input = payload.get("tool_input") or {}
    to = tool_input.get("to") or tool_input.get("recipient")
    if not isinstance(to, str) or not to:
        return False, "no recipient"
    if to in names:
        return True, f"allowed name {to}"
    match = re.fullmatch(r"uds:.*/(\d+)\.sock", to)
    if match:
        name = name_of_pid(match.group(1))
        if name in names:
            return True, f"uds pid {match.group(1)} is {name}"
        return False, f"uds pid {match.group(1)} has name {name!r}, not a test tab"
    return False, f"{to!r} is not a test tab of this run"


def main() -> None:
    """Read the hook payload on stdin, log the decision, and print a deny when the call is refused."""
    payload: object = {}
    log: Path | None = None
    try:
        log = Path(sys.argv[1])
        rest = sys.argv[2:]
        if len(rest) < 2 or rest[0] != "--tools":
            msg = "usage: <log> --tools A,B <names...>"
            raise ValueError(msg)
        tools = {t for t in rest[1].split(",") if t}
        rest = rest[2:]
        monitor = None
        if rest[:1] == ["--allow-monitor"]:
            if len(rest) < 2 or not rest[1]:
                msg = "--allow-monitor needs a command"
                raise ValueError(msg)
            monitor, rest = rest[1], rest[2:]
        names = set(rest)
        payload = json.load(sys.stdin)
        ok, why = decide(payload, tools, names, monitor)
    except Exception as error:  # noqa: BLE001 (any error denies)
        ok, why = False, f"guard error: {error!r}"
    try:
        fields = payload if isinstance(payload, dict) else {}
        record = {
            "at": time.time(),
            "ok": ok,
            "why": why,
            "tool": fields.get("tool_name"),
            "input": fields.get("tool_input"),
        }
        if log is not None:
            with log.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record) + "\n")
    except Exception as error:  # noqa: BLE001 (a log that cannot be written denies, never exit 1)
        ok, why = False, f"log could not be written ({error!r}); {why}"
    if not ok:
        reason = f"testguard: {why}. Test tabs may only use their listed tools and message this run's tabs."
        deny = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
        sys.stdout.write(json.dumps({"hookSpecificOutput": deny}) + "\n")


if __name__ == "__main__":
    main()
