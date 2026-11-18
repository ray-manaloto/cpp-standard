"""repotools pr-merge --check-only: every gate runs and is reported, and nothing is merged."""

import json
import os
import sys
from pathlib import Path

import pytest

from repotools.cli import main

from . import test_gates
from .test_gates import copy, mise, said
from .test_merge import BODY, HK_RAN, World, hk_config, install_gh, merge_args, world
from .test_pr_create import repo

__all__ = ["copy", "repo", "world"]  # the fixtures, used by name
GATES = ["clean", "head", "open", "base", "pr-head", "title", "body", "hk"]


def reported(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_every_gate_holding_reports_each_and_merges_nothing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    main(["pr-merge", "--check-only", *merge_args()])
    assert reported(capsys) == [{"gate": gate, "refusal": None} for gate in GATES]
    assert world.ran.exists()  # hk check --pr ran the checkout's step
    assert not world.merged()
    assert ["pr", "view", "7", "--json", "mergeCommit"] not in world.calls()


def test_failing_gates_are_each_reported_and_every_other_gate_still_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    made = World(repo, monkeypatch, f"{HK_RAN} && exit 3")
    made.set(pr=made.pr() | {"title": "feat: edited"})
    (repo / "notes.md").write_text("untracked\n")
    capsys.readouterr()
    with pytest.raises(SystemExit) as stopped:
        main(["pr-merge", "--check-only", *merge_args()])
    assert stopped.value.code == 1
    captured = capsys.readouterr()
    results = {line["gate"]: line["refusal"] for line in map(json.loads, captured.out.splitlines())}
    assert list(results) == GATES
    assert results == {
        "clean": "the checkout has changes or untracked files, so hk check --pr would not test the head alone",
        "head": None,
        "open": None,
        "base": None,
        "pr-head": None,
        "title": "pull request #7's title on GitHub is not the given title",
        "body": None,
        "hk": f"hk check --pr failed (exit 3) on {made.head}",
    }
    assert json.loads(captured.err) == {"error": "check-only: 3 of 8 gates refused pull request #7"}
    assert made.ran.exists()
    assert not made.merged()


def test_the_task_passes_check_only_to_the_installed_repotools(copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mise run //repo:pr-merge --check-only reaches the installed repotools as --check-only: every gate is reported,
    the copy's hk check exits 3, and the gh stand-in is never asked to merge."""
    tools = copy.parent / "tool-bin"
    tools.mkdir()
    (tools / "repotools").symlink_to(Path(sys.executable).parent / "repotools")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tools))
    (copy.parent / "bin").mkdir()
    log = copy.parent / "calls.jsonl"
    gh = install_gh(copy.parent / "bin", copy.parent / "scenario.json", log)
    with (copy / "mise.local.toml").open("a") as local:
        local.write(f'\n[wrappers.gh]\ncommand = "{gh}"\n')
    (copy / "body.md").write_text(BODY)
    for name in [name for name in os.environ if name.startswith("HK_")]:
        monkeypatch.delenv(name)
    (copy / "hk.pkl").write_text(hk_config("exit 3"))
    head = test_gates.commit("hk exits 3")
    shown = {"headRefOid": head, "state": "OPEN", "baseRefName": "main", "title": "feat: one", "body": BODY}
    (copy.parent / "scenario.json").write_text(json.dumps({"pr": shown, "default": "main"}))
    done = mise("//repo:pr-merge", "--check-only", "7", "feat: one", "body.md")
    assert done.returncode == 1
    gates = [json.loads(line) for line in done.stdout.splitlines() if line.startswith('{"gate"')]
    assert [gate["gate"] for gate in gates] == GATES
    assert [gate["gate"] for gate in gates if gate["refusal"]] == ["hk"]
    (error,) = said(done, "{")
    assert json.loads(error)["error"] == "check-only: 1 of 8 gates refused pull request #7"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(call[:2] == ["pr", "merge"] for call in calls)
