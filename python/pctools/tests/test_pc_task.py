"""The pc:doctor file task (.mise/tasks/pc/doctor): it runs this package's doctor from python/pctools/.venv."""

import json
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
