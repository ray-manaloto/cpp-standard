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
HEAD_C = "c" * 40
TREE_A = "1" * 40
TREE_B = "2" * 40
TREE_C = "3" * 40
PULL = "repos/o/r/pulls/5"
MERGED_AT = "2026-11-18T12:00:00Z"
LISTING = "repos/o/r/pulls?state=closed&per_page=100"

type GhStandIn = Callable[[dict[str, object], set[str]], Path]


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh_stand_in: GhStandIn) -> Path:
    """Every test writes under tmp_path, never the real home, and asks a stand-in gh that knows o/r#3 and #5."""
    pull = {"number": 5, "head": {"sha": HEAD_A}}
    gh_stand_in(
        {PULL: pull, "repos/o/r/pulls/3": pull, "repos/o/.github/pulls/1": pull, LISTING: [[]]},
        set(),
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
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
        {"kind": "section", "section": "without-receipt", "count": 0, "unknown": None},
        {"kind": "section", "section": "merges-in-no-round", "count": 0, "unknown": None},
        {"exit": "0"},
    ]


def test_a_store_never_written_reports_no_open_round_and_no_debt(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "report") == [
        {"kind": "section", "section": "open-rounds", "count": 0, "unknown": None},
        {"kind": "section", "section": "owing-retro", "count": 0, "unknown": None},
        {"kind": "section", "section": "without-receipt", "count": 0, "unknown": None},
        {"kind": "section", "section": "merges-in-no-round", "count": 0, "unknown": None},
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
        ("without-receipt", None),
        ("merges-in-no-round", None),
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
        {"kind": "section", "section": "without-receipt", "count": 0, "unknown": None},
        {"kind": "section", "section": "merges-in-no-round", "count": 0, "unknown": None},
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


def receipts_dir(state: Path) -> Path:
    return state.parent / "receipts"


def write_receipt(state: Path, tree: str, verdict: str = "PASS") -> None:
    directory = receipts_dir(state)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "receipt", "tree": tree, "verdict": verdict, "at": "2026-11-18T12:00:00+00:00"}
    (directory / f"{tree}.json").write_text(json.dumps(payload) + "\n")


def closed_pull(
    number: int, head: str, merged_at: str | None = MERGED_AT, *, merge_commit_sha: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {"number": number, "head": {"sha": head}, "merged_at": merged_at}
    if merge_commit_sha is not None:
        payload["merge_commit_sha"] = merge_commit_sha
    return payload


def commit_payload(
    sha: str, tree: str, message: str = "feat: change\n", files: list[str] | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {"sha": sha, "commit": {"tree": {"sha": tree}, "message": message}}
    if files is not None:
        payload["files"] = [{"filename": name} for name in files]
    return payload


def setup_closed_round(
    capsys: pytest.CaptureFixture[str],
    gh_stand_in: GhStandIn,
    round_id: str,
    prs: list[tuple[int, str]],
) -> None:
    run(capsys, "round-open", "--round", round_id)
    for number, head in prs:
        gh_stand_in({f"repos/o/r/pulls/{number}": {"number": number, "head": {"sha": head}}}, set())
        run(capsys, "round-pr", "--round", round_id, "--repo", "o/r", "--number", str(number))
    gh_stand_in({f"repos/o/r/pulls/{number}": {"number": number, "head": {"sha": head}} for number, head in prs}, set())
    close(capsys, round_id)


def test_reconcile_joins_merges_to_rounds_and_lists_merges_in_no_round(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_B)])
    setup_closed_round(capsys, gh_stand_in, OTHER, [(5, HEAD_B), (6, HEAD_A)])
    write_receipt(state, TREE_A, "PASS")
    log = gh_stand_in(
        {
            LISTING: [
                [closed_pull(5, HEAD_B), closed_pull(4, HEAD_C, merged_at=None)],
                [closed_pull(6, HEAD_A), closed_pull(9, HEAD_C)],
            ],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A),
            f"repos/o/r/commits/{HEAD_B}": commit_payload(HEAD_B, TREE_B),
            f"repos/o/r/commits/{HEAD_C}": commit_payload(HEAD_C, TREE_C),
        },
        set(),
    )
    lines = run(capsys, "report")
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert all(call[0] == "api" for call in calls)
    assert not any(flag in call for call in calls for flag in ("-X", "--method", "-f", "-F", "--input"))
    assert lines == [
        {"kind": "section", "section": "open-rounds", "count": 0, "unknown": None},
        {
            "kind": "retro-owed",
            "round": ROUND,
            "sessions": ["lead-1", "w-2"],
            "plan": "p",
            "prs": [{"repo": "o/r", "number": 5, "head": HEAD_B}],
        },
        {
            "kind": "retro-owed",
            "round": OTHER,
            "sessions": ["lead-1", "w-2"],
            "plan": "p",
            "prs": [{"repo": "o/r", "number": 5, "head": HEAD_B}, {"repo": "o/r", "number": 6, "head": HEAD_A}],
        },
        {"kind": "section", "section": "owing-retro", "count": 2, "unknown": None},
        {
            "kind": "round-without-receipt",
            "round": ROUND,
            "repo": "o/r",
            "number": 5,
            "head": HEAD_B,
            "reading": "unverified",
            "reason": "no Verify-Receipt trailer",
        },
        {
            "kind": "round-without-receipt",
            "round": OTHER,
            "repo": "o/r",
            "number": 5,
            "head": HEAD_B,
            "reading": "unverified",
            "reason": "no Verify-Receipt trailer",
        },
        {
            "kind": "merge-without-receipt",
            "repo": "o/r",
            "number": 5,
            "head": HEAD_B,
            "merged_at": MERGED_AT,
            "rounds": [ROUND, OTHER],
            "reading": "unverified",
            "reason": "no Verify-Receipt trailer",
        },
        {
            "kind": "merge-without-receipt",
            "repo": "o/r",
            "number": 9,
            "head": HEAD_C,
            "merged_at": MERGED_AT,
            "rounds": [],
            "reading": "unverified",
            "reason": "no Verify-Receipt trailer",
        },
        {"kind": "section", "section": "without-receipt", "count": 4, "unknown": None},
        {"kind": "merge-in-no-round", "repo": "o/r", "number": 9, "head": HEAD_C, "merged_at": MERGED_AT},
        {"kind": "section", "section": "merges-in-no-round", "count": 1, "unknown": None},
        {"exit": "0"},
    ]


