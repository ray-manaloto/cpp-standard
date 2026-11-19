"""Check testtab.py and testguard.py against #178's and #251's acceptance lines, offline: a scratch trust record,
stand-in herdr-app and hc executables on PATH, and scratch git checkouts. It never reads the real ~/.claude.json,
opens a tab or starts Claude Code. Prints one line per case and exits 1 when any fails.
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
with open(os.environ["STANDIN_LOG"], "a") as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")
if os.path.basename(sys.argv[0]) == "herdr-app":
    print(json.dumps({{"space": "sp1", "tab": "tb1", "terminal": "t1"}}))
else:
    print(open(os.environ["STANDIN_SCREEN"]).read())
"""
SCREENS = {
    "ready": "Welcome back\n> \n  ? for shortcuts\n",
    "dialog": "Do you trust the files in this folder?\n> 1. Yes, I trust this folder\n  2. No, exit\n",
    "blank": "\n",
}


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def setup(root: Path) -> dict[str, Path]:
    """Scratch checkouts, a trust record that trusts one of them, and the stand-ins."""
    folders = {name: root / name for name in ("trusted", "untrusted", "plain")}
    for name in ("trusted", "untrusted"):
        git("init", "-q", str(folders[name]))
        git(
            "-C",
            str(folders[name]),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        )
    folders["plain"].mkdir()
    folders["worktree"] = root / "trusted-wt"
    git(
        "-C",
        str(folders["trusted"]),
        "worktree",
        "add",
        "-q",
        "-b",
        "wt",
        str(folders["worktree"]),
    )
    config = root / "config"
    config.mkdir()
    record = {
        "projects": {
            str(folders["trusted"].resolve()): {"hasTrustDialogAccepted": True},
            str(folders["untrusted"].resolve()): {"hasTrustDialogAccepted": False},
        }
    }
    (config / ".claude.json").write_text(json.dumps(record), encoding="utf-8")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for name in ("herdr-app", "hc"):
        path = bin_dir / name
        path.write_text(STANDIN.format(python=sys.executable), encoding="utf-8")
        path.chmod(0o755)
    return folders | {"config": config, "bin": bin_dir, "root": root}


def launch(
    env: dict[str, str],
    folder: Path,
    run: Path,
    screen: str,
    wait: str = "3",
    extra: tuple[str, ...] = (),
) -> tuple[int, str, list]:
    """Run testtab.py once and return its exit code, stderr and the stand-in calls it made."""
    log = run / "standin.jsonl"
    screen_file = run / "screen.txt"
    run.mkdir(parents=True)
    screen_file.write_text(SCREENS[screen], encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "testtab.py"),
            "--space",
            "sp1",
            "--run",
            str(run),
            "--folder",
            str(folder),
            "--name",
            "probe",
            "--names",
            "probe",
            "--tools",
            "Read",
            "--wait",
            wait,
            *extra,
        ],
        env=env | {"STANDIN_LOG": str(log), "STANDIN_SCREEN": str(screen_file)},
        capture_output=True,
        text=True,
        check=False,
    )
    calls = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    return done.returncode, done.stderr, calls


def guard(payload: dict) -> str:
    """Run testguard.py on one payload and return what it printed (empty when it allows)."""
    with tempfile.TemporaryDirectory() as scratch:
        done = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "testguard.py"),
                str(Path(scratch) / "log.jsonl"),
                "--tools",
                "Read",
                "probe",
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        )
    return done.stdout


