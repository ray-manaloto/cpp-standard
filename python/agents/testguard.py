"""PreToolUse guard for a live-test Claude tab: only the run's listed tools, and SendMessage only to the run's own tabs.

  python -I testguard.py <log.jsonl> --tools <A,B,...> <allowed-name> [<allowed-name> ...]

testtab.py installs it as the tab's first PreToolUse hook (matcher "*"). Any tool not in --tools is denied (Bash,
Monitor, MCP tools, ...), so a test tab cannot reach another session through a shell, sockets or scripts. A listed
SendMessage may go only to an allowed name, or to a uds:<dir>/<pid>.sock whose process was started with
`-n <allowed-name>`. A shell tool is refused even if listed. Any error denies: the guard fails closed.
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


def decide(payload: dict, tools: set[str], names: set[str]) -> tuple[bool, str]:
    """Allow or deny one tool call, with the reason."""
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or not tool:
        return False, "no tool name"
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
    log = Path(sys.argv[1])
    payload: dict = {}
    try:
        rest = sys.argv[2:]
        if len(rest) < 2 or rest[0] != "--tools":
            msg = "usage: <log> --tools A,B <names...>"
            raise ValueError(msg)
        tools = {t for t in rest[1].split(",") if t}
        names = set(rest[2:])
        payload = json.load(sys.stdin)
        ok, why = decide(payload, tools, names)
    except Exception as error:  # noqa: BLE001 (any error denies)
        ok, why = False, f"guard error: {error!r}"
    with log.open("a", encoding="utf-8") as out:
        record = {
            "at": time.time(),
            "ok": ok,
            "why": why,
            "tool": payload.get("tool_name"),
        }
        out.write(json.dumps(record | {"input": payload.get("tool_input")}) + "\n")
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
