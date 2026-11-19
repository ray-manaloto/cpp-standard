"""Check herdrtab.py against #200's acceptance lines, offline: stand-in herdr-app and hc executables on PATH, never a
real herdr tab. Prints one line per case and exits 1 when any fails.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
STANDIN = """#!{python} -I
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["STANDIN_LOG"], "a") as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "herdr-app" and sys.argv[1] == "ls":
    if os.environ.get("STANDIN_LS_FAIL"):
        sys.exit(1)
    print(open(os.environ["STANDIN_LS"]).read())
elif name == "herdr-app" and sys.argv[2] == "tab.new":
    print(json.dumps({{"space": sys.argv[4], "tab": "tbnew", "terminal": "t9"}}))
elif name == "herdr-app":
    print(json.dumps({{"ok": True}}))
else:
    print(open(os.environ["STANDIN_SCREEN"]).read())
"""
SPACES = {
    "spaces": [
        {"id": "sp1", "tabs": [{"id": "tb1", "terminals": [{"terminal": "t1"}]}]},
        {
            "id": "sp2",
            "tabs": [
                {"id": "tb2", "terminals": [{"terminal": "tmine"}]},
                {"id": "tb3", "terminals": [{"terminal": "t3"}]},
            ],
        },
    ]
}
TASK = "Read AGENTS.md"
DIALOG = "Do you trust the files in this folder?\n> 1. Yes, I trust this folder\n"
ODD = "say \"hi\" and 'bye'\nthen naïve café — ✓ $HOME `x`"


def call(
    root: Path,
    args: list[str],
    screen: str = "",
    spaces: object = SPACES,
    ls_fail: bool = False,
) -> tuple[int, str, str, list[list[str]]]:
    """Run herdrtab.py once; return exit code, stdout, stderr and the stand-in calls."""
    log, screen_file, ls_file = root / "log.jsonl", root / "screen", root / "ls.json"
    for path in (log, screen_file, ls_file):
        path.unlink(missing_ok=True)
    screen_file.write_text(screen, encoding="utf-8")
    ls_file.write_text(json.dumps(spaces), encoding="utf-8")
    env = {
        "PATH": f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "HC_TERMINAL_ID": "tmine",
        "STANDIN_LOG": str(log),
        "STANDIN_SCREEN": str(screen_file),
        "STANDIN_LS": str(ls_file),
        **({"STANDIN_LS_FAIL": "1"} if ls_fail else {}),
    }
    done = subprocess.run(
        [sys.executable, "-I", str(HERE / "herdrtab.py"), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = (
        [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    return done.returncode, done.stdout, done.stderr, calls


def tab_new(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if c[:3] == ["herdr-app", "do", "tab.new"]]


def cases(root: Path) -> list[tuple[str, Callable[[], bool]]]:
    def tab(agent: str, task: str = TASK, screen: str | None = None) -> tuple:
        return call(
            root,
            ["tab", "--agent", agent, "--name", "w1", "--task", task, "--wait", "1"],
            screen=task if screen is None else screen,
        )

    def opens(agent: str, first: str) -> bool:
        code, out, _, calls = tab(agent)
        (new,) = tab_new(calls)
        lines = out.splitlines()
        info = json.loads(lines[0])
        return (
            code == 0
            and new[new.index("--space") + 1] == "sp2"
            and json.loads(new[-1]) == [first, TASK]
            and lines[-1] == "w1 (t9)"
            and info["tab"] == "tbnew"
        )

    def no_space(ls_fail: bool, spaces: object) -> bool:
        code, out, err, calls = call(
            root,
            ["tab", "--agent", "claude", "--name", "w1", "--task", TASK],
            spaces=spaces,
            ls_fail=ls_fail,
        )
        return (
            code != 0
            and not out
            and err
            and not tab_new(calls)
            and not any(c[:2] == ["hc", "run"] for c in calls)
        )

    def not_arrived(screen: str, reason: str) -> bool:
        code, out, err, calls = tab("claude", screen=screen)
        sends = [c for c in calls if c[0] == "hc" and c[1] != "read"]
        return (
            code != 0
            and reason in err
            and "w1 (t9)" in err
            and not sends
            and out.count("\n") == 1
        )

    def odd_task() -> bool:
        code, _, _, calls = tab("codex", task=ODD)
        return code == 0 and json.loads(tab_new(calls)[0][-1]) == ["codex-hc", ODD]

    def close(tab_id: str) -> tuple[int, list[list[str]]]:
        code, _, _, calls = call(root, ["close", "--id", tab_id])
        return code, [c for c in calls if c[:3] == ["herdr-app", "do", "tab.close"]]

    def closes_own() -> bool:
        code, closed = close("tb3")
        return code == 0 and [c[-1] for c in closed] == ["tb3"]

    def refuses_other() -> bool:
        code, closed = close("tb1")
        return code != 0 and not closed

    def refuses_unknown() -> bool:
        code, closed = close("tbzzz")
        return code != 0 and not closed

    def dash_task() -> bool:
        code, _, _, calls = tab("claude", task="--help")
        return code != 0 and not tab_new(calls)

    return [
        (
            "claude tab opens in the current space, task arrived",
            lambda: opens("claude", "claude"),
        ),
        ("codex tab starts codex-hc", lambda: opens("codex", "codex-hc")),
        (
            "herdr-app ls fails: nothing opened, no hc run",
            lambda: no_space(True, SPACES),
        ),
        (
            "terminal in no space: nothing opened, no hc run",
            lambda: no_space(False, {"spaces": SPACES["spaces"][:1]}),
        ),
        (
            "task never appears: exit non-zero, reason named, nothing sent",
            lambda: not_arrived("> \n", "the start of the task text did not show"),
        ),
        (
            "trust dialog: exit non-zero, reason named, nothing sent",
            lambda: not_arrived(DIALOG, "trust dialog"),
        ),
        ("quotes, newline, non-ASCII reach tab.new unchanged", odd_task),
        ("a task starting with a dash is refused", dash_task),
        ("tab-close closes a tab of the current space", closes_own),
        ("tab-close refuses a tab of another space", refuses_other),
        ("tab-close refuses an unknown tab", refuses_unknown),
    ]


def main() -> None:
    failed = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch).resolve()
        (root / "bin").mkdir()
        for name in ("herdr-app", "hc"):
            path = root / "bin" / name
            path.write_text(STANDIN.format(python=sys.executable), encoding="utf-8")
            path.chmod(0o755)
        for name, case in cases(root):
            ok = case()
            failed += not ok
            sys.stdout.write(f"{'ok  ' if ok else 'FAIL'} {name}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
