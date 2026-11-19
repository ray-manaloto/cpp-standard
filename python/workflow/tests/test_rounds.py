"""Rounds through the command line: open, pr and close events over a temporary state directory, and the report."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from workflowtools.cli import main

from .conftest import report

ROUND = "cpp-standard-20261118-rounds"
OTHER = "cpp-standard-20261118-other"
HEAD_A = "a" * 40
HEAD_B = "b" * 40
PULL = "repos/o/r/pulls/5"

type GhStandIn = Callable[[dict[str, object], set[str]], Path]


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh_stand_in: GhStandIn) -> Path:
    """Every test writes under tmp_path, never the real home, and asks a stand-in gh that knows o/r#3 and #5."""
    pull = {"number": 5, "head": {"sha": HEAD_A}}
    gh_stand_in({PULL: pull, "repos/o/r/pulls/3": pull, "repos/o/.github/pulls/1": pull}, set())
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "state" / "workflowtools" / "rounds"


def run(capsys: pytest.CaptureFixture[str], *args: str) -> list[dict[str, object]]:
    """The command's stdout lines without their write time, then the exit code."""
    lines = report(capsys, *args)
    return [{key: value for key, value in line.items() if key not in {"at", "opened_at"}} for line in lines]


def stored(state: Path, lane: str = "cpp-standard") -> list[dict[str, object]]:
    return [json.loads(line) for line in (state / f"{lane}.jsonl").read_text().splitlines()]


def close(capsys: pytest.CaptureFixture[str], round_id: str = ROUND) -> list[dict[str, object]]:
    return run(capsys, "round-close", "--round", round_id, "--session", "lead-1", "--session", "w-2", "--plan", "p")


def test_open_pr_and_close_are_written_and_read_back(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    gh_stand_in({PULL: {"number": 5, "head": {"sha": HEAD_A}}}, set())
    assert run(capsys, "round-open", "--round", ROUND) == [{"kind": "open", "round": ROUND}, {"exit": "0"}]
    assert run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5") == [
        {"kind": "pr", "round": ROUND, "repo": "o/r", "number": 5},
        {"exit": "0"},
    ]
    closed = {
        "kind": "close",
        "round": ROUND,
        "sessions": ["lead-1", "w-2"],
        "plan": "p",
        "prs": [{"repo": "o/r", "number": 5, "head": HEAD_A}],
    }
    assert close(capsys) == [closed, {"exit": "0"}]
    assert [event["kind"] for event in stored(state)] == ["open", "pr", "close"]
    assert all(str(event["at"]).endswith("+00:00") for event in stored(state))


