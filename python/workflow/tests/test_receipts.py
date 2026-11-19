"""Verify receipts through the command line: remember, save, and compare at commit, in a real git repository."""

import json
import subprocess
from pathlib import Path

import pytest

from workflowtools.cli import main

from .conftest import report, write

PLAN = "2026-11-18-161-verify-receipts"
COMMIT = ["-c", "user.name=t", "-c", "user.email=t@e", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Receipts go under tmp_path, never the real home."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state" / "workflowtools" / "receipts"


@pytest.fixture
def work(repo: Path) -> Path:
    """A repository with one commit, a tracked source file and a tracked doc."""
    write(repo, {"a.py": "one\n", "README.md": "# r\n"})
    git(repo, "add", "a.py", "README.md")
    git(repo, *COMMIT, "commit", "-qm", "c")
    return repo


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, check=True, text=True).stdout


def begin(capsys: pytest.CaptureFixture[str]) -> str:
    lines = report(capsys, "verify-receipt")
    assert lines[-1] == {"exit": "0"}
    assert lines[0]["kind"] == "verify-begin"
    return lines[0]["tree"]


def verdict(capsys: pytest.CaptureFixture[str], value: str = "PASS") -> list[dict[str, str]]:
    return report(capsys, "verify-receipt", "--verdict", value)


def commit_check(capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, str]:
    lines = report(capsys, "verify-commit", "--plan", PLAN, *extra)
    # Report-only: whatever the comparison says, the commit is never stopped.
    assert lines[-1] == {"exit": "0"}
    return lines[0]


def verified(capsys: pytest.CaptureFixture[str], value: str = "PASS") -> str:
    tree = begin(capsys)
    line, code = verdict(capsys, value)
    assert code == {"exit": "0"}
    expected = {"kind": "receipt", "tree": tree, "verdict": value}
    assert {key: line[key] for key in expected} == expected
    assert line["at"].endswith("+00:00")
    return tree


