"""Check agy_worker.py against #278's acceptance lines and the rules of D178, offline: a stand-in `agy` on PATH, scratch worktree, brief and
plan folders. It never starts the real agy or reads its settings. Prints one line per case and exits 1 when any fails.
"""

import json
import os
import shutil
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
    if os.environ.get("STANDIN_AGYLOG"):
        os.makedirs(os.environ["AGY_LOG_DIR"], exist_ok=True)
        with open(os.path.join(os.environ["AGY_LOG_DIR"], "cli-20990101_000000.log"), "w") as lg:
            lg.write(os.environ["STANDIN_AGYLOG"] + "\\n")
    print(open(os.environ["STANDIN_SCREEN"]).read())
    sys.exit(int(os.environ.get("STANDIN_RC", "0")))
else:
    with open(os.environ["STANDIN_LOG"], "w") as log:
        log.write(json.dumps(sys.argv[1:]))
"""
OSASCRIPT = """#!/bin/sh\nif [ "${STANDIN_IDE:-1}" = 0 ]; then echo true; else echo false; fi\n"""
LACKS_LINE = "E1119 03:49:29.1 aicode_scope.go:88] OAuth token lacks https://www.googleapis.com/auth/aicode; routing AICode traffic to CCPA"
SCREENS = {
    "signed-in": "ok\n",
    "stale": "Sign-in update needed\n  Your Google sign-in has expired. Run /logout, then sign in again.\n> \n",
    "signed-out": "You are not signed in. Run agy to sign in.\n",
    "blank": "\n",
    "echo": "Error: could not run 'Reply with only the word ok. Do not run any tool.'\n",
}
# The screens are synthetic: nobody has captured what `agy -p` prints with a stale sign-in (see HANDBACK.md).
PLAN = "2026-01-01-1-x"


def sh(*cmd: str, cwd: Path) -> None:
    subprocess.run(cmd, check=True, cwd=cwd, capture_output=True)


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    sh("git", "init", "-q", "-b", "main", cwd=path)
    sh(
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
        cwd=path,
    )
    return path


def add_worktree(repo: Path, wt: Path) -> Path:
    wt.parent.mkdir(parents=True, exist_ok=True)
    sh("git", "worktree", "add", "-q", "-b", wt.name, str(wt), cwd=repo)
    return wt.resolve()


