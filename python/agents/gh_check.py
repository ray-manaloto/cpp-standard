"""Check .mise/tasks/agent/gh against #295's acceptance lines, offline: stand-in mise and gh executables on PATH
logging every argument list, never GitHub. Prints one line per case and exits 1 when any fails.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / ".mise/tasks/agent/gh"
STANDIN = """#!{python} -I
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["STANDIN_LOG"], "a") as log:
    log.write(json.dumps([name, os.environ.get("GH_TOKEN", ""), *sys.argv[1:]]) + "\\n")
if name == "mise":
    print(os.environ["STANDIN_TOKEN"])
elif sys.argv[1] == "api":
    print(os.environ["STANDIN_LOGIN"])
elif sys.argv[1:3] == ["issue", "create"]:
    print("https://github.com/o/r/issues/9")
elif sys.argv[1:3] == ["issue", "view"]:
    print(os.environ["STANDIN_AUTHOR"])
"""


def call(
    root: Path, args: list[str], token: str, login: str, author: str
) -> tuple[int, str, list[list[str]]]:
    log = root / "log.jsonl"
    log.unlink(missing_ok=True)
    env = {
        "PATH": f"{root / 'bin'}:/usr/bin:/bin",
        "HOME": str(root),
        "STANDIN_LOG": str(log),
        "STANDIN_TOKEN": token,
        "STANDIN_LOGIN": login,
        "STANDIN_AUTHOR": author,
        "usage_args": " ".join(args),
    }
    done = subprocess.run(
        ["/bin/bash", str(TASK)],
        env=env,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    calls = (
        [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
    )
    return done.returncode, done.stderr, calls


def main() -> int:
    failures: list[str] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + detail}")
        if not ok:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "bin").mkdir()
        for name in ("mise", "gh"):
            path = root / "bin" / name
            path.write_text(STANDIN.format(python=sys.executable), encoding="utf-8")
            path.chmod(0o755)
        bot = "cpp-standard-agents[bot]"

        code, err, calls = call(root, ["issue", "list"], "", bot, bot)
        case("empty token fails", code == 1, err)
        case("empty token names agent:token", "agent:token" in err, err)
        case(
            "empty token makes no gh call",
            all(c[0] == "mise" for c in calls),
            str(calls),
        )

        code, err, calls = call(root, ["issue", "list"], "tok", "sortakool", bot)
        case("person login fails", code == 1 and "not an App" in err, err)
        case(
            "person login makes no write call",
            not any(c[1:3] == ["tok", "issue"] for c in calls),
            str(calls),
        )

        code, err, calls = call(root, ["pr", "comment", "3"], "tok", bot, bot)
        gh = [c for c in calls if c[0] == "gh" and c[2] != "api"]
        case(
            "write runs with the App token",
            code == 0 and gh == [["gh", "tok", "pr", "comment", "3"]],
            str(calls),
        )

        code, err, calls = call(
            root, ["issue", "create", "--title", "T"], "tok", bot, bot
        )
        views = [c for c in calls if c[2:4] == ["issue", "view"]]
        case(
            "issue create checks the author after",
            code == 0 and len(views) == 1 and bot in err,
            err + str(calls),
        )

        code, err, _ = call(
            root, ["issue", "create", "--title", "T"], "tok", bot, "sortakool"
        )
        case(
            "issue create by a person fails",
            code == 1 and "not authored by the App" in err,
            err,
        )

    print("FAILED" if failures else "all cases passed")
    return 1 if failures else 0


sys.exit(main())
