"""repotools shell-apply and shell-rollback in-process, with real git, mise and zsh in a stand-in checkout."""

# python/tests/test_shell_apply.py runs the same commands through `mise run` in a copy of this checkout.

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from repotools import shell
from repotools.cli import main
from tests import clean_git_env

DEPLOYED = (
    ".zshenv",
    ".config/zsh/.zprofile",
    ".config/zsh/.zshrc",
    ".config/zsh/.zshrc.d/10-zsh.zsh",
    ".config/zsh/.zshrc.d/90-mise.zsh",
    ".config/zsh/path.zsh",
)
PATHS = ".zshenv .zprofile .zshrc .zprofile.d .zshrc.d .config/zsh"
ENTRY = '"~/{0}" = {{ source = "unix/home/{0}", mode = "symlink" }}\n'
DOTFILES = "[dotfiles]\n" + "".join(ENTRY.format(name) for name in DEPLOYED)
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout at root/repo with the six [dotfiles] entries, and a live home at root/home."""
    for name in DEPLOYED:
        (tmp_path / "repo/unix/home" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "repo/unix/home" / name).write_text(f"# new {name}\n")
    (tmp_path / "repo/unix/home/.zshenv").write_text(
        'export ZDOTDIR="$HOME/.config/zsh"\n'
    )  # zsh reads the rest from there
    (tmp_path / "repo/mise.toml").write_text(DOTFILES)
    (tmp_path / "home/.zshrc.d").mkdir(parents=True)
    (tmp_path / "home/.zshrc").write_text("# live .zshrc\n")
    (tmp_path / "home/.zshrc.d/70-mine.zsh").write_text("# live drop-in\n")
    (tmp_path / "home/.zshrc.d/60-agent-tools.zsh").symlink_to("/nowhere/60-agent-tools.zsh")
    clean_git_env(monkeypatch)
    for name, value in {
        "HOME": tmp_path / "home",
        "XDG_CONFIG_HOME": tmp_path / "config",
        "XDG_DATA_HOME": tmp_path / "data",
        "XDG_STATE_HOME": tmp_path / "state",
        "XDG_CACHE_HOME": tmp_path / "cache",
        "MISE_TRUSTED_CONFIG_PATHS": f"{tmp_path / 'repo'}:{tmp_path / 'worktree'}",
        "MISE_CEILING_PATHS": tmp_path,
        "MISE_AUTO_INSTALL": "0",
        "SHELL_BACKUP_PATHS": PATHS,
    }.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.chdir(tmp_path / "repo")
    return tmp_path


def backups(root: Path) -> Path:
    return root / "state/dotfiles/shell-backup"


def snapshot(home: Path) -> dict[str, tuple[int, bytes]]:
    """Mode and bytes of each file or link under the backed-up paths; a link holds its target."""
    tops = [home / name for name in PATHS.split()]
    paths = [path for top in tops for path in [top, *(top.rglob("*") if top.is_dir() else [])]]
    return {
        str(path.relative_to(home)): (0, os.fsencode(path.readlink()))
        if path.is_symlink()
        else (stat.S_IMODE(path.stat().st_mode), path.read_bytes())
        for path in paths
        if path.is_symlink() or path.is_file()
    }


def succeeds(command: str) -> bool:
    try:
        main([command])
    except SystemExit:
        return False
    return True


def refused(root: Path, command: str = "shell-apply") -> None:
    live = snapshot(root / "home")
    assert not succeeds(command)
    assert snapshot(root / "home") == live
    assert not backups(root).exists() or not list(backups(root).iterdir())


def test_apply_links_backs_up_and_rollback_restores(root: Path) -> None:
    (root / "home/.zsh_history").write_bytes(b": 1:0;echo before\n")
    live = snapshot(root / "home")
    assert succeeds("shell-apply")
    for name in DEPLOYED:
        assert (root / "home" / name).resolve() == root / "repo/unix/home" / name
    assert [path.name for path in backups(root).iterdir()] == ["pre-apply"]
    assert snapshot(backups(root) / "pre-apply") == live
    assert stat.S_IMODE((backups(root) / "pre-apply").stat().st_mode) == 0o700
    history = root / "state/zsh/history"
    assert history.read_bytes() == b": 1:0;echo before\n"
    assert stat.S_IMODE(history.stat().st_mode) == 0o600
    assert (root / "cache/zsh/completions/_mise").is_file()
    assert succeeds("shell-apply")  # nothing left to link: no second backup
    assert [path.name for path in backups(root).iterdir()] == ["pre-apply"]
    history.write_bytes(b"newer\n")
    assert succeeds("shell-rollback")
    assert snapshot(root / "home") == live
    assert history.read_bytes() == b"newer\n"
    assert not (backups(root) / "pre-apply").exists()
    assert len(list(backups(root).glob("replaced-*"))) == 2  # what was live, and the used pre-apply


def test_a_later_apply_keeps_the_changed_live_files_aside(root: Path) -> None:
    assert succeeds("shell-apply")
    first = snapshot(backups(root) / "pre-apply")
    (root / "home/.config/zsh/.zshrc").unlink()
    (root / "home/.config/zsh/.zshrc").write_text("# installer\n")
    assert succeeds("shell-apply")
    assert snapshot(backups(root) / "pre-apply") == first
    [replaced] = backups(root).glob("replaced-*")
    assert (replaced / ".config/zsh/.zshrc").read_text() == "# installer\n"
    assert not (root / "state/zsh/history").exists()  # there was no history to keep


def test_needs_link_reads_the_exit_status_not_stdout(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status: list[int] = [0]

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, status[0], stdout="would link x\n", stderr="")

    monkeypatch.setattr(shell.subprocess, "run", run)
    for rc, applied in ((0, False), (1, True)):
        status[0] = rc
        assert shell.needs_link() is applied  # stdout is non-empty either way; only the exit status decides
    assert not backups(root).exists()  # deciding makes no backup by itself
    status[0] = 2
    with pytest.raises(ValueError, match="mise dot status exited 2"):
        shell.needs_link()


def test_an_apply_with_everything_applied_makes_no_backup_even_when_dry_run_prints(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = shutil.which("mise")
    assert real  # the stand-in execs it for everything but a dry run
    assert succeeds("shell-apply")
    live = snapshot(root / "home")
    assert [path.name for path in backups(root).iterdir()] == ["pre-apply"]
    (root / "bin").mkdir()
    stand_in = root / "bin" / "mise"
    # mise prints dry-run output even when everything is applied; the old bug took that stdout as work to link.
    stand_in.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = dot ] && [ "$2" = apply ] && [ "$3" = --force ] && [ "$4" = --yes ]'
        ' && [ "$5" = --dry-run ]; then\n'
        "  echo 'would link everything'\n"
        "  exit 0\n"
        "fi\n"
        f'exec {real} "$@"\n',
    )
    stand_in.chmod(0o755)
    monkeypatch.setenv("PATH", f"{root / 'bin'}:{os.environ['PATH']}")
    assert succeeds("shell-apply")
    assert [path.name for path in backups(root).iterdir()] == ["pre-apply"]
    assert not list(backups(root).glob("replaced-*"))
    assert snapshot(root / "home") == live


def test_one_missing_target_links_only_what_is_missing_and_backs_up(root: Path) -> None:
    assert succeeds("shell-apply")
    live = snapshot(root / "home")
    (root / "home/.config/zsh/path.zsh").unlink()
    assert succeeds("shell-apply")
    assert (root / "home/.config/zsh/path.zsh").resolve() == root / "repo/unix/home/.config/zsh/path.zsh"
    assert snapshot(root / "home") == live  # every other link stayed as the first apply left it
    [replaced] = backups(root).glob("replaced-*")
    # The backup holds the live state of that run: the same home, minus the link that had gone missing.
    assert snapshot(replaced) == {name: got for name, got in live.items() if name != ".config/zsh/path.zsh"}


def test_a_task_run_without_its_paths_refuses(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHELL_BACKUP_PATHS")
    refused(root)
    refused(root, "shell-rollback")


def test_a_linked_worktree_refuses(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run([*GIT, "init", "-q"], check=True)
    subprocess.run([*GIT, "add", "."], check=True)
    subprocess.run([*GIT, "commit", "-qm", "stand-in"], check=True)
    subprocess.run([*GIT, "worktree", "add", "-q", str(root / "worktree")], check=True)
    monkeypatch.chdir(root / "worktree")
    refused(root)


def test_rollback_without_a_backup_refuses(root: Path) -> None:
    refused(root, "shell-rollback")


def test_a_shell_that_prints_at_startup_refuses(root: Path) -> None:
    (root / "repo/unix/home/.config/zsh/.zshrc").write_text("print noisy\n")
    refused(root)


def test_a_live_file_that_changes_during_the_run_refuses(root: Path) -> None:
    # The checked shell's startup writes to the live .zshrc, between the two copies of it.
    (root / "repo/unix/home/.config/zsh/.zshrc").write_text(f"print -n '# more' >> {root / 'home/.zshrc'}\n")
    before = (root / "home/.zshrc").read_bytes()
    assert not succeeds("shell-apply")
    assert (root / "home/.zshrc").read_bytes().startswith(before)
    assert not (root / "home/.zshenv").exists()
    assert not list(backups(root).iterdir())


def test_apply_drops_the_old_links_into_this_checkout_and_keeps_everything_else(root: Path) -> None:
    home, repo = root / "home", root / "repo"
    for name in (".zprofile", ".zshrc.d/10-zsh.zsh", ".zshrc.d/90-mise.zsh", ".zshrc.d/60-agent-tools.zsh"):
        (repo / "unix/home" / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / "unix/home" / name).write_text(f"# old {name}\n")
    (home / ".zshrc").unlink()
    (home / ".zshrc").symlink_to(repo / "unix/home/.config/zsh/.zshrc")
    (home / ".zprofile").symlink_to(repo / "unix/home/.zprofile")
    (home / ".zshrc.d/60-agent-tools.zsh").unlink()
    for name in ("10-zsh.zsh", "90-mise.zsh", "60-agent-tools.zsh"):
        (home / ".zshrc.d" / name).symlink_to(repo / "unix/home/.zshrc.d" / name)
    elsewhere = root / "elsewhere.zsh"
    elsewhere.write_text("# not ours\n")
    (home / ".zshrc.d/80-elsewhere.zsh").symlink_to(elsewhere)
    assert succeeds("shell-apply")
    assert not os.path.lexists(home / ".zprofile")
    assert not os.path.lexists(home / ".zshrc")
    assert sorted(path.name for path in (home / ".zshrc.d").iterdir()) == ["70-mine.zsh", "80-elsewhere.zsh"]
    assert (home / ".zshrc.d/70-mine.zsh").read_text() == "# live drop-in\n"
    assert (home / ".zshrc.d/80-elsewhere.zsh").readlink() == elsewhere
    # The new layout is linked, and a rollback puts the old links back.
    assert (home / ".config/zsh/.zshrc").resolve() == repo / "unix/home/.config/zsh/.zshrc"
    assert succeeds("shell-rollback")
    assert (home / ".zprofile").readlink() == repo / "unix/home/.zprofile"
    assert (home / ".zshrc.d/10-zsh.zsh").is_symlink()


def test_apply_removes_the_old_folder_once_only_our_links_were_in_it(root: Path) -> None:
    home, repo = root / "home", root / "repo"
    (home / ".zshrc.d/70-mine.zsh").unlink()
    (home / ".zshrc.d/60-agent-tools.zsh").unlink()
    (home / ".zshrc.d/10-zsh.zsh").symlink_to(repo / "unix/home/.zshrc.d/10-zsh.zsh")
    (home / ".zshrc").unlink()  # a real file stays; see the next test
    assert succeeds("shell-apply")
    assert not (home / ".zshrc.d").exists()


def test_apply_never_deletes_a_real_file_or_a_link_elsewhere(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = root / "home"
    (home / ".zprofile").write_text("# real profile\n")
    (home / ".zshrc").unlink()
    (home / ".zshrc").symlink_to(root / "other-checkout/unix/home/.zshrc")
    assert succeeds("shell-apply")
    assert (home / ".zprofile").read_text() == "# real profile\n"
    assert (home / ".zshrc").readlink() == root / "other-checkout/unix/home/.zshrc"
    # The real drop-in is named, since zsh no longer loads it.
    assert "70-mine.zsh" in capsys.readouterr().err
    assert (home / ".zshrc.d/70-mine.zsh").read_text() == "# live drop-in\n"


def test_apply_removes_an_old_folder_link_into_this_checkout(root: Path) -> None:
    home, repo = root / "home", root / "repo"
    shutil.rmtree(home / ".zshrc.d")
    (repo / "unix/home/.zshrc.d").mkdir(parents=True)
    (home / ".zshrc.d").symlink_to(repo / "unix/home/.zshrc.d")
    assert succeeds("shell-apply")
    assert not (home / ".zshrc.d").is_symlink()
    assert (repo / "unix/home/.zshrc.d").is_dir()
