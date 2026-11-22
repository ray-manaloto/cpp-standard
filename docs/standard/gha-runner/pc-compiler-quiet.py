#!/usr/bin/env python3
"""Measure idle CPU usage on the compiler host before requesting dispatch."""

import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

WINDOW_SECONDS = 240
INTERVAL_SECONDS = 15
BUDGET_US = 800_000


def utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def docker(*args):
    env = dict(os.environ)
    env.pop("DOCKER_CONTEXT", None)
    return subprocess.check_output(
        ["docker", "--host", "unix:///var/run/docker.sock", *args],
        env=env,
        text=True,
        timeout=10,
    )


def snapshot():
    ids = docker("ps", "-q", "--no-trunc").split()
    if (
        not ids
        or len(ids) != len(set(ids))
        or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in ids)
    ):
        raise ValueError("missing or invalid running container inventory")

    records = {}
    template = "{{.Id}} {{.Name}} {{.State.Pid}} {{.State.StartedAt}} {{.RestartCount}}"
    for line in docker("inspect", "--format", template, *ids).splitlines():
        container, name, pid, started, restarts = line.split()
        if not pid.isdecimal() or int(pid) <= 0 or container in records:
            raise ValueError("invalid running container identity")
        if name.startswith("/cpp-compiler-"):
            raise ValueError("compiler workload already active")
        cgroup_lines = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
        (cgroup,) = [line[3:] for line in cgroup_lines if line.startswith("0::/")]
        path = Path(cgroup)
        if path == Path("/") or ".." in path.parts:
            raise ValueError("invalid container cgroup")
        stat = (Path("/sys/fs/cgroup") / path.relative_to("/") / "cpu.stat").read_text()
        (usage,) = [
            int(line.split()[1])
            for line in stat.splitlines()
            if line.startswith("usage_usec ")
        ]
        if usage < 0:
            raise ValueError("invalid CPU counter")
        records[container] = (name, pid, started, restarts, cgroup, usage)
    if records.keys() != set(ids):
        raise ValueError("container inventory changed during snapshot")
    return records


def deltas(before, after):
    if before.keys() != after.keys():
        raise ValueError("running container inventory changed")
    result = {}
    for container, previous in before.items():
        current = after[container]
        if previous[:-1] != current[:-1]:
            raise ValueError(f"container identity changed: {current[0]}")
        used = current[-1] - previous[-1]
        if used < 0:
            raise ValueError(f"CPU counter went backwards: {current[0]}")
        result[container] = used
    return result


def main():
    report = {
        "started_at": utc_now(),
        "window_seconds": WINDOW_SECONDS,
        "budget_us": BUDGET_US,
        "samples": [],
    }
    try:
        initial = snapshot()
        report["containers"] = {key: value[:-1] for key, value in initial.items()}
        report["samples"].append(
            {"acquired_at": utc_now(), "cpu_us": {key: 0 for key in initial}}
        )
        began = time.monotonic()
        previous = initial
        for offset in range(INTERVAL_SECONDS, WINDOW_SECONDS + 1, INTERVAL_SECONDS):
            time.sleep(max(0, began + offset - time.monotonic()))
            current = snapshot()
            deltas(previous, current)
            report["samples"].append(
                {"acquired_at": utc_now(), "cpu_us": deltas(initial, current)}
            )
            previous = current
        report["total_cpu_us"] = sum(report["samples"][-1]["cpu_us"].values())
        report["ready"] = report["total_cpu_us"] <= BUDGET_US
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report.update(ready=False, error=str(exc))
    report["finished_at"] = utc_now()
    print(json.dumps(report, indent=2))
    return int(not report["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
