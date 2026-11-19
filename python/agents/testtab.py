"""Open one live-test Claude tab in a herdr-app space, guarded, and never answer its workspace-trust dialog (#178).

  python -I testtab.py --space S --run RUNDIR --folder DIR --name N --names a,b --tools T1,T2 [--prompt TEXT]
                       [--model haiku] [--effort low] [--mode default] [--extra FILE] [--no-tools-flag] [--wait 20]

Trust is the owner's decision. Before launch the folder must already be trusted in the client's own record
(projects[<key>].hasTrustDialogAccepted in $CLAUDE_CONFIG_DIR/.claude.json, else ~/.claude.json), where the key is
the folder's git root, or a linked worktree's main checkout, as the client keys it. An untrusted, unknown or non-git
folder is refused (exit 3) and no tab opens. After launch the tab's screen is read for up to --wait seconds: a ready
prompt is success (exit 0); a trust dialog, or a screen that never shows a ready prompt, is handed to the owner
(exit 4) and nothing more is sent to the tab. The first prompt goes in argv (--prompt), so the launcher never types.

Settings written to RUNDIR/settings-N.json: env CLAUDE_CODE_BRIEF "0" and a PreToolUse "*" hook running testguard.py
(tool allowlist and SendMessage recipients, with "onFailure": "block", so a broken guard blocks the call) first, then
any hooks from --extra. The launch strips the inherited
CLAUDE_CODE_* variables. Writes RUNDIR/tabnew_N.json. Exit 2 is a usage error.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFUSED, HANDOFF = 3, 4
# Markers taken from captured screens of Claude Code 2.1.3xx tabs.
DIALOG = (
    "Do you trust the files in this folder",
    "Is this a project you created or one you trust",
    "trust this folder",
)
READY = ("? for shortcuts", "shift+tab to cycle", "esc to interrupt")


class RefusedError(Exception):
    """The launch is refused before any tab opens."""


def git(folder: Path, *args: str) -> str:
    """Run git in the folder; a failure means the folder has no trust key."""
    done = subprocess.run(
        ["git", "-C", str(folder), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        msg = f"{folder} is not in a git checkout, so it has no trust entry"
        raise RefusedError(msg)
    return done.stdout


def trust_key(folder: Path) -> Path:
    """The folder's git root, or a linked worktree's main checkout: the path the client keys trust by."""
    git_dir, common, top = (
        Path(line)
        for line in git(
            folder,
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
            "--git-common-dir",
            "--show-toplevel",
        ).splitlines()
    )
    if git_dir == common:
        return top.resolve()
    main_root = common.parent
    if (
        git_dir.parent != common / "worktrees"
        or (main_root / ".git").resolve() != common.resolve()
    ):
        msg = f"{folder}: its common git dir {common} has no main checkout above it"
        raise RefusedError(msg)
    return main_root.resolve()


def config_file() -> Path:
    """The client's config file: the one the launched tab will read."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()) / ".claude.json"


def check_trust(folder: Path) -> Path:
    """Refuse unless the client's own record already trusts the folder's key. Read only, never written."""
    key = trust_key(folder)
    path = config_file()
    try:
        projects = json.loads(path.read_text(encoding="utf-8")).get("projects") or {}
    except (OSError, ValueError, AttributeError) as error:
        msg = f"cannot read the trust record {path}: {error}"
        raise RefusedError(msg) from error
    entry = projects.get(str(key))
    if not isinstance(entry, dict) or entry.get("hasTrustDialogAccepted") is not True:
        msg = f"{key} is not trusted; the owner trusts it by opening Claude Code there once and answering the dialog"
        raise RefusedError(msg)
    return key


