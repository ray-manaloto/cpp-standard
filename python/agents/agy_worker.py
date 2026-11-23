"""Launch an agy worker in a ticket's worktree from the reviewed rules file, after a sign-in preflight (#278).

  python -I agy_worker.py WORKTREE BRIEF [--plan PLAN_ID] [--model M] [--dry-run]
  python -I agy_worker.py --health

Refuses (exit 3, nothing started) a path that is not a linked git worktree (the main checkout, a plain folder), a
worktree that is not directly under the worktrees root, a missing brief, a missing plan folder, and an agy that is
not signed in. The layout comes from the target repository's own mise env (`mise -C <main checkout> env --json`):
`AGY_WORKTREE_ROOT` is the worktrees root (default `<main checkout>.worktrees` beside the main checkout) and
`PWF_PLAN_ROOT`, the variable workflowtools uses, is the plans root (default `<main checkout>.plans`). The plan
folder is `<plans root>/.planning/<PLAN_ID>`; PLAN_ID comes from --plan or the environment. The preflight starts agy in a scratch folder with one trivial prompt and reads the reply: "Sign-in
update needed" or "not signed in" stops the launch and names the fix. The rules are
`.agents/agy-worker-settings.json`, passed with --settings, so the owner's own agy settings are never written.
--dry-run prints the launch line and runs no agy. Exit 2 is a usage error.

The banner "Sign-in update needed" is a TUI warning that `agy -p` never prints, so the preflight also reads agy's own
log: a launch whose stored sign-in lacks the aicode scope logs "OAuth token lacks .../auth/aicode" (aicode_scope.go).
Both the guard (after the probe, on the log the probe just wrote) and `--health` (the newest log, no agy run; the
doctor line) use it. Never reads a token or login file, only the log text. Antigravity.app shares agy's one
keychain entry (upstream antigravity-cli #1610), so the launch refuses while it runs (`agy:ide-stop`) and the health line says so.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agy_ide

SETTINGS = HERE.parent.parent / ".agents" / "agy-worker-settings.json"
WORKTREE_VAR = "AGY_WORKTREE_ROOT"
PLANS_VAR = "PWF_PLAN_ROOT"
MODEL = "gemini-pro-orchestrator-neon"
PROBE = "Reply with only the word ok. Do not run any tool."
REFUSED = 3
LOG_DIR = Path.home() / ".gemini" / "antigravity-cli" / "log"
LACKS = re.compile(r"OAuth token lacks \S*/auth/aicode")
# Markers from the ticket and the owner's rules; no capture of print mode's own wording exists yet.
STALE = ("sign-in update needed",)
SIGNED_OUT = ("not signed in",)
FIX = (
    "type /logout in agy, then quit and restart agy; it opens the Google sign-in (the owner ticks every permission box and does any password, passkey or 2FA step); "
    "`mise run agents:agy-login` --step status only sees that a login file exists, so it does not prove this"
)


class RefusedError(Exception):
    """The launch is refused before any worker starts."""


def signin_state(stdout: str, stderr: str = "", returncode: int = 0) -> str:
    """Classify agy's answer to the probe: "stale", "signed-out", "ok" or "unknown".

    ok needs exit 0 and a stdout reply that is the word ok by itself, so an error that quotes the probe is not ok.
    """
    low = f"{stdout}\n{stderr}".lower()
    if any(m in low for m in STALE):
        return "stale"
    if any(m in low for m in SIGNED_OUT):
        return "signed-out"
    reply = stdout.strip().lower().strip(".! ")
    return "ok" if returncode == 0 and reply == "ok" else "unknown"


def refusal_for(state: str) -> str | None:
    """The refusal message for a preflight state, or None when the worker may start."""
    if state == "ok":
        return None
    if state == "scope":
        return scope_refusal()
    what = {
        "stale": "agy shows 'Sign-in update needed'",
        "signed-out": "agy is not signed in",
    }.get(state, "agy did not answer the probe with ok")
    return f"{what}; fix: {FIX}"


def log_dir() -> Path:
    return Path(os.environ.get("AGY_LOG_DIR") or LOG_DIR)


def newest_log(since: float | None = None) -> Path | None:
    """agy's newest per-launch log (cli-<date>_<time>.log), or None; with since, only one written at or after it."""
    logs = sorted(log_dir().glob("cli-[0-9]*.log"))
    if since is not None:
        logs = [p for p in logs if p.stat().st_mtime >= since]
    return logs[-1] if logs else None


def scope_state(log: Path | None) -> str:
    """ "stale" when the launch logged a token without the aicode scope, "ok" when it did not, "unknown" with no log."""
    if log is None:
        return "unknown"
    return "stale" if LACKS.search(log.read_text(errors="replace")) else "ok"


def ide_running() -> bool:
    """True while Antigravity.app runs; it shares agy's keychain sign-in."""
    return agy_ide.app_running(agy_ide.APPS["antigravity"])


IDE_REFUSAL = (
    "Antigravity.app is running and shares agy's sign-in; "
    "run `mise run agy:ide-stop` (owner OK) and retry."
)


def scope_refusal() -> str:
    """The refusal for a sign-in that lacks the aicode scope: the owner step, and the IDE when it is running."""
    msg = (
        "owner: type /logout in agy, then quit and restart agy; it opens the Google sign-in "
        "(tick every permission box and do any password, passkey or 2FA step)"
    )
    return f"agy's sign-in lacks the aicode scope; {msg}"


