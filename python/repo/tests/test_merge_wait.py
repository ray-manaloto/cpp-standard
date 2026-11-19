"""repotools pr-merge's wait after the merge call: passing checks, then reads until merged, dropped or out of time.

The wait's clock is a fake one in most tests: it advances only when the wait sleeps, so the number of reads and the
pauses between them are exact on any machine. One test runs on the real clock with a short interval.
"""

import json
from pathlib import Path

import pytest

from repotools import merge
from repotools.cli import main

from .test_merge import CLOSED, HK_RAN, MERGED, QUEUED, WAITING, World, merge_args
from .test_merge_gate import REQUIRED, setting
from .test_pr_create import pr_refusal_of, repo

__all__ = ["repo"]  # the fixture, used by name
FAST = ["--interval", "2", "--time-limit", "30"]


class FakeClock(merge.Clock):
    """Time that stands still between sleeps; each sleep is recorded and moves it on by exactly that much."""

    def __init__(self) -> None:
        self.time = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.time += seconds


@pytest.fixture(params=["local-hk", "required-checks"])
def world(request: pytest.FixtureRequest, repo: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """Every test here runs under both gates: the wait after the merge call is the same (#158), whether the call
    merges at once or queues the pull request."""
    scene = World(repo, monkeypatch, HK_RAN)
    if request.param == "required-checks":
        setting(scene, repo, REQUIRED, pushed=True)
    return scene


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(merge, "CLOCK", fake)
    return fake


def wait_args(*extra: str) -> list[str]:
    return [*merge_args(), *FAST, *extra]


def test_a_queued_pull_request_is_read_until_it_merges(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(reads=[WAITING, QUEUED, QUEUED, MERGED])
    main(["pr-merge", *wait_args()])
    assert json.loads(capsys.readouterr().out)["merge_commit"] == "f00d"
    assert len(world.reads()) == 4
    assert clock.slept == [2, 2, 2]


def test_passing_checks_on_a_pull_request_not_yet_merged_keep_the_wait_going(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    """The checks pass at once, but GitHub has neither queued nor merged it for three reads: not a result."""
    world.set(reads=[WAITING, WAITING, WAITING, MERGED])
    main(["pr-merge", *wait_args()])
    assert json.loads(capsys.readouterr().out)["number"] == 7
    assert len(world.reads()) == 4
    assert clock.slept == [2, 2, 2]


def test_a_pull_request_dropped_from_the_queue_is_a_failure(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(reads=[QUEUED, QUEUED, WAITING])
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    assert said == "pull request #7 was dropped from the merge queue: no queue entry and not merged"
    assert len(world.reads()) == 4  # two reads in a row with no entry
    assert clock.slept == [2, 2, 2]


def test_one_read_between_the_queue_entry_leaving_and_the_merge_is_not_a_drop(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """On the real clock, with a short interval and a long limit: the wait really sleeps between reads."""
    world.set(reads=[QUEUED, WAITING, MERGED])
    main(["pr-merge", *merge_args(), "--interval", "0.05", "--time-limit", "600"])
    assert json.loads(capsys.readouterr().out)["merge_commit"] == "f00d"
    assert len(world.reads()) == 3


def test_a_pull_request_closed_unmerged_is_a_failure(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(reads=[QUEUED, CLOSED])
    assert pr_refusal_of(capsys, "pr-merge", wait_args()) == "pull request #7 was closed without being merged"
    assert clock.slept == [2]


def test_reads_are_spaced_by_the_interval(world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]) -> None:
    """One pause of the whole interval between each two reads, and none after the last: no burst of reads."""
    world.set(reads=[QUEUED, QUEUED, QUEUED, QUEUED, MERGED])
    main(["pr-merge", *merge_args(), "--interval", "3", "--time-limit", "30"])
    capsys.readouterr()
    assert len(world.reads()) == 5
    assert clock.slept == [3, 3, 3, 3]


@pytest.mark.parametrize(
    ("last", "state"),
    [(QUEUED, "still queued at position 2"), (WAITING, "open, neither queued nor merged")],
    ids=["queued", "not-queued"],
)
def test_the_time_limit_ends_the_wait_naming_the_last_state_read(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str], last: dict[str, object], state: str
) -> None:
    """A limit of 10s and an interval of 3s: reads at 0, 3, 6 and 9s, and a last one at the limit after 1s."""
    world.set(reads=[last])
    said = pr_refusal_of(capsys, "pr-merge", [*merge_args(), "--interval", "3", "--time-limit", "10"])
    assert said == f"pull request #7 did not merge within the 10.0s time limit; last read: {state}"
    assert len(world.reads()) == 5
    assert clock.slept == [3, 3, 3, 1]


def test_an_unknown_pull_request_number_ends_the_wait_with_an_error(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(reads=["unknown"])
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    assert said == "gh failed: gh: Could not resolve to a PullRequest with the number of 7.\n"
    assert len(world.reads()) == 1
    assert clock.slept == []


def test_failing_checks_stop_before_the_merge(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(checks=1, checks_said="build failed: step test")
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    failed = "did not pass (jouet wait ci exit 1): build failed: step test"
    assert said == f"the checks of pull request #7 on {world.head} {failed}"
    assert not world.merged()
    assert world.reads() == []
    assert clock.slept == []


def test_checks_still_running_at_the_time_limit_are_named_as_such(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(checks=124, checks_said="")
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    limit = "within the 30.0s time limit (jouet wait ci exit 124)"
    assert said == f"the checks of pull request #7 on {world.head} did not pass {limit}"
    assert not world.merged()
    assert clock.slept == []


def test_the_checks_wait_is_bounded_by_the_time_limit(
    world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["pr-merge", *merge_args(), "--time-limit", "90"])
    capsys.readouterr()
    (checks,) = [call for call in world.calls() if call[:3] == ["jouet", "wait", "ci"]]
    assert checks[checks.index("--timeout") + 1] == "90s"
    assert clock.slept == []


def test_no_event_listen_is_ever_called(world: World, clock: FakeClock, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(reads=[QUEUED, MERGED])
    main(["pr-merge", *wait_args()])
    capsys.readouterr()
    assert not [call for call in world.calls() if "event" in call]
    assert clock.slept == [2]