def settings(
    args: argparse.Namespace, run: Path, tools: list[str], names: list[str]
) -> Path:
    """Write the tab's settings file, with the guard as its first PreToolUse hook."""
    guard = shlex.join(
        [
            sys.executable,
            "-I",
            str(HERE / "testguard.py"),
            str(run / "log" / "testguard.jsonl"),
            "--tools",
            ",".join(tools),
            *names,
        ]
    )
    data = (
        json.loads(Path(args.extra).read_text(encoding="utf-8")) if args.extra else {}
    )
    data.setdefault("env", {})["CLAUDE_CODE_BRIEF"] = "0"
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    # onFailure "block": a guard that cannot start, crashes or times out blocks the call instead of letting it through.
    hook = {"type": "command", "command": guard, "onFailure": "block"}
    pre.insert(0, {"matcher": "*", "hooks": [hook]})
    path = run / f"settings-{args.name}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def watch(terminal: str, wait: float) -> tuple[bool, str]:
    """Read the tab's screen until it shows a ready prompt or a trust dialog, or the wait ends."""
    deadline = time.monotonic() + wait
    while True:
        screen = subprocess.run(
            ["hc", "read", terminal], capture_output=True, text=True, check=False
        ).stdout
        if any(marker in screen for marker in DIALOG):
            return False, "a workspace-trust dialog is open"
        if any(marker in screen for marker in READY):
            return True, "ready"
        if time.monotonic() >= deadline:
            return False, f"no ready prompt within {wait:g}s"
        time.sleep(1)


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--space", "--run", "--folder", "--name", "--names", "--tools"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--prompt", help="the tab's first prompt, passed in argv")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--mode", default="default")
    parser.add_argument(
        "--extra", help="a settings file whose hooks run after the guard"
    )
    # /restart refuses a session launched with a tool allowlist; the guard hook still allows only --tools.
    parser.add_argument(
        "--no-tools-flag",
        action="store_true",
        help="omit the --tools launch flag; the guard stays",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=20,
        help="seconds to wait for the tab's ready prompt",
    )
    return parser.parse_args()


def main() -> None:
    args = parse()
    if args.mode in {"auto", "bypassPermissions", "dontAsk"}:
        sys.exit(
            f"testtab: refusing --mode {args.mode}: test tabs run in default or plan mode"
        )
    tools = [t for t in args.tools.split(",") if t]
    if {"Bash", "Monitor", "PowerShell"} & set(tools):
        sys.exit("testtab: refusing a shell tool in a test tab")
    names = [n for n in args.names.split(",") if n]
    if args.name not in names:
        names.append(args.name)
    try:
        folder = Path(args.folder).resolve(strict=True)
        check_trust(folder)
    except (OSError, RefusedError) as error:
        sys.stderr.write(f"testtab: refused, no tab opened: {error}\n")
        sys.exit(REFUSED)
    run = Path(args.run)
    (run / "log").mkdir(parents=True, exist_ok=True)
    path = settings(args, run, tools, names)
    unset = [
        x for k in sorted(os.environ) if k.startswith("CLAUDE_CODE_") for x in ("-u", k)
    ]
    argv = [
        "env",
        *unset,
        "claude",
        "--model",
        args.model,
        "--effort",
        args.effort,
        "-n",
        args.name,
        "--permission-mode",
        args.mode,
        "--strict-mcp-config",
        "--no-chrome",
        *([] if args.no_tools_flag else ["--tools", ",".join(tools)]),
        "--settings",
        str(path),
        *([args.prompt] if args.prompt else []),
    ]
    out = subprocess.run(
        [
            "herdr-app",
            "do",
            "tab.new",
            "--space",
            args.space,
            "--name",
            args.name,
            "--folder",
            str(folder),
            "--argv",
            json.dumps(argv),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (run / f"tabnew_{args.name}.json").write_text(out, encoding="utf-8")
    terminal = json.loads(out)["terminal"]
    ok, why = watch(terminal, args.wait)
    result = {"name": args.name, "terminal": terminal, "ready": ok, "why": why}
    sys.stdout.write(json.dumps(result) + "\n")
    if not ok:
        sys.stderr.write(
            f"testtab: handing {args.name} ({terminal}) to the owner: {why}; nothing more is sent to it\n"
        )
        sys.exit(HANDOFF)


if __name__ == "__main__":
    main()