def test_replaying_any_event_adds_nothing(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    gh_stand_in({PULL: {"number": 5, "head": {"sha": HEAD_A}}}, set())
    steps = [
        ["round-open", "--round", ROUND],
        ["round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5"],
        ["round-close", "--round", ROUND, "--session", "s", "--plan", "p"],
    ]
    first = [report(capsys, *step) for step in steps]
    before = (state / "cpp-standard.jsonl").read_text()
    # GitHub is down and the head moved: a replayed close still prints the stored event and asks nothing.
    gh_stand_in({PULL: {"number": 5, "head": {"sha": HEAD_B}}}, {PULL})
    assert [report(capsys, *step) for step in steps] == first
    assert (state / "cpp-standard.jsonl").read_text() == before


def test_a_round_with_no_pull_request_opens_and_closes(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    log = gh_stand_in({}, set())
    run(capsys, "round-open", "--round", ROUND)
    assert close(capsys)[0]["prs"] == []
    assert not log.exists()
    assert [event["kind"] for event in stored(state)] == ["open", "close"]


def test_two_rounds_sharing_a_pull_request_record_their_own_head(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    for round_id in (ROUND, OTHER):
        run(capsys, "round-open", "--round", round_id)
        run(capsys, "round-pr", "--round", round_id, "--repo", "o/r", "--number", "5")
    gh_stand_in({PULL: {"number": 5, "head": {"sha": HEAD_A}}}, set())
    close(capsys, ROUND)
    gh_stand_in({PULL: {"number": 5, "head": {"sha": HEAD_B}}}, set())
    close(capsys, OTHER)
    heads = {event["round"]: event["prs"] for event in stored(state) if event["kind"] == "close"}
    assert heads == {
        ROUND: [{"repo": "o/r", "number": 5, "head": HEAD_A}],
        OTHER: [{"repo": "o/r", "number": 5, "head": HEAD_B}],
    }


def test_a_close_github_cannot_answer_writes_nothing(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    run(capsys, "round-open", "--round", ROUND)
    run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5")
    gh_stand_in({}, {PULL})
    assert close(capsys) == [
        {"kind": "github-unavailable", "check": "rounds", "repo": "o/r", "detail": "HTTP 503"},
        {"exit": "2"},
    ]
    gh_stand_in({PULL: "<not json>"}, set())
    assert close(capsys)[0]["detail"] == "gh returned output that is not the expected JSON"
    assert [event["kind"] for event in stored(state)] == ["open", "pr"]


@pytest.mark.parametrize(
    ("setup", "step", "detail"),
    [
        ([], ["round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5"], f"round {ROUND} was never opened"),
        ([], ["round-close", "--round", ROUND, "--session", "s", "--plan", "p"], f"round {ROUND} was never opened"),
        (
            [["round-open", "--round", ROUND], ["round-close", "--round", ROUND, "--session", "s", "--plan", "p"]],
            ["round-pr", "--round", ROUND, "--repo", "o/r", "--number", "6"],
            f"round {ROUND} is closed",
        ),
    ],
)
def test_an_event_out_of_order_is_refused(
    state: Path, capsys: pytest.CaptureFixture[str], setup: list[list[str]], step: list[str], detail: str
) -> None:
    for earlier in setup:
        report(capsys, *earlier)
    before = (state / "cpp-standard.jsonl").read_text() if setup else None
    assert run(capsys, *step) == [
        {"path": str(state / "cpp-standard.jsonl"), "check": "rounds", "detail": detail},
        {"exit": "1"},
    ]
    assert ((state / "cpp-standard.jsonl").read_text() if setup else None) == before


def test_the_report_lists_open_rounds(capsys: pytest.CaptureFixture[str]) -> None:
    for round_id in (OTHER, ROUND, "dotfiles-20261117-wiki"):
        run(capsys, "round-open", "--round", round_id)
    run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5")
    run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "3")
    close(capsys, OTHER)
    assert run(capsys, "report") == [
        {"kind": "open-round", "round": ROUND, "prs": [{"repo": "o/r", "number": 5}, {"repo": "o/r", "number": 3}]},
        {"kind": "open-round", "round": "dotfiles-20261117-wiki", "prs": []},
        {"kind": "section", "section": "open-rounds", "count": 2, "unknown": None},
        {"exit": "0"},
    ]


def test_a_store_never_written_reports_no_open_round(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "report") == [
        {"kind": "section", "section": "open-rounds", "count": 0, "unknown": None},
        {"exit": "0"},
    ]


def test_the_default_store_is_under_the_home_state_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_STATE_HOME")
    run(capsys, "round-open", "--round", ROUND)
    assert (tmp_path / "home" / ".local" / "state" / "workflowtools" / "rounds" / "cpp-standard.jsonl").is_file()


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (lambda state: (state / "cpp-standard.jsonl").write_text("{not json\n"), "cpp-standard.jsonl line 1"),
        (lambda state: (state / "cpp-standard.jsonl").write_text('{"kind": "retro"}\n'), "cpp-standard.jsonl line 1"),
        (lambda state: (state / "cpp-standard.jsonl").mkdir(), "Is a directory"),
        (lambda state: state.rmdir() or state.write_text(""), "Not a directory"),
    ],
)
def test_an_unreadable_store_reads_unknown_with_the_reason(
    state: Path, capsys: pytest.CaptureFixture[str], damage: Callable[[Path], object], reason: str
) -> None:
    state.mkdir(parents=True)
    damage(state)
    *_, section, code = run(capsys, "report")
    assert (section["count"], code) == (None, {"exit": "0"})
    assert reason in str(section["unknown"])


def test_a_damaged_store_refuses_a_new_event(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state.mkdir(parents=True)
    (state / "cpp-standard.jsonl").write_text("{not json\n")
    with pytest.raises(SystemExit) as stop:
        main(["round-open", "--round", ROUND])
    assert stop.value.code == 1
    assert "cpp-standard.jsonl line 1: not a round event" in json.loads(capsys.readouterr().err)["error"]
    assert (state / "cpp-standard.jsonl").read_text() == "{not json\n"


@pytest.mark.parametrize(
    "round_id", ["../x-20261118-y", "cpp-standard", "x-2026111-y", "X-20261118-y", "a/b-20261118-c"]
)
def test_a_round_id_must_be_lane_date_slug(capsys: pytest.CaptureFixture[str], round_id: str) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["round-open", "--round", round_id])
    assert stop.value.code == 1
    assert "round" in json.loads(capsys.readouterr().err)["error"]


@pytest.mark.parametrize("repo", ["../..", "a/..", "a/.", "../r", "a/b/c"])
def test_a_repo_must_be_owner_and_name(capsys: pytest.CaptureFixture[str], repo: str) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["round-pr", "--round", ROUND, "--repo", repo, "--number", "1"])
    assert stop.value.code == 1
    assert "repo" in json.loads(capsys.readouterr().err)["error"]


def test_a_dot_github_repository_is_a_repo(capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "round-open", "--round", ROUND)
    assert run(capsys, "round-pr", "--round", ROUND, "--repo", "o/.github", "--number", "1")[0]["repo"] == "o/.github"


def test_a_blank_line_in_a_lane_file_is_skipped(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "round-open", "--round", ROUND)
    with (state / "cpp-standard.jsonl").open("a") as stream:
        stream.write("\n  \n")
    assert run(capsys, "report")[-2] == {"kind": "section", "section": "open-rounds", "count": 1, "unknown": None}


def test_a_pull_request_github_cannot_read_is_not_added(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    run(capsys, "round-open", "--round", ROUND)
    gh_stand_in({}, {"repos/o/r/pulls/55"})
    assert run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "55") == [
        {"kind": "github-unavailable", "check": "rounds", "repo": "o/r", "detail": "HTTP 503"},
        {"exit": "2"},
    ]
    assert [event["kind"] for event in stored(state)] == ["open"]
