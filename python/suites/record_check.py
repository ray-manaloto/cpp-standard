"""Check record.py offline: stand-in suites in a scratch records folder, never the real one or a CI job summary. Prints
one line per case and exits 1 when any fails.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A stand-in pytest: other output, a prefixed --durations block (as mise's prefix output shows it), then the summary.
SUITE = """
import sys
print("collected 2 items")
print("[//python/repo:test] ======== slowest 25 durations ========")
print("[//python/repo:test] 2.50s call     tests/test_a.py::test_slow")
print("[//python/repo:test] ")
print("[//python/repo:test] 0.10s setup    tests/test_a.py::test_fast")
print("[//python/repo:test] (3 durations < 0.005s hidden.  Use -vv to show these durations.)")
print("======== 2 passed in 2.70s ========")
sys.exit(int(sys.argv[1]))
"""
# A stand-in `pytest -q`: a block with no closing rule, the hidden-durations note, then the bare summary line.
QUIET = """
print("======== slowest durations ========")
print("1.25s call     tests/test_b.py::test_q")
print("(1 durations < 0.005s hidden.  Use -vv to show these durations.)")
print("2 passed in 1.30s")
"""


def record(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(HERE / "record.py"), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def suite(
    env: dict[str, str], name: str, status: int
) -> subprocess.CompletedProcess[str]:
    return record(env, "run", name, "--", sys.executable, "-c", SUITE, str(status))


def cases(env: dict[str, str], folder: Path) -> list[tuple[str, Callable[[], bool]]]:
    def kept() -> bool:
        done = suite(env, "repo", 0)
        saved = json.loads((folder / "repo.json").read_text())
        return (
            done.returncode == 0
            and "collected 2 items" in done.stdout
            and saved["suite"] == "repo"
            and saved["status"] == 0
            and saved["slowest"]
            == [
                "2.50s call     tests/test_a.py::test_slow",
                "0.10s setup    tests/test_a.py::test_fast",
            ]
            and isinstance(saved["wall_s"], float)
            and isinstance(saved["load_start"], float)
            and isinstance(saved["load_end"], float)
        )

    def quiet() -> bool:
        done = record(env, "run", "quiet", "--", sys.executable, "-c", QUIET)
        saved = json.loads((folder / "quiet.json").read_text())
        return done.returncode == 0 and saved["slowest"] == [
            "1.25s call     tests/test_b.py::test_q"
        ]

    def failing() -> bool:
        done = suite(env, "workflow", 3)
        return (
            done.returncode == 3
            and json.loads((folder / "workflow.json").read_text())["status"] == 3
        )

    def unwritable() -> bool:
        blocked = folder / "a-file"
        blocked.write_text("")
        done = suite(env | {"SUITE_TIMES_DIR": str(blocked / "below")}, "pctools", 4)
        return (
            done.returncode == 4
            and "warning: cannot write the pctools record" in done.stderr
        )

    def missing() -> bool:
        done = record(env, "run", "repo", "--", str(folder / "no-such-command"))
        return done.returncode == 127 and "no-such-command" in done.stderr

    def report() -> bool:
        (folder / "pctools.json").write_text("{not json")
        rows = [json.loads(line) for line in record(env, "report").stdout.splitlines()]
        return [row["suite"] for row in rows] == [
            "repo",
            "workflow",
            "pctools",
        ] and rows[2] == {
            "suite": "pctools",
            "record": None,
        }

    def summary() -> bool:
        text = record(env, "summary").stdout
        return (
            "| repo |" in text
            and "| pctools | no record |" in text
            and "`2.50s call     tests/test_a.py::test_slow`" in text
            and "<summary>repo: slowest tests</summary>" in text
        )

    def state_default() -> bool:
        state = folder / "state"
        plain = {k: v for k, v in env.items() if k != "SUITE_TIMES_DIR"} | {
            "XDG_STATE_HOME": str(state)
        }
        suite(plain, "repo", 0)
        home = {k: v for k, v in plain.items() if k != "XDG_STATE_HOME"} | {
            "HOME": str(folder / "home")
        }
        suite(home, "repo", 0)
        return (state / "cpp-standard" / "suite-times" / "repo.json").is_file() and (
            folder
            / "home"
            / ".local"
            / "state"
            / "cpp-standard"
            / "suite-times"
            / "repo.json"
        ).is_file()

    def usage() -> bool:
        done = record(env, "run", "repo")
        return done.returncode == 2 and "record.py run <suite>" in done.stderr

    return [
        (
            "a passing suite: output passes through, the record keeps time, load and slowest tests",
            kept,
        ),
        (
            "pytest -q: only test lines are kept, not the hidden note or the summary",
            quiet,
        ),
        ("a failing suite keeps its exit status, and the record says so", failing),
        (
            "an unwritable records folder warns, and the suite's status stands",
            unwritable,
        ),
        ("a command that is not there exits 127", missing),
        ("report lists every suite; a missing or broken record is null", report),
        ("summary renders the Markdown table and the slowest tests", summary),
        ("without SUITE_TIMES_DIR: XDG_STATE_HOME, else ~/.local/state", state_default),
        ("a malformed command line prints the usage and exits 2", usage),
    ]


def main() -> None:
    failed = 0
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch).resolve()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"GITHUB_STEP_SUMMARY", "XDG_STATE_HOME"}
        }
        env["SUITE_TIMES_DIR"] = str(folder)
        for name, case in cases(env, folder):
            ok = case()
            failed += not ok
            sys.stdout.write(f"{'ok  ' if ok else 'FAIL'} {name}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
