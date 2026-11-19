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
    times = {"at", "opened_at", "closed_at"}
    return [{key: value for key, value in line.items() if key not in times} for line in report(capsys, *args)]


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
        {"kind": "retro-owed", "round": OTHER, "sessions": ["lead-1", "w-2"], "plan": "p", "prs": []},
        {"kind": "section", "section": "owing-retro", "count": 1, "unknown": None},
        {"exit": "0"},
    ]


def test_a_store_never_written_reports_no_open_round_and_no_debt(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "report") == [
        {"kind": "section", "section": "open-rounds", "count": 0, "unknown": None},
        {"kind": "section", "section": "owing-retro", "count": 0, "unknown": None},
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
    *sections, code = run(capsys, "report")
    assert code == {"exit": "0"}
    assert [(section["section"], section["count"]) for section in sections] == [
        ("open-rounds", None),
        ("owing-retro", None),
    ]
    assert all(reason in str(section["unknown"]) for section in sections)


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
    assert {"kind": "section", "section": "open-rounds", "count": 1, "unknown": None} in run(capsys, "report")


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


def retro(capsys: pytest.CaptureFixture[str], *extra: str, round_id: str = ROUND) -> list[dict[str, object]]:
    base = ["round-retro", "--round", round_id, "--source", "lead-1", "--findings-at", "plan/findings.md"]
    return run(capsys, *base, *extra)


def owing(capsys: pytest.CaptureFixture[str]) -> list[object]:
    """The rounds the report lists as owing a retro, after checking the section's count line."""
    lines = run(capsys, "report")
    owed = [line["round"] for line in lines if line.get("kind") == "retro-owed"]
    assert {"kind": "section", "section": "owing-retro", "count": len(owed), "unknown": None} in lines
    return owed


def test_a_closed_round_owes_a_retro_and_an_open_one_does_not(capsys: pytest.CaptureFixture[str]) -> None:
    for round_id in (ROUND, OTHER):
        run(capsys, "round-open", "--round", round_id)
    run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5")
    close(capsys, ROUND)
    assert run(capsys, "report") == [
        {"kind": "open-round", "round": OTHER, "prs": []},
        {"kind": "section", "section": "open-rounds", "count": 1, "unknown": None},
        {
            "kind": "retro-owed",
            "round": ROUND,
            "sessions": ["lead-1", "w-2"],
            "plan": "p",
            "prs": [{"repo": "o/r", "number": 5, "head": HEAD_A}],
        },
        {"kind": "section", "section": "owing-retro", "count": 1, "unknown": None},
        {"exit": "0"},
    ]


def test_a_retro_with_zero_findings_clears_the_debt(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    run(capsys, "round-open", "--round", ROUND)
    close(capsys)
    log = gh_stand_in({}, set())
    assert retro(capsys, "--findings", "0") == [
        {
            "kind": "retro",
            "round": ROUND,
            "sources": ["lead-1"],
            "findings": 0,
            "findings_at": "plan/findings.md",
            "changes": [],
        },
        {"exit": "0"},
    ]
    assert not log.exists()
    assert [event["kind"] for event in stored(state)] == ["open", "close", "retro"]
    assert owing(capsys) == []


def test_a_retro_whose_proposals_are_all_declined_clears_the_debt(capsys: pytest.CaptureFixture[str]) -> None:
    for round_id in (ROUND, OTHER):
        run(capsys, "round-open", "--round", round_id)
        close(capsys, round_id)
    declined = ["--declined", "a mise task for X", "--declined", "a doctor check for Y"]
    assert retro(capsys, "--findings", "2", *declined)[0]["changes"] == [
        {"change": "a mise task for X", "disposition": "declined"},
        {"change": "a doctor check for Y", "disposition": "declined"},
    ]
    assert owing(capsys) == [OTHER]


def test_a_retro_records_one_disposition_per_change(capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "round-open", "--round", ROUND)
    close(capsys)
    changes = ["--later", "c", "--accepted", "a", "--declined", "b", "--accepted", "a2"]
    assert retro(capsys, "--findings", "3", *changes)[0]["changes"] == [
        {"change": "a", "disposition": "accepted"},
        {"change": "a2", "disposition": "accepted"},
        {"change": "b", "disposition": "declined"},
        {"change": "c", "disposition": "later"},
    ]


def test_replaying_close_or_retro_neither_duplicates_nor_restores_debt(
    state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run(capsys, "round-open", "--round", ROUND)
    close(capsys)
    close(capsys)
    assert owing(capsys) == [ROUND]
    first = retro(capsys, "--findings", "0")
    close(capsys)
    assert owing(capsys) == []
    before = (state / "cpp-standard.jsonl").read_text()
    # A replay with other arguments prints the stored retro and writes nothing.
    assert retro(capsys, "--findings", "4", "--later", "x") == first
    assert (state / "cpp-standard.jsonl").read_text() == before
    assert owing(capsys) == []
    assert [event["kind"] for event in stored(state)] == ["open", "close", "retro"]


@pytest.mark.parametrize(
    ("setup", "detail"),
    [
        ([], f"round {ROUND} was never opened"),
        ([["round-open", "--round", ROUND]], f"round {ROUND} is not closed: close it before its retro"),
    ],
)
def test_a_retro_for_a_round_not_closed_is_refused(
    state: Path, capsys: pytest.CaptureFixture[str], setup: list[list[str]], detail: str
) -> None:
    for earlier in setup:
        report(capsys, *earlier)
    assert retro(capsys, "--findings", "0") == [
        {"path": str(state / "cpp-standard.jsonl"), "check": "rounds", "detail": detail},
        {"exit": "1"},
    ]
    lane = state / "cpp-standard.jsonl"
    assert ([event["kind"] for event in stored(state)] if lane.exists() else []) == ["open"] * len(setup)
    assert owing(capsys) == []


@pytest.mark.parametrize("findings", ["-1", "x"])
def test_a_retro_states_a_finding_count_of_zero_or_more(capsys: pytest.CaptureFixture[str], findings: str) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["round-retro", "--round", ROUND, "--source", "s", "--findings-at", "f", "--findings", findings])
    assert stop.value.code == 1
    assert "findings" in json.loads(capsys.readouterr().err)["error"]


def test_a_change_given_twice_is_refused(state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "round-open", "--round", ROUND)
    close(capsys)
    assert retro(capsys, "--findings", "1", "--accepted", "x", "--declined", "x") == [
        {"path": str(state / "cpp-standard.jsonl"), "check": "rounds", "detail": "a change has one disposition: x"},
        {"exit": "1"},
    ]
    assert owing(capsys) == [ROUND]
