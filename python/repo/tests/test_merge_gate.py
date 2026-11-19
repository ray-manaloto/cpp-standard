"""repotools pr-merge's merge gate setting: repotools.toml's [pr-merge] gate, read from origin's default branch.

`local-hk` (the default, and what a missing file or table means) is today's gate: hk check --pr, then the merge.
`required-checks` runs every gate but hk, runs no hk, and puts the pull request in the merge queue, whose required
checks are then the gate (#213).
"""

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from repotools.cli import main

from .test_gates import REPO
from .test_merge import PR_REFUSALS, World, merge_args, world
from .test_pr_create import commit, pr_refusal_of, repo

__all__ = ["repo", "world"]  # the fixtures, used by name
REQUIRED = '[pr-merge]\ngate = "required-checks"\n'
LOCAL = '[pr-merge]\ngate = "local-hk"\n'
GATES = ["clean", "head", "open", "base", "pr-head", "title", "body", "hk"]


def setting(world: World, repo: Path, text: str, *, pushed: bool) -> None:
    """repotools.toml holding text, committed; pushed puts it on origin's trunk, else only in the branch's checkout.
    The pull request's head follows the new commit."""
    (repo / "repotools.toml").write_text(text)
    commit()
    if pushed:
        subprocess.run(["git", "push", "-q", "origin", "HEAD:trunk"], check=True)
    world.head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, check=True, text=True).stdout.strip()
    world.set(pr=world.pr())


@pytest.fixture
def queued(world: World, repo: Path) -> World:
    setting(world, repo, REQUIRED, pushed=True)
    return world


def queue_form(world: World) -> list[str]:
    return ["pr", "merge", "7", "--match-head-commit", world.head]


def test_required_checks_runs_no_hk_and_queues_in_the_queue_form(
    queued: World, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    main(["pr-merge", *merge_args()])
    assert json.loads(capsys.readouterr().out) == {"number": 7, "head_commit": queued.head, "merged": False}
    assert not queued.ran.exists()
    calls = queued.calls()
    merges = [call for call in calls if call[:2] == ["pr", "merge"]]
    # The exact argument list: no --merge (the ruleset allows only the queue's squash), no --author-email (the
    # queue's squash takes the pull request's author), no --auto.
    assert merges == [queue_form(queued)]
    assert not any(call[0] == "jouet" for call in calls)  # the queue runs the required checks, not this command
    assert not any(call[:2] == ["api", "graphql"] for call in calls)  # queued, not waited for


def test_required_checks_still_refuses_a_dirty_checkout(
    queued: World, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "notes.md").write_text("untracked\n")
    assert "untracked files" in pr_refusal_of(capsys, "pr-merge", merge_args())
    assert queued.calls() == []


@pytest.mark.parametrize(("change", "said"), PR_REFUSALS)
def test_required_checks_still_runs_every_gate_but_hk(
    queued: World, capsys: pytest.CaptureFixture[str], change: dict[str, str], said: str
) -> None:
    queued.set(pr=queued.pr() | change)
    assert said in pr_refusal_of(capsys, "pr-merge", merge_args())
    assert not queued.ran.exists()
    assert not queued.merged()


def test_a_branch_switching_its_own_gate_off_still_gets_hk(world: World, repo: Path) -> None:
    """origin's trunk has no setting; the branch under merge sets required-checks in its own checkout: no effect."""
    setting(world, repo, REQUIRED, pushed=False)
    main(["pr-merge", *merge_args()])
    assert world.ran.exists()
    assert ["pr", "merge", "7", "--merge", "--match-head-commit", world.head, "--author-email"] == next(
        call for call in world.calls() if call[:2] == ["pr", "merge"]
    )[:7]


def test_a_branch_switching_its_own_gate_back_to_hk_still_queues(queued: World, repo: Path) -> None:
    """origin's trunk says required-checks; a branch that sets local-hk in its own checkout does not change that."""
    setting(queued, repo, LOCAL, pushed=False)
    main(["pr-merge", *merge_args()])
    assert not queued.ran.exists()
    assert [call for call in queued.calls() if call[:2] == ["pr", "merge"]] == [queue_form(queued)]


def test_a_file_without_the_table_keeps_the_local_hk_gate(world: World, repo: Path) -> None:
    setting(world, repo, "[other]\nkey = 1\n", pushed=True)
    main(["pr-merge", *merge_args()])
    assert world.ran.exists()


def test_an_unknown_gate_is_refused_before_hk_and_the_merge(
    world: World, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setting(world, repo, '[pr-merge]\ngate = "none"\n', pushed=True)
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert said == "repotools.toml on origin/trunk sets [pr-merge] gate = 'none'; it takes local-hk or required-checks"
    assert not world.ran.exists()
    assert not world.merged()


def test_a_default_branch_missing_from_the_clone_is_refused(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/trunk"], check=True)
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert said == "origin/trunk is not in this clone, so its repotools.toml cannot be read; run git fetch origin"
    assert not world.merged()


def test_check_only_reports_hk_as_skipped_and_names_the_setting(
    queued: World, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    main(["pr-merge", "--check-only", *merge_args()])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["gate"] for line in lines] == GATES
    assert lines[:-1] == [{"gate": gate, "refusal": None} for gate in GATES[:-1]]
    assert lines[-1] == {
        "gate": "hk",
        "refusal": None,
        "skipped": 'repotools.toml on origin/trunk sets [pr-merge] gate = "required-checks": the merge queue\'s'
        " required checks are the gate, so hk check --pr does not run",
    }
    assert not queued.ran.exists()
    assert not queued.merged()


def test_cpp_standard_sets_required_checks() -> None:
    """This repository's committed setting: its merges rely on the required CI checks (#213)."""
    assert tomllib.loads((REPO / "repotools.toml").read_text()) == {"pr-merge": {"gate": "required-checks"}}
