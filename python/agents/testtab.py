"""Open one live-test Claude tab in a herdr-app space, guarded, and never answer its workspace-trust dialog (#178).

  python -I testtab.py --space S --run RUNDIR --folder DIR --name N --names a,b --tools T1,T2 [--prompt TEXT]
                       [--model haiku] [--effort low] [--mode default] [--extra FILE] [--no-tools-flag] [--plugin-dir DIR]... [--allow-monitor CMD]
                       [--wait 20]

Trust is the owner's decision. Before launch the folder must already be trusted in the client's own record
(projects[<key>].hasTrustDialogAccepted in $CLAUDE_CONFIG_DIR/.claude.json, else ~/.claude.json), where the key is
the folder's git root, or a linked worktree's main checkout, as the client keys it. The session is named
`N-<stamp>` (tabname.stamp, #303) unless `N` already carries a stamp; the stamped name is what tab.new, `-n` and
the guard's allowed names carry. An untrusted, unknown or non-git
folder is refused (exit 3) and no tab opens. After launch the tab's screen is read for up to --wait seconds: a ready
prompt is success (exit 0); a trust dialog, or a screen that never shows a ready prompt, is handed to the owner
(exit 4) and nothing more is sent to the tab. The first prompt goes to the supervisor (--prompt), so the launcher
never types.

Settings written to RUNDIR/settings-N.json: env CLAUDE_CODE_BRIEF "0" and a PreToolUse "*" hook running testguard.py
(tool allowlist and SendMessage recipients, with "onFailure": "block", so a broken guard blocks the call) first, then
any hooks from --extra. The launch runs under the #304 same-tab supervisor (`herdrtab.supervised`), which strips the
inherited CLAUDE_CODE_* variables and, after an exit with a resume request, resumes the same session in this same
tab. Writes RUNDIR/tabnew_N.json. Exit 2 is a usage error.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I leaves the script's directory off sys.path
import herdrtab
import tabname

REFUSED, HANDOFF = 3, herdrtab.HANDOFF
# Marker taken from captured screens of Claude Code 2.1.3xx tabs.
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
    name: str, args: argparse.Namespace, run: Path, tools: list[str], names: list[str]
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
            *(["--allow-monitor", args.allow_monitor] if args.allow_monitor else []),
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
    path = run / f"settings-{name}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--space", "--run", "--folder", "--name", "--names", "--tools"):
        parser.add_argument(flag, required=True)
    parser.add_argument(
        "--prompt", help="the tab's first prompt, given to the first launch only"
    )
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
        "--plugin-dir",
        action="append",
        default=[],
        help="a plugin or mod folder to load for this tab only (repeatable)",
    )
    parser.add_argument(
        "--allow-monitor",
        metavar="CMD",
        help="let the guard allow the Monitor tool for this exact command only (Bash stays refused)",
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
    name = (
        args.name
        if tabname.is_stamped(args.name)
        else tabname.make_name(args.name, datetime.now().astimezone())
    )
    names = [n for n in args.names.split(",") if n]
    if name not in names:
        names.append(name)
    try:
        folder = Path(args.folder).resolve(strict=True)
        check_trust(folder)
    except (OSError, RefusedError) as error:
        sys.stderr.write(f"testtab: refused, no tab opened: {error}\n")
        sys.exit(REFUSED)
    run = Path(args.run)
    (run / "log").mkdir(parents=True, exist_ok=True)
    path = settings(name, args, run, tools, names)
    # No env -u, no -n and no prompt here: the supervisor strips the CLAUDE_CODE_* variables and gives the name and
    # the first prompt to the first launch only, so a relaunch is the agent argv plus the resume form (#304).
    argv = herdrtab.supervised(
        "claude",
        [
            "claude",
            "--model",
            args.model,
            "--effort",
            args.effort,
            "--permission-mode",
            args.mode,
            "--strict-mcp-config",
            "--no-chrome",
            *([] if args.no_tools_flag else ["--tools", ",".join(tools)]),
            "--settings",
            str(path),
            *[
                x
                for d in args.plugin_dir
                for x in ("--plugin-dir", str(Path(d).resolve()))
            ],
        ],
        str(run / "supervise"),
        prompt=args.prompt,
        name=name,
    )
    try:
        reply = herdrtab.open_tab(args.space, name, str(folder), argv)
    except herdrtab.TabError as error:
        sys.exit(f"testtab: no tab opened: {error}")
    (run / f"tabnew_{name}.json").write_text(json.dumps(reply), encoding="utf-8")
    terminal = reply["terminal"]
    ok, why = herdrtab.watch(terminal, args.wait, ready=READY)
    result = {"name": name, "terminal": terminal, "ready": ok, "why": why}
    sys.stdout.write(json.dumps(result) + "\n")
    if not ok:
        sys.stderr.write(
            f"testtab: handing {name} ({terminal}) to the owner: {why}; nothing more is sent to it\n"
        )
        sys.exit(HANDOFF)


if __name__ == "__main__":
    main()
