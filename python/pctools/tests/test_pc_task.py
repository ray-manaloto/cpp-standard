"""The pc:doctor file task (.mise/tasks/pc/doctor): it runs this package's doctor from python/pctools/.venv."""

import json
import shutil
import subprocess
from pathlib import Path

from .test_pc_doctor import HEALTHY, answer

TASK = Path(__file__).resolve().parents[3] / ".mise/tasks/pc/doctor"


def run(*argv: str, task: Path = TASK) -> subprocess.CompletedProcess[str]:
    # The ssh fixture's PATH and STAND_IN reach the task through the environment, as mise passes them.
    return subprocess.run((str(task), *argv), capture_output=True, text=True, check=False)


def test_the_task_runs_the_doctor(ssh: Path) -> None:
    answer(ssh, {})
    done = run()
    assert done.returncode == 0, done.stderr
    checks = [json.loads(line)["check"] for line in done.stdout.splitlines()]
    assert checks == [
        "bootstrap-status",
        "bootstrap-plan",
        "pending-updates",
        "gpu-cdi",
        "kernel-settings",
        "privileged-containers",
        "fence-drops",
    ]
    called = set((ssh / "calls.jsonl").read_text().splitlines())
    assert called == set(HEALTHY)


def test_the_task_takes_no_arguments(ssh: Path) -> None:
    done = run("--fix")
    assert (done.returncode, done.stdout) == (2, "")
    assert json.loads(done.stderr) == {"error": "pc:doctor: takes no arguments"}
    assert not (ssh / "calls.jsonl").exists()


def test_without_the_environment_the_task_says_how_to_make_it(ssh: Path, tmp_path: Path) -> None:
    # The same task file in a checkout whose python/pctools has no .venv.
    task = tmp_path / "checkout/.mise/tasks/pc/doctor"
    task.parent.mkdir(parents=True)
    shutil.copy2(TASK, task)
    done = run(task=task)
    assert done.returncode == 2
    assert "run: mise run pctools:sync" in json.loads(done.stderr)["error"]
    assert not (ssh / "calls.jsonl").exists()
