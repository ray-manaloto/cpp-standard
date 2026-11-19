"""repotools pr-merge's wait after the merge call: passing checks, then reads until merged, dropped or out of time."""

import itertools
import json

import pytest

from repotools.cli import main

from .test_merge import CLOSED, MERGED, QUEUED, WAITING, World, merge_args, world
from .test_pr_create import pr_refusal_of, repo

__all__ = ["repo", "world"]  # the fixtures, used by name
FAST = ["--interval", "0.2", "--time-limit", "30"]


def wait_args(*extra: str) -> list[str]:
    return [*merge_args(), *FAST, *extra]


def test_a_queued_pull_request_is_read_until_it_merges(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(reads=[WAITING, QUEUED, QUEUED, MERGED])
    main(["pr-merge", *wait_args()])
    assert json.loads(capsys.readouterr().out)["merge_commit"] == "f00d"
    assert len(world.reads()) == 4


def test_passing_checks_on_a_pull_request_not_yet_merged_keep_the_wait_going(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """The checks pass at once, but GitHub has neither queued nor merged it for three reads: not a result."""
    world.set(reads=[WAITING, WAITING, WAITING, MERGED])
    main(["pr-merge", *wait_args()])
    assert json.loads(capsys.readouterr().out)["number"] == 7
    assert len(world.reads()) == 4


def test_a_pull_request_dropped_from_the_queue_is_a_failure(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(reads=[QUEUED, QUEUED, WAITING])
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    assert said == "pull request #7 was dropped from the merge queue: no queue entry and not merged"
    assert len(world.reads()) == 4  # two reads in a row with no entry


def test_one_read_between_the_queue_entry_leaving_and_the_merge_is_not_a_drop(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(reads=[QUEUED, WAITING, MERGED])
    main(["pr-merge", *wait_args()])
    assert json.loads(capsys.readouterr().out)["merge_commit"] == "f00d"


def test_a_pull_request_closed_unmerged_is_a_failure(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(reads=[QUEUED, CLOSED])
    assert pr_refusal_of(capsys, "pr-merge", wait_args()) == "pull request #7 was closed without being merged"


def test_reads_are_spaced_by_the_interval(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(reads=[QUEUED, QUEUED, QUEUED, QUEUED, MERGED])
    main(["pr-merge", *merge_args(), "--interval", "0.3", "--time-limit", "30"])
    capsys.readouterr()
    times = world.reads()
    assert len(times) == 5
    assert all(later - earlier >= 0.3 for earlier, later in itertools.pairwise(times))


@pytest.mark.parametrize(
    ("last", "state"),
    [(QUEUED, "still queued at position 2"), (WAITING, "open, neither queued nor merged")],
    ids=["queued", "not-queued"],
)
def test_the_time_limit_ends_the_wait_naming_the_last_state_read(
    world: World, capsys: pytest.CaptureFixture[str], last: dict[str, object], state: str
) -> None:
    world.set(reads=[last])
    said = pr_refusal_of(capsys, "pr-merge", [*merge_args(), "--interval", "0.2", "--time-limit", "1"])
    assert said == f"pull request #7 did not merge within the 1.0s time limit; last read: {state}"
    times = world.reads()
    assert 4 <= len(times) <= 7  # about one read per interval in the limit, the last at the limit, not a burst
    assert 0.6 <= times[-1] - times[0] < 1.5


def test_an_unknown_pull_request_number_ends_the_wait_with_an_error(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(reads=["unknown"])
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    assert said == "gh failed: gh: Could not resolve to a PullRequest with the number of 7.\n"
    assert len(world.reads()) == 1


def test_failing_checks_stop_before_the_merge(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(checks=1, checks_said="build failed: step test")
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    assert (
        said
        == f"the checks of pull request #7 on {world.head} did not pass (jouet wait ci exit 1): build failed: step test"
    )
    assert not world.merged()
    assert world.reads() == []


def test_checks_still_running_at_the_time_limit_are_named_as_such(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.set(checks=124, checks_said="")
    said = pr_refusal_of(capsys, "pr-merge", wait_args())
    limit = "within the 30.0s time limit (jouet wait ci exit 124)"
    assert said == f"the checks of pull request #7 on {world.head} did not pass {limit}"
    assert not world.merged()


def test_the_checks_wait_is_bounded_by_the_time_limit(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    main(["pr-merge", *merge_args(), "--time-limit", "90"])
    capsys.readouterr()
    (checks,) = [call for call in world.calls() if call[:3] == ["jouet", "wait", "ci"]]
    timeout = checks[checks.index("--timeout") + 1]
    assert timeout.endswith("s")
    assert 0 < int(timeout.removesuffix("s")) <= 90


def test_no_event_listen_is_ever_called(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.set(reads=[QUEUED, MERGED])
    main(["pr-merge", *wait_args()])
    capsys.readouterr()
    assert not [call for call in world.calls() if "event" in call]
