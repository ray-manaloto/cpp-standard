"""repotools pr-merge's merge gate setting: repotools.toml's [pr-merge] gate, read from origin's default branch.

`local-hk` (the default, and what a missing file or table means) is today's gate: hk check --pr, then the merge.
`required-checks` runs every gate but hk, runs no hk, waits for the pull request's required checks to pass, and puts
it in the merge queue, whose required checks are then the gate (#213).
"""

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from repotools.cli import main
from repotools.merge import NOREPLY

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
    # Done only after the read showed `merged`: the output is the merge commit, not a queued receipt (#158).
    assert json.loads(capsys.readouterr().out) == {"number": 7, "merge_commit": "f00d", "author_email": NOREPLY}
    assert not queued.ran.exists()
    calls = queued.calls()
    merges = [call for call in calls if call[:2] == ["pr", "merge"]]
    # The exact argument list: no --merge (the ruleset allows only the queue's squash), no --author-email (the
    # queue's squash takes the pull request's author), no --auto.
    assert merges == [queue_form(queued)]
    # The required checks pass on the head first, then the queue call, then the reads until merged.
    checks = next(i for i, call in enumerate(calls) if call[:3] == ["jouet", "wait", "ci"])
    assert calls[checks][3:6] == ["7", "--sha", queued.head]
    assert calls.index(queue_form(queued)) > checks
    read = next(i for i, call in enumerate(calls) if call[:2] == ["api", "graphql"])
    assert read > calls.index(queue_form(queued))


def test_required_checks_failing_stops_before_the_queue(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    """A red required check fails the command at once, naming it, rather than leaving an auto-merge armed."""
    queued.set(checks=1, checks_said="lint failed")
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert said == f"the checks of pull request #7 on {queued.head} did not pass (jouet wait ci exit 1): lint failed"
    assert not queued.merged()
    assert not queued.ran.exists()


def test_required_checks_still_refuses_a_dirty_checkout(
    queued: World, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "notes.md").write_text("untracked\n")
    refusal = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert "untracked files" in refusal
    assert "hk check --pr" not in refusal
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
    assert said == (
        f"repotools.toml on origin/trunk ({world.head}) sets [pr-merge] gate = 'none'; "
        "it takes local-hk or required-checks"
    )
    assert not world.ran.exists()
    assert not world.merged()


@pytest.mark.parametrize(
    "ref_change", [["remote", "rename", "origin", "upstream"], ["update-ref", "-d", "refs/remotes/origin/trunk"]]
)
@pytest.mark.parametrize("extra", [[], ["--check-only"]])
def test_missing_origin_ref_uses_local_hk(
    world: World, capsys: pytest.CaptureFixture[str], ref_change: list[str], extra: list[str]
) -> None:
    subprocess.run(["git", *ref_change], check=True)
    main(["pr-merge", *extra, *merge_args()])
    assert capsys.readouterr().err.splitlines() == [
        "origin/trunk is not in this clone; cannot read its repotools.toml, using local-hk"
    ]
    assert world.ran.exists()
    assert world.merged() == (not extra)


@pytest.mark.parametrize(("text", "reason"), [('pr-merge = "x"', "must be a table"), ("[pr-merge", "not valid TOML")])
def test_invalid_setting_names_file_and_ref(
    world: World, repo: Path, capsys: pytest.CaptureFixture[str], text: str, reason: str
) -> None:
    setting(world, repo, text, pushed=True)
    with pytest.raises(SystemExit) as stopped:
        main(["pr-merge", *merge_args()])
    assert stopped.value.code == 1
    (line,) = capsys.readouterr().err.splitlines()
    refusal = json.loads(line)["error"]
    assert "repotools.toml on origin/trunk" in refusal
    assert reason in refusal
    assert not world.merged()
    assert not world.ran.exists()


def test_check_only_reports_bad_setting_beside_other_gates(
    world: World, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    setting(world, repo, "[pr-merge", pushed=True)
    world.set(pr=world.pr() | {"title": "edited"})
    with pytest.raises(SystemExit) as stopped:
        main(["pr-merge", "--check-only", *merge_args()])
    assert stopped.value.code == 1
    captured = capsys.readouterr()
    results = {item["gate"]: item["refusal"] for item in map(json.loads, captured.out.splitlines())}
    assert list(results) == GATES
    assert "title" in results["title"]
    assert "not valid TOML" in results["hk"]
    assert "2 of 8 gates refused" in captured.err
    assert not world.ran.exists()
    assert not world.merged()


def test_subfolder_reads_and_names_the_default_branch_commit(
    queued: World, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted = queued.head
    setting(queued, repo, LOCAL, pushed=False)
    folder = repo / "subfolder"
    folder.mkdir()
    monkeypatch.chdir(folder)
    main(["pr-merge", "--check-only", *merge_args()])
    captured = capsys.readouterr()
    assert f"origin/trunk ({trusted})" in captured.err
    assert "required-checks" in json.loads(captured.out.splitlines()[-1])["skipped"]
    assert not queued.ran.exists()


@pytest.mark.parametrize("field", ["baseRefName", "title", "body"])
def test_edit_during_checks_refuses_queue(queued: World, capsys: pytest.CaptureFixture[str], field: str) -> None:
    queued.set(after_checks={"pr": queued.pr() | {field: "edited"}})
    said = pr_refusal_of(capsys, "pr-merge", merge_args())
    assert ("goes into edited" if field == "baseRefName" else field) in said
    assert not queued.merged()


def test_required_checks_without_queue_reports_gh_refusal(queued: World, capsys: pytest.CaptureFixture[str]) -> None:
    # Non-interactive gh needs a merge method when the target branch has no queue.
    reason = "--merge, --rebase, or --squash required when not running interactively"
    queued.set(refuse=reason)
    assert pr_refusal_of(capsys, "pr-merge", merge_args()) == f"gh failed: {reason}"
    assert [call for call in queued.calls() if call[:2] == ["pr", "merge"]] == [queue_form(queued)]
    assert not queued.ran.exists()


def test_shipping_explains_when_pr_merge_returns() -> None:
    shipping = (REPO / "AGENTS.md").read_text().split("- Shipping:")[1].split("- Worktrees:")[0]
    assert "whose required\n" not in shipping
    assert "returns once the pull request is queued" in shipping
    assert "`jouet wait pr <number> --until merged` waits for the merge" in shipping


def test_generated_claude_mods_tsconfig_does_not_dirty_checkout(repo: Path) -> None:
    (repo / ".gitignore").write_bytes((REPO / ".gitignore").read_bytes())
    commit()
    package = repo / "unix/home/.local/share/claude-mods/example"
    package.mkdir(parents=True)
    (package / "tsconfig.json").write_text("{}")
    assert subprocess.run(["git", "status", "--porcelain"], check=True, capture_output=True).stdout == b""


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