def health() -> tuple[int, str]:
    """The doctor line: exit code and text, from the newest agy log; runs no agy."""
    state = scope_state(newest_log())
    ide = (
        " (Antigravity.app is running and shares agy's sign-in; run `mise run agy:ide-stop`, owner OK)"
        if ide_running()
        else ""
    )
    if state == "stale":
        return (
            1,
            f"MISSING agy sign-in lacks the aicode scope in the newest log; owner: type /logout in agy, then quit and restart agy{ide}",
        )
    if state == "unknown":
        return 0, f"ok    agy sign-in: no agy log yet{ide}"
    return 0, f"ok    agy sign-in: newest log shows the aicode scope{ide}"


def preflight(agy: str = "agy", timeout: float = 180) -> str:
    """Start agy in a scratch folder, send the probe, return the sign-in state of what it printed and logged."""
    started = time.time() - 1
    with tempfile.TemporaryDirectory() as scratch:
        try:
            done = subprocess.run(
                [agy, "-p", PROBE],
                check=False,
                cwd=scratch,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return "unknown"
        except FileNotFoundError as err:
            raise RefusedError(f"agy is not installed: {err}") from err
    state = signin_state(done.stdout, done.stderr, done.returncode)
    if state == "ok" and scope_state(newest_log(started)) == "stale":
        return "scope"
    return state


def _git(wt: Path, *args: str) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(wt), *args], check=False, capture_output=True, text=True
    )
    return done.stdout.strip() if done.returncode == 0 else None


def main_checkout(wt: Path) -> Path:
    """The main checkout of the repository a linked worktree belongs to; refuses what is not a linked worktree."""
    git_file = wt / ".git"
    if not git_file.is_file():
        raise RefusedError(
            f"{wt} is not a linked git worktree (its .git is not a file); "
            "the main checkout and plain folders are refused"
        )
    common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    gitdir = _git(wt, "rev-parse", "--path-format=absolute", "--git-dir")
    if not common or not gitdir or Path(common) == Path(gitdir):
        raise RefusedError(f"{wt} is not a linked git worktree of a repository")
    return Path(common).resolve().parent


def repo_env(main: Path) -> dict[str, str]:
    """The target repository's mise env; empty when mise or its config is unavailable."""
    try:
        done = subprocess.run(
            ["mise", "-C", str(main), "env", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=os.environ | {"MISE_ENV_CACHE": "0"},
        )
        env = json.loads(done.stdout) if done.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}
    return env if isinstance(env, dict) else {}


def layout(worktree: Path) -> tuple[Path, Path]:
    """(worktrees_root, plans_root) for the repository of a linked worktree.

    AGY_WORKTREE_ROOT and PWF_PLAN_ROOT from the repository's mise env win; the defaults are
    `<main checkout>.worktrees` and `<main checkout>.plans` beside the main checkout.
    """
    main = main_checkout(worktree.expanduser().resolve())
    env = repo_env(main)

    def pick(var: str, default: str) -> Path:
        value = env.get(var)
        base = Path(value).expanduser() if value else main.parent / default
        return (main / base).resolve()

    return (
        pick(WORKTREE_VAR, f"{main.name}.worktrees"),
        pick(PLANS_VAR, f"{main.name}.plans"),
    )


def check_launch(
    worktree: Path, brief: Path, plan_id: str | None
) -> tuple[Path, Path, Path]:
    """Validate the paths; return the resolved worktree, brief and plan folder."""
    wt = worktree.expanduser().resolve()
    if not wt.is_dir():
        raise RefusedError(f"worktree {wt} does not exist")
    worktrees_root, plans_root = layout(wt)
    if wt.parent != worktrees_root:
        raise RefusedError(
            f"{wt} is not a folder directly under the worktrees root {worktrees_root} "
            f"(set by {WORKTREE_VAR} in the repository's mise env, default <main checkout>.worktrees)"
        )
    br = brief.expanduser().resolve()
    if not br.is_file():
        raise RefusedError(f"brief {br} does not exist")
    if not plan_id:
        raise RefusedError("no plan: pass --plan PLAN_ID or export PLAN_ID")
    plan = plans_root / ".planning" / plan_id
    if not plan.is_dir():
        raise RefusedError(
            f"plan folder {plan} does not exist (plans root {plans_root}, "
            f"set by {PLANS_VAR} in the repository's mise env, default <main checkout>.plans)"
        )
    return wt, br, plan


def build_argv(
    wt: Path, brief: Path, plan: Path, model: str = MODEL, settings: Path = SETTINGS
) -> list[str]:
    """The agy launch line: session-only rules, the worktree, the brief's folder and the plan folder."""
    prompt = f"Read {brief} and follow it. Work only in {wt}."
    return [
        "agy",
        "--settings",
        str(settings),
        "--add-dir",
        str(wt),
        "--add-dir",
        str(brief.parent),
        "--add-dir",
        str(plan),
        "--mode",
        "auto",
        "--model",
        model,
        "-i",
        prompt,
    ]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="agents:agy-worker")
    ap.add_argument("worktree", type=Path, nargs="?")
    ap.add_argument("brief", type=Path, nargs="?")
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--plan", default=os.environ.get("PLAN_ID"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.health:
        code, line = health()
        print(line)
        return code
    if args.worktree is None or args.brief is None:
        ap.error("WORKTREE and BRIEF are required")
    try:
        wt, brief, plan = check_launch(args.worktree, args.brief, args.plan)
        if not SETTINGS.is_file():
            raise RefusedError(f"rules file {SETTINGS} is missing")
        cmd = build_argv(wt, brief, plan, args.model)
        if args.dry_run:
            print(shlex.join(cmd))
            return 0
        if ide_running():
            raise RefusedError(IDE_REFUSAL)
        msg = refusal_for(preflight())
        if msg:
            raise RefusedError(msg)
    except RefusedError as err:
        print(f"agents:agy-worker: refused: {err}", file=sys.stderr)
        return REFUSED
    os.chdir(wt)
    os.execvp(cmd[0], cmd)
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
