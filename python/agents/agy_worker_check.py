"""Check agy_worker.py against #278's acceptance lines, offline: a stand-in `agy` on PATH, scratch worktree, brief and
plan folders. It never starts the real agy or reads its settings. Prints one line per case and exits 1 when any fails.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agy_worker

STANDIN = """#!{python} -I
import json, os, sys
if "-p" in sys.argv:
    print(open(os.environ["STANDIN_SCREEN"]).read())
    sys.exit(int(os.environ.get("STANDIN_RC", "0")))
else:
    with open(os.environ["STANDIN_LOG"], "w") as log:
        log.write(json.dumps(sys.argv[1:]))
"""
SCREENS = {
    "signed-in": "ok\n",
    "stale": "Sign-in update needed\n  Your Google sign-in has expired. Run /logout, then sign in again.\n> \n",
    "signed-out": "You are not signed in. Run agy to sign in.\n",
    "blank": "\n",
    "echo": "Error: could not run 'Reply with only the word ok. Do not run any tool.'\n",
}
# The screens are synthetic: nobody has captured what `agy -p` prints with a stale sign-in (see HANDBACK.md).
PLAN = "2026-01-01-1-x"


def run(
    root: Path, screen: str, *args: str, plan: bool = True, rc: int = 0
) -> tuple[int, str, list[str] | None]:
    log = root / "agy.log"
    log.unlink(missing_ok=True)
    (root / "screen.txt").write_text(SCREENS[screen])
    # Inherited, so coverage's subprocess patch reaches the child (agents:cov).
    env = {k: v for k, v in os.environ.items() if k != "PLAN_ID"} | {
        "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
        "STANDIN_SCREEN": str(root / "screen.txt"),
        "STANDIN_LOG": str(log),
        "STANDIN_RC": str(rc),
    }
    if plan:
        env["PLAN_ID"] = PLAN
    done = subprocess.run(
        [sys.executable, "-I", str(HERE / "agy_worker.py"), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return (
        done.returncode,
        done.stderr + done.stdout,
        json.loads(log.read_text()) if log.exists() else None,
    )


def main() -> int:
    failures: list[str] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        print(
            f"{'ok  ' if ok else 'FAIL'} {name}"
            + (f": {detail}" if detail and not ok else "")
        )
        if not ok:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / "bin").mkdir()
        standin = root / "bin" / "agy"
        standin.write_text(STANDIN.format(python=sys.executable))
        standin.chmod(0o755)
        wt = root / agy_worker.WORKTREES / "t1"
        wt.mkdir(parents=True)
        plan = root / agy_worker.PLANS / ".planning" / PLAN
        plan.mkdir(parents=True)
        briefs = root / "briefs"
        briefs.mkdir()
        brief = briefs / "brief.md"
        brief.write_text("do it\n")

        case(
            "classifier: stale screen",
            agy_worker.signin_state(SCREENS["stale"]) == "stale",
        )
        case(
            "classifier: not signed in",
            agy_worker.signin_state(SCREENS["signed-out"]) == "signed-out",
        )
        case(
            "classifier: signed in",
            agy_worker.signin_state(SCREENS["signed-in"]) == "ok",
        )
        case(
            "classifier: blank is unknown",
            agy_worker.signin_state(SCREENS["blank"]) == "unknown",
        )
        case("signed in: no refusal", agy_worker.refusal_for("ok") is None)

        rc, out, argv = run(root, "stale", str(wt), str(brief))
        case(
            "stale sign-in: refuses, names the fix, starts no worker",
            rc == 3
            and "Sign-in update needed" in out
            and "/logout" in out
            and argv is None,
            out,
        )
        rc, out, argv = run(root, "signed-out", str(wt), str(brief))
        case(
            "not signed in: refuses, names the fix",
            rc == 3 and "/logout" in out and argv is None,
            out,
        )
        rc, out, argv = run(root, "blank", str(wt), str(brief))
        case("no ok reply: refuses", rc == 3 and argv is None, out)

        rc, out, argv = run(root, "echo", str(wt), str(brief))
        case("an error that quotes the probe: refuses", rc == 3 and argv is None, out)
        rc, out, argv = run(root, "signed-in", str(wt), str(brief), rc=1)
        case("ok reply with a nonzero exit: refuses", rc == 3 and argv is None, out)
        case(
            "classifier: nonzero exit is unknown",
            agy_worker.signin_state("ok", "", 1) == "unknown",
        )

        rc, out, argv = run(root, "signed-in", str(wt), str(brief))
        flags = {
            "--settings": str(agy_worker.SETTINGS),
            "--mode": "auto",
            "--model": agy_worker.MODEL,
        }
        adds = [argv[i + 1] for i, a in enumerate(argv or []) if a == "--add-dir"]
        case(
            "signed in: starts agy with settings, mode, model",
            rc == 0
            and argv is not None
            and all(argv[argv.index(k) + 1] == v for k, v in flags.items()),
            out,
        )
        case(
            "signed in: --add-dir for worktree, brief folder and plan folder",
            adds == [str(wt), str(briefs), str(plan)],
            str(adds),
        )
        case(
            "signed in: first prompt names the brief",
            argv is not None and str(brief) in argv[-1],
        )

        rc, out, argv = run(root, "signed-in", str(root), str(brief))
        case(
            "worktree outside cpp-standard.worktrees: refused",
            rc == 3 and argv is None,
            out,
        )
        rc, out, argv = run(root, "signed-in", str(wt), str(briefs / "none.md"))
        case("missing brief: refused", rc == 3 and argv is None, out)
        rc, out, argv = run(root, "signed-in", str(wt), str(brief), plan=False)
        case("no plan id: refused", rc == 3 and argv is None, out)
        rc, out, argv = run(root, "signed-in", str(wt), str(brief), "--plan", "nope")
        case("missing plan folder: refused", rc == 3 and argv is None, out)

        settings = json.loads(agy_worker.SETTINGS.read_text())["permissions"]
        denied = {
            "docker",
            "ssh",
            "scp",
            "sudo",
            "gh",
            "git push",
            "git commit",
            "git stash",
            "fnox",
            "hk",
        }
        case(
            "rules: every deny from #278", {r[8:-1] for r in settings["deny"]} == denied
        )
        allowed = {r[8:-1] for r in settings["allow"]}
        case(
            "rules: no allow rule overlaps a deny",
            not allowed & denied and "git push" not in allowed,
        )

    print(f"{len(failures)} failed" if failures else "all cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