def test_report_repo_flag_reconciles_a_repository_with_no_rounds(
    capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    gh_stand_in(
        {
            LISTING: [[closed_pull(9, HEAD_B)]],
            f"repos/o/r/commits/{HEAD_B}": commit_payload(HEAD_B, TREE_B),
        },
        set(),
    )
    assert run(capsys, "report", "--repo", "o/r") == [
        {"kind": "section", "section": "open-rounds", "count": 0, "unknown": None},
        {"kind": "section", "section": "owing-retro", "count": 0, "unknown": None},
        {
            "kind": "merge-without-receipt",
            "repo": "o/r",
            "number": 9,
            "head": HEAD_B,
            "merged_at": MERGED_AT,
            "rounds": [],
            "reading": "unverified",
            "reason": "no Verify-Receipt trailer",
        },
        {"kind": "section", "section": "without-receipt", "count": 1, "unknown": None},
        {"kind": "merge-in-no-round", "repo": "o/r", "number": 9, "head": HEAD_B, "merged_at": MERGED_AT},
        {"kind": "section", "section": "merges-in-no-round", "count": 1, "unknown": None},
        {"exit": "0"},
    ]


@pytest.mark.parametrize(
    ("earlier_message", "expected_reading"),
    [
        ("wip\n", "unverified"),
        (f"wip\n\nVerify-Receipt: {TREE_A} {ROUND}\n", "unknown"),
    ],
)
def test_two_rounds_sharing_a_pull_request_only_final_head_has_pass(
    state: Path,
    capsys: pytest.CaptureFixture[str],
    gh_stand_in: GhStandIn,
    earlier_message: str,
    expected_reading: str,
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    setup_closed_round(capsys, gh_stand_in, OTHER, [(5, HEAD_B)])
    write_receipt(state, TREE_B, "PASS")
    gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_B)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A, earlier_message),
            f"repos/o/r/commits/{HEAD_B}": commit_payload(HEAD_B, TREE_B),
        },
        set(),
    )
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert len(without) == 1
    assert without[0]["kind"] == "round-without-receipt"
    assert without[0]["round"] == ROUND
    assert without[0]["head"] == HEAD_A
    assert without[0]["reading"] == expected_reading
    assert {"kind": "section", "section": "without-receipt", "count": 1, "unknown": None} in lines


