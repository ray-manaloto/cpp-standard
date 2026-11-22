#!/usr/bin/env python3
"""Measure idle CPU usage on the compiler host before requesting dispatch."""

import errno
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

WINDOW_SECONDS = 240
INTERVAL_SECONDS = 15
MAX_LATENESS_SECONDS = 2
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


def container_cgroup(container, pid):
    cgroup_lines = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
    (cgroup,) = [line[3:] for line in cgroup_lines if line.startswith("0::/")]
    parts = Path(cgroup).parts
    expected = f"docker-{container}.scope"
    if ".." in parts or parts.count(expected) != 1:
        raise ValueError(f"cannot identify the container root cgroup: {container}")
    return Path("/sys/fs/cgroup", *parts[1 : parts.index(expected) + 1])


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
        root = container_cgroup(container, pid)
        inode = root.stat().st_ino
        stat = (root / "cpu.stat").read_text()
        (usage,) = [
            int(line.split()[1])
            for line in stat.splitlines()
            if line.startswith("usage_usec ")
        ]
        if usage < 0:
            raise ValueError("invalid CPU counter")
        records[container] = (name, pid, started, restarts, str(root), inode, usage)
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


def daemon_invocation():
    invocation = subprocess.check_output(
        ["systemctl", "show", "docker.service", "-p", "InvocationID", "--value"],
        text=True,
        timeout=10,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{32}", invocation) or int(invocation, 16) == 0:
        raise ValueError("cannot identify the Docker daemon invocation")
    return invocation


def event_anchor():
    invocation = daemon_invocation()
    containers = docker("ps", "-q", "--no-trunc").split()
    if not containers:
        raise ValueError("no running container for the Docker event anchor")
    container = containers[0]
    # The daemon emits a top event for this read-only call. Its continued
    # presence proves that the bounded event history still reaches our start.
    since = time.time_ns()
    docker("top", container, "-eo", "pid")
    return invocation, container, since, time.time_ns()


def event_timestamp(nanoseconds):
    seconds, fraction = divmod(nanoseconds, 1_000_000_000)
    return f"{seconds}.{fraction:09d}"


def check_events(anchor, end):
    invocation, container, since, anchor_end = anchor
    if not since <= anchor_end <= end:
        raise ValueError("Docker event window clock moved backwards")
    raw = docker(
        "events",
        "--since",
        event_timestamp(since),
        "--until",
        event_timestamp(end),
        "--format",
        "{{json .}}",
    )
    if daemon_invocation() != invocation:
        raise ValueError("Docker daemon restarted during sampling")
    anchor_seen = False
    for line in raw.splitlines():
        event = json.loads(line)
        if event["Type"] != "container":
            continue
        action = event["Action"]
        if (
            action == "top"
            and event["Actor"]["ID"] == container
            and since <= event["timeNano"] <= anchor_end
        ):
            anchor_seen = True
        if action in {
            "create",
            "destroy",
            "die",
            "kill",
            "oom",
            "pause",
            "rename",
            "restart",
            "start",
            "stop",
            "unpause",
            "update",
        }:
            raise ValueError(f"container lifecycle event during sampling: {action}")
    if not anchor_seen:
        raise ValueError("Docker event history lost the start anchor")
    return len(raw.splitlines())


@contextmanager
def stable_wall_clock():
    if not hasattr(os, "timerfd_create"):
        raise ValueError("Linux timerfd is required to verify the Docker event clock")
    fd = os.timerfd_create(time.CLOCK_REALTIME, flags=os.TFD_NONBLOCK)
    try:
        # An armed absolute realtime timer records a discontinuous change even
        # if the wall clock steps back and recovers between two samples.
        os.timerfd_settime_ns(
            fd,
            flags=os.TFD_TIMER_ABSTIME | os.TFD_TIMER_CANCEL_ON_SET,
            initial=time.time_ns() + 2 * WINDOW_SECONDS * 1_000_000_000,
        )
        yield
        try:
            os.read(fd, 8)
        except BlockingIOError:
            pass
        except OSError as exc:
            if exc.errno == errno.ECANCELED:
                raise ValueError(
                    "wall clock stepped during Docker event sampling"
                ) from exc
            raise
        else:
            raise ValueError("Docker event clock guard expired")
    finally:
        os.close(fd)


def collect_samples(report):
    anchor = event_anchor()
    initial = snapshot()
    report["containers"] = {key: value[:-1] for key, value in initial.items()}
    report["samples"].append(
        {"acquired_at": utc_now(), "cpu_us": {key: 0 for key in initial}}
    )
    began = time.monotonic()
    previous = initial
    for offset in range(INTERVAL_SECONDS, WINDOW_SECONDS + 1, INTERVAL_SECONDS):
        deadline = began + offset
        time.sleep(max(0, deadline - time.monotonic()))
        current = snapshot()
        if time.monotonic() > deadline + MAX_LATENESS_SECONDS:
            raise ValueError(f"missed CPU sample deadline at +{offset}s")
        deltas(previous, current)
        report["samples"].append(
            {"acquired_at": utc_now(), "cpu_us": deltas(initial, current)}
        )
        previous = current
    report["docker_event_count"] = check_events(anchor, time.time_ns())


def main():
    report = {
        "started_at": utc_now(),
        "window_seconds": WINDOW_SECONDS,
        "budget_us": BUDGET_US,
        "samples": [],
    }
    try:
        with stable_wall_clock():
            collect_samples(report)
        report["total_cpu_us"] = sum(report["samples"][-1]["cpu_us"].values())
        report["ready"] = report["total_cpu_us"] <= BUDGET_US
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        report.update(ready=False, error=str(exc))
    report["finished_at"] = utc_now()
    print(json.dumps(report, indent=2))
    return int(not report["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
