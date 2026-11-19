"""Launch an agy worker in a ticket's worktree from the reviewed rules file, after a sign-in preflight (#278).

  python -I agy_worker.py WORKTREE BRIEF [--plan PLAN_ID] [--model M] [--dry-run]

Refuses (exit 3, nothing started) a worktree that is not a folder directly under a `cpp-standard.worktrees`
folder, a missing brief, a missing plan folder, and an agy that is not signed in. The plan folder is
`cpp-standard.plans/.planning/<PLAN_ID>` beside `cpp-standard.worktrees`; PLAN_ID comes from --plan or the
environment. The preflight starts agy in a scratch folder with one trivial prompt and reads the reply: "Sign-in
update needed" or "not signed in" stops the launch and names the fix. The rules are
`.agents/agy-worker-settings.json`, passed with --settings, so the owner's own agy settings are never written.
--dry-run prints the launch line and runs no agy. Exit 2 is a usage error.
"""

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE.parent.parent / ".agents" / "agy-worker-settings.json"
WORKTREES = "cpp-standard.worktrees"
PLANS = "cpp-standard.plans"
MODEL = "gemini-pro-orchestrator-neon"
PROBE = "Reply with only the word ok. Do not run any tool."
REFUSED = 3
# Markers from the ticket and the owner's rules; no capture of print mode's own wording exists yet.
STALE = ("sign-in update needed",)
SIGNED_OUT = ("not signed in",)
FIX = (
    "type /logout in agy, then sign in with Google again (the owner does any password, passkey or 2FA step); "
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
    what = {
        "stale": "agy shows 'Sign-in update needed'",
        "signed-out": "agy is not signed in",
    }.get(state, "agy did not answer the probe with ok")
    return f"{what}; fix: {FIX}"


def preflight(agy: str = "agy", timeout: float = 180) -> str:
    """Start agy in a scratch folder, send the probe, return the sign-in state of what it printed."""
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
    return signin_state(done.stdout, done.stderr, done.returncode)


def check_launch(
    worktree: Path, brief: Path, plan_id: str | None
) -> tuple[Path, Path, Path]:
    """Validate the paths; return the resolved worktree, brief and plan folder."""
    wt = worktree.expanduser().resolve()
    if wt.parent.name != WORKTREES:
        raise RefusedError(f"{wt} is not a folder directly under {WORKTREES}/")
    if not wt.is_dir():
        raise RefusedError(f"worktree {wt} does not exist")
    br = brief.expanduser().resolve()
    if not br.is_file():
        raise RefusedError(f"brief {br} does not exist")
    if not plan_id:
        raise RefusedError("no plan: pass --plan PLAN_ID or export PLAN_ID")
    plan = wt.parent.parent / PLANS / ".planning" / plan_id
    if not plan.is_dir():
        raise RefusedError(f"plan folder {plan} does not exist")
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
    ap.add_argument("worktree", type=Path)
    ap.add_argument("brief", type=Path)
    ap.add_argument("--plan", default=os.environ.get("PLAN_ID"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        wt, brief, plan = check_launch(args.worktree, args.brief, args.plan)
        if not SETTINGS.is_file():
            raise RefusedError(f"rules file {SETTINGS} is missing")
        cmd = build_argv(wt, brief, plan, args.model)
        if args.dry_run:
            print(shlex.join(cmd))
            return 0
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
