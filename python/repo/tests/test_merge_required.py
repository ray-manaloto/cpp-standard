"""repotools pr-merge under required-checks waits only on the required checks, read from the branch rules (#293).

The others are listed with their state, never waited on and never a failure. A required list that cannot be read
refuses the merge. local-hk still waits on every check, as before.
"""

import json
from pathlib import Path

import pytest

from repotools.cli import main

from .test_merge import RUNS, World, merge_args, world
from .test_merge_gate import REQUIRED, setting
from .test_pr_create import pr_refusal_of, repo

__all__ = ["repo", "world"]  # the fixture, used by name
RULES_CALL = ["api", "repos/{owner}/{repo}/rules/branches/trunk"]


@pytest.fixture
def queued(world: World, repo: Path) -> World:
    setting(world, repo, REQUIRED, pushed=True)
    return world


def runs_call(world: World) -> list[str]:
    return [
        "api",
        f"repos/{{owner}}/{{repo}}/commits/{world.head}/check-runs",
        "--method",
        "GET",
        "-F",
        "per_page=100",
    ]


def wait_call(world: World) -> list[str]:
    return next(call for call in world.calls() if call[:3] == ["jouet", "wait", "ci"])


def test_the_wait_names_the_required_checks_and_nothing_else(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    main(["pr-merge", *merge_args()])
    capsys.readouterr()
    # The exact arguments: the required contexts, sorted, one --check each; no --all, no --required.
    call = wait_call(queued)
    assert call[3:6] == ["7", "--sha", queued.head]
    assert call[6] == "--timeout"  # its value is what is left of the time limit
    assert call[8:] == ["--check", "gate", "--check", "lint"]
    assert RULES_CALL in queued.calls()
    assert runs_call(queued) in queued.calls()


def test_a_pending_check_that_is_not_required_does_not_stop_the_merge_and_is_listed(
    queued: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ticket's Repowise case: queued, never required, and the merge call is still made."""
    main(["pr-merge", *merge_args()])
    done = capsys.readouterr()
    assert queued.merged()
    assert json.loads(done.out)["other_checks"] == {"Repowise review": "queued"}
    assert "not required, not waited on: Repowise review: queued\n" in done.err


def test_a_failing_check_that_is_not_required_is_no_failure(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    queued.set(check_runs=[*RUNS, {"name": "CodeRabbit", "status": "completed", "conclusion": "failure"}])
    main(["pr-merge", *merge_args()])
    assert json.loads(capsys.readouterr().out)["other_checks"]["CodeRabbit"] == "failure"
    assert queued.merged()


def test_no_other_checks_is_said_and_reported_as_empty(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    queued.set(check_runs=RUNS[:2])
    main(["pr-merge", *merge_args()])
    done = capsys.readouterr()
    assert json.loads(done.out)["other_checks"] == {}
    assert "no checks on the head besides the required ones\n" in done.err


def test_a_failing_required_check_fails_at_once_and_is_named(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    queued.set(
        checks=1,
        checks_said="lint failed",
        check_runs=[{"name": "lint", "status": "completed", "conclusion": "failure"}, RUNS[1]],
    )
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    failed = "did not pass (jouet wait ci exit 1); required checks not passing: lint (failure): lint failed"
    assert said == f"the checks of pull request #7 on {queued.head} {failed}"
    assert not queued.merged()


def test_a_required_check_pending_at_the_time_limit_is_named(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    queued.set(
        checks=124, checks_said="", check_runs=[RUNS[0], {"name": "gate", "status": "in_progress", "conclusion": None}]
    )
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    limit = "within the 3600.0s time limit (jouet wait ci exit 124); required checks not passing: gate (in_progress)"
    assert said == f"the checks of pull request #7 on {queued.head} did not pass {limit}"
    assert not queued.merged()


def test_a_required_check_not_reported_yet_is_named_as_such(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    queued.set(checks=124, checks_said="", check_runs=[RUNS[0]])
    assert "required checks not passing: gate (not reported)" in pr_refusal_of(capsys, "pr-merge", merge_args())


def test_a_failure_whose_states_cannot_be_read_still_gives_jouets_message(
    queued: World, capsys: pytest.CaptureFixture[str]
) -> None:
    queued.set(checks=1, checks_said="lint failed", check_runs="not a list")
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    failed = (
        "did not pass (jouet wait ci exit 1); required checks not passing: gate (not reported), lint (not reported)"
    )
    assert said == f"the checks of pull request #7 on {queued.head} {failed}: lint failed"


@pytest.mark.parametrize(
    "rules",
    ["unreadable", "not json", [{"type": "required_status_checks"}], {"type": "x"}],
    ids=["gh-fails", "not-json", "no-parameters", "not-a-list"],
)
def test_an_unreadable_required_list_refuses_the_merge(
    queued: World, capsys: pytest.CaptureFixture[str], rules: object
) -> None:
    queued.set(rules=rules)
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert said.startswith("cannot read the required checks of trunk from its branch rules (")
    assert said.endswith("; refusing to merge")
    assert not queued.merged()
    assert not [call for call in queued.calls() if call[:2] == ["jouet", "wait"]]  # no fall back to every check


def test_branch_rules_with_no_required_checks_refuse_the_merge(
    queued: World, capsys: pytest.CaptureFixture[str]
) -> None:
    queued.set(rules=[{"type": "deletion"}])
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert said == "the branch rules of trunk name no required checks; refusing to wait on every check instead"
    assert not queued.merged()


def test_local_hk_still_waits_on_every_check_and_reads_neither_rules_nor_check_runs(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["pr-merge", *merge_args()])
    done = capsys.readouterr()
    call = wait_call(world)
    assert call[3:7] == ["7", "--sha", world.head, "--timeout"]
    assert len(call) == 8  # no --check: every check is waited on
    assert RULES_CALL not in world.calls()
    assert runs_call(world) not in world.calls()
    assert "other_checks" not in json.loads(done.out)