def guard_run(
    payload: object, log: Path, tools: str = "Read", monitor: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run testguard.py on one stdin text and a log path; never raises on a non-zero exit."""
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "testguard.py"),
            str(log),
            "--tools",
            tools,
            *(["--allow-monitor", monitor] if monitor is not None else []),
            "probe",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def denies_cleanly(done: subprocess.CompletedProcess[str]) -> bool:
    """Exit 0 and a deny on stdout: what Claude Code reads as a decision, not as a hook failure."""
    return done.returncode == 0 and '"permissionDecision": "deny"' in done.stdout


def cases(
    s: dict[str, Path], env: dict[str, str]
) -> list[tuple[str, Callable[[], bool]]]:
    runs = s["root"] / "runs"

    def refused(name: str, folder: Path) -> bool:
        code, err, calls = launch(env, folder, runs / name, "ready")
        return code == 3 and "no tab opened" in err and not calls

    def opened(name: str, folder: Path) -> bool:
        code, _, calls = launch(env, folder, runs / name, "ready")
        return code == 0 and [c[:3] for c in calls if c[0] == "herdr-app"] == [
            ["herdr-app", "do", "tab.new"]
        ]

    def handoff(name: str, screen: str) -> bool:
        code, err, calls = launch(env, s["trusted"], runs / name, screen, wait="1")
        sends = [c for c in calls if c[0] == "hc" and c[1] != "read"]
        return code == 4 and "handing probe (t1) to the owner" in err and not sends

    def guard_hook_blocks() -> bool:
        code, _, _calls = launch(env, s["trusted"], runs / "settings", "ready")
        path = runs / "settings" / "settings-probe.json"
        if code != 0 or not path.exists():
            return False
        pre = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        hooks = [h for e in pre for h in e["hooks"] if "testguard.py" in h["command"]]
        return len(hooks) == 1 and hooks[0].get("onFailure") == "block"

    def log_unwritable_denies() -> bool:
        gone = s["root"] / "gone" / "log.jsonl"
        done = guard_run({"tool_name": "Read", "tool_input": {}}, gone)
        return denies_cleanly(done) and "log could not be written" in done.stdout

    def odd_payload_denies() -> bool:
        return denies_cleanly(guard_run([], s["root"] / "odd.jsonl"))

    def plugin_dir_passed() -> bool:
        mod = s["root"] / "probe-mod"
        mod.mkdir(exist_ok=True)
        code, _, calls = launch(
            env,
            s["trusted"],
            runs / "plugin-dir",
            "ready",
            extra=("--plugin-dir", str(mod)),
        )
        new = [c for c in calls if c[:3] == ["herdr-app", "do", "tab.new"]]
        argv = json.loads(new[0][new[0].index("--argv") + 1]) if new else []
        at = argv.index("--plugin-dir") if "--plugin-dir" in argv else -1
        return code == 0 and at > 0 and argv[at + 1] == str(mod.resolve())

    def allow_monitor_exact_only() -> bool:
        cmd = "tail -f /run/watch.log"
        log = s["root"] / "monitor.jsonl"

        def call(tool: str, tool_input: dict) -> subprocess.CompletedProcess[str]:
            payload = {"tool_name": tool, "tool_input": tool_input}
            return guard_run(payload, log, monitor=cmd)

        exact = call("Monitor", {"command": cmd, "description": "w", "timeout_ms": 1})
        other = call("Monitor", {"command": cmd + "; id", "description": "w"})
        socket = call("Monitor", {"command": cmd, "ws": {"url": "ws://x"}})
        shell = call("Bash", {"command": cmd})
        unset = guard_run({"tool_name": "Monitor", "tool_input": {"command": cmd}}, log)
        return (
            exact.returncode == 0
            and exact.stdout == ""
            and all(denies_cleanly(d) for d in (other, socket, shell, unset))
        )

    def allow_monitor_in_settings() -> bool:
        code, _, _calls = launch(
            env,
            s["trusted"],
            runs / "allow-monitor",
            "ready",
            extra=("--allow-monitor", "tail -f /run/watch.log"),
        )
        path = runs / "allow-monitor" / "settings-probe.json"
        if code != 0 or not path.exists():
            return False
        text = path.read_text(encoding="utf-8")
        return "--allow-monitor 'tail -f /run/watch.log'" in text

    def skill_says_blocked() -> bool:
        text = (HERE.parents[1] / ".agents/skills/run-testtab/SKILL.md").read_text(
            encoding="utf-8"
        )
        return "onFailure" in text and "stops every tool call" in text

    return [
        (
            "untrusted folder refused, no tab",
            lambda: refused("untrusted", s["untrusted"]),
        ),
        ("folder outside git refused, no tab", lambda: refused("plain", s["plain"])),
        ("trusted folder opens a tab", lambda: opened("trusted", s["trusted"])),
        (
            "worktree of a trusted checkout opens a tab",
            lambda: opened("worktree", s["worktree"]),
        ),
        (
            "trust dialog after launch: handoff, nothing sent",
            lambda: handoff("dialog", "dialog"),
        ),
        ("no ready prompt: handoff, nothing sent", lambda: handoff("blank", "blank")),
        (
            "guard denies an unlisted tool",
            lambda: "deny" in guard({"tool_name": "Bash", "tool_input": {}}),
        ),
        (
            "guard allows a listed tool",
            lambda: guard({"tool_name": "Read", "tool_input": {}}) == "",
        ),
        ("guard hook in the settings file has onFailure block", guard_hook_blocks),
        ("--plugin-dir reaches the claude argv", plugin_dir_passed),
        (
            "--allow-monitor: only the exact Monitor command passes; Bash stays denied",
            allow_monitor_exact_only,
        ),
        ("--allow-monitor reaches the guard command", allow_monitor_in_settings),
        ("run-testtab skill says a broken guard stops every call", skill_says_blocked),
        ("guard denies, exit 0, when its log cannot be written", log_unwritable_denies),
        (
            "guard denies, exit 0, on a payload that is not an object",
            odd_payload_denies,
        ),
    ]


def main() -> None:
    failed = 0
    with tempfile.TemporaryDirectory() as scratch:
        s = setup(Path(scratch).resolve())
        env = {k: v for k, v in os.environ.items() if k != "HOME"}
        env |= {
            "PATH": f"{s['bin']}{os.pathsep}{os.environ['PATH']}",
            "CLAUDE_CONFIG_DIR": str(s["config"]),
            "HOME": str(s["root"]),
        }
        for name, case in cases(s, env):
            ok = case()
            failed += not ok
            sys.stdout.write(f"{'ok  ' if ok else 'FAIL'} {name}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