def test_commit_pushed_after_round_close_is_caught_per_merge(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    write_receipt(state, TREE_A, "PASS")
    gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_B)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A),
            f"repos/o/r/commits/{HEAD_B}": commit_payload(HEAD_B, TREE_B),
        },
        set(),
    )
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert without == [
        {
            "kind": "merge-without-receipt",
            "repo": "o/r",
            "number": 5,
            "head": HEAD_B,
            "merged_at": MERGED_AT,
            "rounds": [ROUND],
            "reading": "unverified",
            "reason": "no Verify-Receipt trailer",
        }
    ]
    assert {"kind": "section", "section": "without-receipt", "count": 1, "unknown": None} in lines


def test_squash_merge_checks_pr_head_not_landed_commit(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    write_receipt(state, TREE_A, "PASS")
    log = gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_A, merge_commit_sha=HEAD_B)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A),
        },
        {f"repos/o/r/commits/{HEAD_B}"},
    )
    lines = run(capsys, "report")
    assert {"kind": "section", "section": "without-receipt", "count": 0, "unknown": None} in lines
    assert {"kind": "section", "section": "merges-in-no-round", "count": 0, "unknown": None} in lines
    assert not any(HEAD_B in line for line in log.read_text().splitlines())


def test_squash_merge_without_receipt_on_pr_head_reports_pr_head(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    write_receipt(state, TREE_B, "PASS")
    log = gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_A, merge_commit_sha=HEAD_B)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A),
        },
        {f"repos/o/r/commits/{HEAD_B}"},
    )
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert [line["head"] for line in without] == [HEAD_A, HEAD_A]
    assert not any(HEAD_B in line for line in log.read_text().splitlines())


def test_skip_receipt_verifies_only_documentation_only_changes(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    setup_closed_round(capsys, gh_stand_in, OTHER, [(6, HEAD_B)])
    write_receipt(state, TREE_A, "SKIP")
    write_receipt(state, TREE_B, "SKIP")
    write_receipt(state, TREE_C, "FAIL")
    gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_A), closed_pull(6, HEAD_B), closed_pull(7, HEAD_C)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A, files=["docs/guide.md"]),
            f"repos/o/r/commits/{HEAD_B}": commit_payload(
                HEAD_B, TREE_B, f"docs: mix\n\nVerify-Receipt: {TREE_B} {OTHER}\n", files=["src/a.py", "README.md"]
            ),
            f"repos/o/r/commits/{HEAD_C}": commit_payload(
                HEAD_C, TREE_C, f"fix: broken\n\nVerify-Receipt: {TREE_C} p\n", files=["src/a.py"]
            ),
        },
        set(),
    )
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert [(line["kind"], line["number"], line["reading"]) for line in without] == [
        ("round-without-receipt", 6, "unverified"),
        ("merge-without-receipt", 6, "unverified"),
        ("merge-without-receipt", 7, "unverified"),
    ]
    assert "not on a documentation-only change" in str(without[0]["reason"])
    assert "FAIL" in str(without[2]["reason"])


def test_matching_trailer_without_local_receipt_reads_unknown(
    capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_A)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(
                HEAD_A, TREE_A, f"feat: x\n\nCo-Authored-By: A <a@e>\nVerify-Receipt: {TREE_A} plan-1\n"
            ),
        },
        set(),
    )
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert len(without) == 2
    assert all(line["reading"] == "unknown" and "no receipt" in str(line["reason"]) for line in without)


@pytest.mark.parametrize("has_receipt", [False, True])
def test_mismatched_trailer_reads_unverified_changed_after_verification(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn, *, has_receipt: bool
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    if has_receipt:
        write_receipt(state, TREE_A, "PASS")
    gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_A)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(
                HEAD_A, TREE_B, f"feat: edited\n\nVerify-Receipt: {TREE_A} {ROUND}\n"
            ),
        },
        set(),
    )
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert len(without) == 2
    assert all(
        line["reading"] == "unverified" and "changed after verification" in str(line["reason"]) for line in without
    )