def run(
    root: Path,
    screen: str,
    *args: str,
    plan: bool = True,
    rc: int = 0,
    agylog: str = "",
    ide: bool = False,
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
        "STANDIN_IDE": "0" if ide else "1",
        "STANDIN_AGYLOG": agylog,
        "AGY_LOG_DIR": str(root / "logs"),
        "MISE_TRUSTED_CONFIG_PATHS": str(root),
        # Prove repo_env disables stale mise env caching even when caller shells export MISE_ENV_CACHE=1.
        "MISE_ENV_CACHE": "1",
    }
    shutil.rmtree(root / "logs", ignore_errors=True)
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
        osa = root / "bin" / "osascript"
        osa.write_text(OSASCRIPT)
        osa.chmod(0o755)
        repo = git_repo(root / "demo")
        wt = add_worktree(repo, root / "demo.worktrees" / "t1")
        plan = root / "demo.plans" / ".planning" / PLAN
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

        rc, out, argv = run(root, "signed-in", str(wt), str(brief), agylog=LACKS_LINE)
        case(
            "ok reply but the log lacks aicode: refuses with the owner step, starts no worker",
            rc == 3
            and "owner: type /logout" in out
            and "aicode" in out
            and "IDE" not in out
            and argv is None,
            out,
        )
        rc, out, argv = run(
            root, "signed-in", str(wt), str(brief), agylog=LACKS_LINE, ide=True
        )
        case(
            "Antigravity.app running: refuses before the probe with the exact text, even when signed in",
            rc == 3
            and agy_worker.IDE_REFUSAL in out
            and "agy:ide-stop" in out
            and argv is None,
            out,
        )
        rc, out, argv = run(
            root, "signed-in", str(wt), str(brief), agylog="I1119 Auth succeeded"
        )
        case(
            "log without the lacks line: starts the worker",
            rc == 0 and argv is not None,
            out,
        )

        env = {
            "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
            "AGY_LOG_DIR": str(root / "hl"),
        }
        for name, line, ide, want_rc, want in (
            ("no log", None, False, 0, "no agy log yet"),
            ("good log", "I1119 Auth succeeded", False, 0, "shows the aicode scope"),
            ("lacking log", LACKS_LINE, False, 1, "MISSING"),
            (
                "lacking log, IDE running",
                LACKS_LINE,
                True,
                1,
                "Antigravity.app is running",
            ),
        ):
            shutil.rmtree(root / "hl", ignore_errors=True)
            if line:
                (root / "hl").mkdir()
                (root / "hl" / "cli-20990101_000000.log").write_text(line + "\n")
            done = subprocess.run(
                [sys.executable, "-I", str(HERE / "agy_worker.py"), "--health"],
                check=False,
                capture_output=True,
                text=True,
                env=env | {"STANDIN_IDE": "0" if ide else "1"},
            )
            case(
                f"--health: {name}",
                done.returncode == want_rc and want in done.stdout,
                done.stdout + done.stderr,
            )

        pg = root / "bin" / "pgrep"
        pg.write_text(
            '#!/bin/sh\n[ -n "$STANDIN_LS" ] && echo "$STANDIN_LS language_server --standalone"; exit 0\n'
        )
        pg.chmod(0o755)
        for name, ide, ls, want_rc, want in (
            ("idle", False, "", 0, "com.google.antigravity: not running"),
            ("app running", True, "", 1, "com.google.antigravity: running"),
            ("language_server left", False, "4242", 1, "language_server pids 4242"),
        ):
            done = subprocess.run(
                [sys.executable, "-I", str(HERE / "agy_ide.py"), "status"],
                check=False,
                capture_output=True,
                text=True,
                env=env | {"STANDIN_IDE": "0" if ide else "1", "STANDIN_LS": ls},
            )
            case(
                f"agy_ide status: {name}",
                done.returncode == want_rc and want in done.stdout,
                done.stdout + done.stderr,
            )
        done = subprocess.run(
            [sys.executable, "-I", str(HERE / "agy_ide.py"), "status", "--app", "ide"],
            check=False,
            capture_output=True,
            text=True,
            env=env | {"STANDIN_IDE": "1"},
        )
        case(
            "agy_ide status --app ide names com.google.antigravity-ide",
            "com.google.antigravity-ide" in done.stdout,
            done.stdout,
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
            "a plain folder that is no worktree: refused", rc == 3 and argv is None, out
        )
        rc, out, argv = run(root, "signed-in", str(repo), str(brief))
        case(
            "the main checkout, no layout variables: refused",
            rc == 3 and "not a linked git worktree" in out and argv is None,
            out,
        )
        plain = root / "demo.worktrees" / "plain"
        plain.mkdir()
        rc, out, argv = run(root, "signed-in", str(plain), str(brief))
        case(
            "a plain folder under the worktrees root: refused",
            rc == 3 and "not a linked git worktree" in out and argv is None,
            out,
        )
        elsewhere = add_worktree(repo, root / "elsewhere" / "t2")
        rc, out, argv = run(root, "signed-in", str(elsewhere), str(brief))
        case(
            "a linked worktree outside the worktrees root: refused, names the root and variable",
            rc == 3
            and str(root / "demo.worktrees") in out
            and "AGY_WORKTREE_ROOT" in out
            and argv is None,
            out,
        )
        noplan = add_worktree(repo, root / "demo.worktrees" / "t3")
        rc, out, argv = run(
            root, "signed-in", str(noplan), str(brief), "--plan", "nope"
        )
        case(
            "missing plan folder: refused, names the plans root and variable",
            rc == 3
            and str(root / "demo.plans") in out
            and "PWF_PLAN_ROOT" in out
            and argv is None,
            out,
        )

        # A kb-shaped layout: the repository sets its own roots in its mise.toml.
        kb = git_repo(root / "demo-v2")
        (kb / "mise.toml").write_text(
            f'[env]\nAGY_WORKTREE_ROOT = "{root / "demo-v2-wt"}"\n'
        )
        kbwt = add_worktree(kb, root / "demo-v2-wt" / "t1")
        kbplan = root / "demo-v2.plans" / ".planning" / PLAN
        kbplan.mkdir(parents=True)
        rc, out, argv = run(root, "signed-in", str(kbwt), str(brief))
        adds = [argv[i + 1] for i, a in enumerate(argv or []) if a == "--add-dir"]
        case(
            "kb-shaped layout (AGY_WORKTREE_ROOT, default plans root): starts the worker",
            rc == 0 and adds[:1] == [str(kbwt)] and adds[-1:] == [str(kbplan)],
            out + str(adds),
        )
        rc, out, argv = run(root, "signed-in", str(kb), str(brief))
        case(
            "kb-shaped main checkout, variables set: refused",
            rc == 3 and "not a linked git worktree" in out and argv is None,
            out,
        )
        (kb / "mise.toml").write_text(
            f'[env]\nAGY_WORKTREE_ROOT = "{root / "demo-v2-wt"}"\n'
            f'PWF_PLAN_ROOT = "{root / "plans-elsewhere"}"\n'
        )
        rc, out, argv = run(root, "signed-in", str(kbwt), str(brief))
        case(
            "PWF_PLAN_ROOT moves the plans root: the old plan folder is refused",
            rc == 3 and str(root / "plans-elsewhere") in out and argv is None,
            out,
        )
        rc, out, argv = run(root, "signed-in", str(wt), str(briefs / "none.md"))
        case("missing brief: refused", rc == 3 and argv is None, out)
        rc, out, argv = run(root, "signed-in", str(wt), str(brief), plan=False)
        case("no plan id: refused", rc == 3 and argv is None, out)
        rc, out, argv = run(root, "signed-in", str(wt), str(brief), "--plan", "nope")
        case("missing plan folder: refused", rc == 3 and argv is None, out)

        settings = json.loads(agy_worker.SETTINGS.read_text())["permissions"]
        rules = {k: {r[8:-1] for r in settings[k]} for k in ("allow", "ask", "deny")}
        # The owner's ruling of 2026-11-19 (D178): agy gets a Claude worker's checks; commit, push, gh, docker, ssh
        # and scp stay asks; what every agent is denied stays denied.
        want_allow = {"hk check", "ty", "pytest", "typos", "ruff", "rumdl", "git add"}
        want_ask = {
            "docker",
            "ssh",
            "scp",
            "gh",
            "git commit",
            "git push",
            "repotools pr-create",
            "mise run //repo:pr-merge",
            "hk check --all",
        }
        want_deny = {
            "sudo",
            "fnox get",
            "fnox exec",
            "fnox export",
            "fnox set",
            "git stash",
            "git add -A",
            "git add .",
        }
        case("rules: the checks are allowed", want_allow <= rules["allow"])
        case("rules: commit, push, gh, docker, ssh, scp ask", want_ask <= rules["ask"])
        case("rules: the shared denies hold", want_deny <= rules["deny"])
        case(
            "rules: --no-verify, --admin and a force push without lease are denied",
            all(
                any(flag in r for r in rules["deny"])
                for flag in ("--no-verify", "--admin", "(-f|--force)")
            ),
        )
        case(
            "rules: no ask or deny rule is also an allow",
            not rules["allow"] & (rules["ask"] | rules["deny"]),
        )
        case(
            "rules: nothing that ships is allowed",
            not any(
                r.split()[0] in {"gh", "docker", "ssh", "scp", "sudo", "fnox"}
                or r.startswith(
                    ("git push", "git commit", "repotools", "mise run //repo")
                )
                for r in rules["allow"]
            ),
        )

    print(f"{len(failures)} failed" if failures else "all cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
