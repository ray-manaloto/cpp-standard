"""Open, watch and close agent tabs in the herdr-app space that holds this terminal (#200). The one implementation of
"find the space", "open a tab" and "watch its screen"; `testtab.py` imports it and adds its guard on top.

  python -I herdrtab.py tab --agent claude|codex --name N --task TEXT [--folder DIR] [--wait 30]
  python -I herdrtab.py close --id TAB_ID

`tab` finds the space whose tabs list $HC_TERMINAL_ID in `herdr-app ls`, opens the tab there with `tab.new` (Codex as
`codex-hc`, Claude as `claude`, the task as the last argv word), and reads the new terminal with `hc read` until the
start of the task text is on its screen. It prints one JSON line {"name","space","tab","terminal"} and, as the last
line, `name (terminal)`. Exit 0: the task arrived. Exit 2: usage, or `herdr-app` failed, or no space lists this
terminal; nothing opened and `hc run` is never the fallback. Exit 4: a tab opened but a trust dialog is open or the
task never appeared; the screen is named on stderr, nothing more is sent to the tab, and the tab stays open for the
owner. `close` closes a tab of the current space and refuses (exit 2) one that is in another space or is unknown.
"""

import argparse
import json
import os
import subprocess
import sys
import time

USAGE, HANDOFF = 2, 4
# Markers taken from captured screens of Claude Code 2.1.3xx tabs, and Codex's own directory-trust prompt.
DIALOG = (
    "Do you trust the files in this folder",
    "Is this a project you created or one you trust",
    "trust this folder",
    "Do you trust the contents of this directory",
)
AGENTS = {"claude": "claude", "codex": "codex-hc"}
HEAD = 30  # characters of the task, whitespace removed, that must show on the screen


class TabError(Exception):
    """A step failed before or while opening; the message is the reason."""


def run(*argv: str) -> str:
    """Run a command and return its stdout; a missing command or non-zero exit is a TabError."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as error:
        msg = f"{argv[0]}: {error}"
        raise TabError(msg) from error
    if done.returncode != 0:
        msg = f"{' '.join(argv[:3])} exited {done.returncode}: {done.stderr.strip()}"
        raise TabError(msg)
    return done.stdout


def listing() -> list[dict]:
    """The spaces of `herdr-app ls`."""
    try:
        spaces = json.loads(run("herdr-app", "ls"))["spaces"]
    except (ValueError, KeyError, TypeError) as error:
        msg = f"herdr-app ls gave no spaces list: {error}"
        raise TabError(msg) from error
    return spaces


def terminal_id() -> str:
    """This terminal's id."""
    term = os.environ.get("HC_TERMINAL_ID", "")
    if not term:
        msg = "HC_TERMINAL_ID is not set; run this from a herdr terminal"
        raise TabError(msg)
    return term


def find_space(term: str | None = None) -> str:
    """The id of the space whose tabs list the terminal."""
    term = term or terminal_id()
    for space in listing():
        if any(
            t.get("terminal") == term
            for tab in space.get("tabs", [])
            for t in tab.get("terminals", [])
        ):
            return space["id"]
    msg = f"no herdr-app space lists terminal {term}"
    raise TabError(msg)


def open_tab(space: str, name: str, folder: str, argv: list[str]) -> dict:
    """`tab.new` in the space; returns the reply, which holds "tab" and "terminal"."""
    out = run(
        "herdr-app",
        "do",
        "tab.new",
        "--space",
        space,
        "--name",
        name,
        "--folder",
        folder,
        "--argv",
        json.dumps(argv),
    )
    try:
        reply = json.loads(out)
        reply["tab"], reply["terminal"]
    except (ValueError, KeyError, TypeError) as error:
        msg = f"tab.new gave no tab and terminal: {out.strip()[:200]}"
        raise TabError(msg) from error
    return reply


def squeeze(text: str) -> str:
    """Text without any whitespace, so a screen's wrapping and indent cannot split a match."""
    return "".join(text.split())


def watch(
    terminal: str,
    wait: float,
    ready: tuple[str, ...] = (),
    task: str | None = None,
) -> tuple[bool, str]:
    """Read the screen until it shows the start of `task` (or any `ready` marker), a trust dialog, or the wait ends."""
    head = squeeze(task or "")[:HEAD]
    deadline = time.monotonic() + wait
    while True:
        screen = subprocess.run(
            ["hc", "read", terminal], capture_output=True, text=True, check=False
        ).stdout
        if any(marker in screen for marker in DIALOG):
            return False, "a workspace-trust dialog is open"
        if (head and head in squeeze(screen)) or any(m in screen for m in ready):
            return True, "ready"
        if time.monotonic() >= deadline:
            tail = "\n".join(
                [line for line in screen.splitlines() if line.strip()][-6:]
            )
            what = "the start of the task text" if head else "a ready prompt"
            return (
                False,
                f"{what} did not show within {wait:g}s; the screen showed:\n{tail}",
            )
        time.sleep(1)


def tab_cmd(args: argparse.Namespace) -> int:
    if args.task.startswith("-"):
        msg = "the task starts with '-', which the agent would read as a flag"
        raise TabError(msg)
    space = find_space()
    folder = os.path.realpath(args.folder)
    reply = open_tab(space, args.name, folder, [AGENTS[args.agent], args.task])
    terminal = reply["terminal"]
    ok, why = watch(terminal, args.wait, task=args.task)
    sys.stdout.write(
        json.dumps(
            {
                "name": args.name,
                "space": space,
                "tab": reply["tab"],
                "terminal": terminal,
            }
        )
        + "\n"
    )
    if not ok:
        sys.stderr.write(
            f"herdrtab: {args.name} ({terminal}): {why}; nothing more is sent to it, "
            f"the tab stays open (close it: herdrtab close --id {reply['tab']})\n"
        )
        return HANDOFF
    sys.stdout.write(f"{args.name} ({terminal})\n")
    return 0


def close_cmd(args: argparse.Namespace) -> int:
    space = find_space()
    for other in listing():
        if any(tab.get("id") == args.id for tab in other.get("tabs", [])):
            if other["id"] != space:
                msg = f"tab {args.id} is in space {other['id']}, not the current space {space}"
                raise TabError(msg)
            break
    else:
        msg = f"no tab {args.id} in any space"
        raise TabError(msg)
    run("herdr-app", "do", "tab.close", "--id", args.id)
    sys.stdout.write(json.dumps({"closed": args.id, "space": space}) + "\n")
    return 0


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    tab = sub.add_parser("tab", help="open a tab and prove the task arrived")
    tab.add_argument("--agent", choices=sorted(AGENTS), required=True)
    tab.add_argument("--name", required=True)
    tab.add_argument("--task", required=True)
    tab.add_argument("--folder", default=os.getcwd())
    tab.add_argument("--wait", type=float, default=30)
    close = sub.add_parser("close", help="close a tab of the current space")
    close.add_argument("--id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse()
    try:
        code = tab_cmd(args) if args.command == "tab" else close_cmd(args)
    except TabError as error:
        sys.stderr.write(f"herdrtab: {error}\n")
        code = USAGE
    sys.exit(code)


if __name__ == "__main__":
    main()