def test_commit_without_verify_trailer_reads_unverified(
    capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    gh_stand_in(
        {
            LISTING: [[closed_pull(9, HEAD_A)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A, "feat: plain commit\n"),
        },
        set(),
    )
    lines = run(capsys, "report", "--repo", "o/r")
    assert lines[2] == {
        "kind": "merge-without-receipt",
        "repo": "o/r",
        "number": 9,
        "head": HEAD_A,
        "merged_at": MERGED_AT,
        "rounds": [],
        "reading": "unverified",
        "reason": "no Verify-Receipt trailer",
    }


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (lambda directory: (directory / f"{TREE_A}.json").write_text("{not json\n"), "not a verify receipt"),
        (lambda directory: (directory / f"{TREE_A}.json").mkdir(), "Is a directory"),
        (lambda directory: directory.rmdir() or directory.write_text(""), "Not a directory"),
    ],
)
def test_an_unreadable_receipts_store_makes_without_receipt_unknown(
    state: Path, capsys: pytest.CaptureFixture[str], damage: Callable[[Path], object], reason: str
) -> None:
    directory = receipts_dir(state)
    directory.mkdir(parents=True)
    damage(directory)
    *lines, code = run(capsys, "report")
    assert code == {"exit": "0"}
    assert lines == [
        {"kind": "section", "section": "open-rounds", "count": 0, "unknown": None},
        {"kind": "section", "section": "owing-retro", "count": 0, "unknown": None},
        {"kind": "section", "section": "without-receipt", "count": None, "unknown": lines[2]["unknown"]},
        {"kind": "section", "section": "merges-in-no-round", "count": 0, "unknown": None},
    ]
    assert reason in str(lines[2]["unknown"])


def test_non_json_file_in_receipts_store_is_ignored(
    state: Path, capsys: pytest.CaptureFixture[str], gh_stand_in: GhStandIn
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    write_receipt(state, TREE_A, "PASS")
    (receipts_dir(state) / "README.txt").write_text("ignored\n")
    gh_stand_in(
        {
            LISTING: [[closed_pull(5, HEAD_A)]],
            f"repos/o/r/commits/{HEAD_A}": commit_payload(HEAD_A, TREE_A),
        },
        set(),
    )
    lines = run(capsys, "report")
    assert {"kind": "section", "section": "without-receipt", "count": 0, "unknown": None} in lines


@pytest.mark.parametrize(
    ("responses", "failing", "reason"),
    [
        ({}, {LISTING}, "o/r: HTTP 503"),
        ({LISTING: "<not json>"}, set(), "o/r: gh returned output that is not the expected JSON"),
    ],
)
def test_an_unreadable_github_listing_reads_unknown_with_reason(
    capsys: pytest.CaptureFixture[str],
    gh_stand_in: GhStandIn,
    responses: dict[str, object],
    failing: set[str],
    reason: str,
) -> None:
    run(capsys, "round-open", "--round", ROUND)
    run(capsys, "round-pr", "--round", ROUND, "--repo", "o/r", "--number", "5")
    gh_stand_in(responses, failing)
    lines = run(capsys, "report")
    sections = {line["section"]: line for line in lines if line.get("kind") == "section"}
    assert sections["open-rounds"] == {"kind": "section", "section": "open-rounds", "count": 1, "unknown": None}
    assert sections["owing-retro"] == {"kind": "section", "section": "owing-retro", "count": 0, "unknown": None}
    assert sections["without-receipt"] == {
        "kind": "section",
        "section": "without-receipt",
        "count": None,
        "unknown": reason,
    }
    assert sections["merges-in-no-round"] == {
        "kind": "section",
        "section": "merges-in-no-round",
        "count": None,
        "unknown": reason,
    }


@pytest.mark.parametrize(
    ("responses", "failing", "reason"),
    [
        ({LISTING: [[closed_pull(5, HEAD_A)]]}, {f"repos/o/r/commits/{HEAD_A}"}, "HTTP 503"),
        (
            {LISTING: [[closed_pull(5, HEAD_A)]], f"repos/o/r/commits/{HEAD_A}": "<not json>"},
            set(),
            "gh returned output that is not the expected JSON",
        ),
    ],
)
def test_an_unreadable_github_commit_reads_unknown_with_reason(
    capsys: pytest.CaptureFixture[str],
    gh_stand_in: GhStandIn,
    responses: dict[str, object],
    failing: set[str],
    reason: str,
) -> None:
    setup_closed_round(capsys, gh_stand_in, ROUND, [(5, HEAD_A)])
    gh_stand_in(responses, failing)
    lines = run(capsys, "report")
    without = [line for line in lines if line.get("kind") in {"round-without-receipt", "merge-without-receipt"}]
    assert len(without) == 2
    assert all(
        line["reading"] == "unknown" and HEAD_A in str(line["reason"]) and reason in str(line["reason"])
        for line in without
    )
    assert {"kind": "section", "section": "merges-in-no-round", "count": 0, "unknown": None} in lines