def test_verified_content_staged_unchanged_matches(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n"})
    tree = verified(capsys)
    git(work, "add", "a.py")
    line = commit_check(capsys)
    assert line["status"] == "match"
    assert (line["staged"], line["verified"], line["verdict"]) == (tree, tree, "PASS")
    assert line["trailer"] == f"Verify-Receipt: {tree} {PLAN}"


def test_the_trailer_names_no_path(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n"})
    verified(capsys)
    git(work, "add", "a.py")
    _, tree, plan = commit_check(capsys)["trailer"].split(" ")
    assert (len(tree), plan) == (40, PLAN)
    assert "/" not in commit_check(capsys)["trailer"]


@pytest.mark.parametrize("plan", ["a/b", "../x", "/abs", ""])
def test_a_plan_that_could_be_a_path_is_refused(work: Path, capsys: pytest.CaptureFixture[str], plan: str) -> None:
    assert work.exists()
    with pytest.raises(SystemExit) as stop:
        main(["verify-commit", "--plan", plan])
    assert stop.value.code == 1
    assert "plan" in json.loads(capsys.readouterr().err)["error"]


def test_an_edit_after_the_receipt_is_a_mismatch(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n"})
    tree = verified(capsys)
    write(work, {"a.py": "three\n"})
    git(work, "add", "a.py")
    line = commit_check(capsys)
    assert line["status"] == "mismatch"
    assert line["verified"] == tree
    assert line["staged"] != tree
    # The trailer names the verified tree, so a reader sees the commit changed after verification.
    assert line["trailer"] == f"Verify-Receipt: {tree} {PLAN}"


def test_an_edit_between_the_hash_and_the_verdict_saves_no_pass(
    work: Path, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(work, {"a.py": "two\n"})
    begin(capsys)
    write(work, {"a.py": "three\n"})
    finding, code = verdict(capsys)
    assert code == {"exit": "1"}
    assert finding["check"] == "verify"
    assert "verify again" in finding["detail"]
    assert not state.exists() or not any(state.iterdir())
    git(work, "add", "a.py")
    assert commit_check(capsys)["status"] == "no-receipt"


def test_an_added_untracked_file_is_part_of_the_hash(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n", "new.py": "new\n"})
    tree = verified(capsys)
    assert "new.py" in git(work, "ls-tree", "--name-only", tree).split()
    git(work, "add", "a.py")
    assert commit_check(capsys)["status"] == "mismatch"
    git(work, "add", "new.py")
    assert commit_check(capsys)["status"] == "match"


def test_an_ignored_file_is_not_part_of_the_hash(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {".git/info/exclude": "scratch.txt\n", "scratch.txt": "x\n"})
    assert "scratch.txt" not in git(work, "ls-tree", "--name-only", begin(capsys)).split()


def test_content_staged_apart_from_what_was_verified_is_a_mismatch(
    work: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(work, {"a.py": "two\n", "README.md": "# two\n"})
    verified(capsys)
    git(work, "add", "a.py")
    assert commit_check(capsys)["status"] == "mismatch"


def test_no_receipt_is_reported_as_such(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n"})
    git(work, "add", "a.py")
    line = commit_check(capsys)
    assert (line["status"], line["verified"], line["verdict"], line["trailer"]) == ("no-receipt", None, None, None)


def test_the_real_index_is_unchanged(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n", "new.py": "new\n"})
    index = work / ".git" / "index"
    before = index.read_bytes()
    verified(capsys)
    commit_check(capsys)
    assert index.read_bytes() == before
    assert git(work, "status", "--porcelain") == " M a.py\n?? new.py\n"


def test_a_verdict_without_a_remembered_tree_is_refused(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert work.exists()
    finding, code = verdict(capsys)
    assert code == {"exit": "1"}
    assert "run workflowtools verify-receipt before /verify" in finding["detail"]


def test_each_verdict_needs_its_own_remembered_tree(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n"})
    verified(capsys)
    assert verdict(capsys)[-1] == {"exit": "1"}


@pytest.mark.parametrize(
    ("files", "accepted"),
    [
        ({"README.md": "# two\n", "docs/new.rst": "x\n", "CHANGELOG.MD": "x\n"}, True),
        ({"README.md": "# two\n", "a.py": "two\n"}, False),
        ({"tests/test_a.py": "def test(): pass\n"}, False),
    ],
    ids=["documentation-only", "mixed", "test-only"],
)
def test_skip_needs_a_documentation_only_change(
    work: Path, state: Path, capsys: pytest.CaptureFixture[str], files: dict[str, str], *, accepted: bool
) -> None:
    write(work, files)
    begin(capsys)
    line, code = verdict(capsys, "SKIP")
    assert code == {"exit": "0" if accepted else "1"}
    if accepted:
        assert line["verdict"] == "SKIP"
    else:
        assert "PASS is required" in line["detail"]
        assert not state.exists() or not any(state.iterdir())
        # The remembered tree stays, so the same content can still get its PASS.
        assert verdict(capsys, "PASS")[-1] == {"exit": "0"}


def test_skip_on_documentation_before_the_first_commit(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, {"README.md": "# r\n"})
    begin(capsys)
    assert verdict(capsys, "SKIP")[-1] == {"exit": "0"}
    assert not (repo / ".git" / "index").exists()


def test_a_fail_receipt_matches_and_carries_its_verdict(work: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(work, {"a.py": "two\n"})
    verified(capsys, "FAIL")
    git(work, "add", "a.py")
    line = commit_check(capsys)
    assert (line["status"], line["verdict"], line["trailer"]) == ("match", "FAIL", None)


@pytest.mark.parametrize("value", ["FAIL", "BLOCKED"])
def test_an_edit_after_a_failing_verdict_gets_no_trailer(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    message = tmp_path / "message.txt"
    message.write_text("fix: one\n")
    write(work, {"a.py": "two\n"})
    verified(capsys, value)
    write(work, {"a.py": "fixed\n"})
    git(work, "add", "a.py")
    line = commit_check(capsys, "--message-file", str(message))
    assert (line["status"], line["trailer"]) == ("no-receipt", None)
    assert message.read_text() == "fix: one\n"


def test_the_trailer_is_added_to_a_message_file_once(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    message = tmp_path / "message.txt"
    message.write_text("feat: one\n\nBody.\n\nCo-Authored-By: A <a@e>\n")
    write(work, {"a.py": "two\n"})
    tree = verified(capsys)
    git(work, "add", "a.py")
    commit_check(capsys, "--message-file", str(message))
    commit_check(capsys, "--message-file", str(message))
    trailers = git(work, "interpret-trailers", "--parse", str(message))
    assert trailers == f"Co-Authored-By: A <a@e>\nVerify-Receipt: {tree} {PLAN}\n"


def test_no_trailer_is_added_without_a_receipt(work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    message = tmp_path / "message.txt"
    message.write_text("feat: one\n")
    assert work.exists()
    commit_check(capsys, "--message-file", str(message))
    assert message.read_text() == "feat: one\n"


def test_receipts_live_beside_the_rounds_and_the_report_still_reads(
    work: Path, state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(work, {"a.py": "two\n"})
    tree = verified(capsys)
    assert (state / f"{tree}.json").is_file()
    sections = [line for line in report(capsys, "report") if line.get("kind") == "section"]
    assert sections
    assert all(section["unknown"] is None for section in sections)


def test_skip_counts_the_branch_commits_since_the_default_branch(
    work: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin = tmp_path / "origin.git"
    git(work, "init", "-q", "--bare", str(origin))
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "HEAD:main")
    git(work, "fetch", "-q", "origin")
    git(work, "remote", "set-head", "origin", "main")
    # A code commit on the branch, then a documentation-only change on top of it: the change is not docs-only.
    write(work, {"a.py": "two\n"})
    git(work, *COMMIT, "commit", "-qam", "code")
    write(work, {"README.md": "# two\n"})
    begin(capsys)
    line, code = verdict(capsys, "SKIP")
    assert code == {"exit": "1"}
    assert "a.py" in line["detail"]
