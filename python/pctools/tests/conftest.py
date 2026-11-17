"""The fixture every tests/test_pc_*.py shares: pc-doctor's ssh, stood in."""

import sys
from pathlib import Path

import pytest


@pytest.fixture
def ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """pc-doctor's ssh: the stand-in's folder (tests/stand_in.py), ahead of the real ssh on PATH."""
    folder = tmp_path / "stand-in"
    folder.mkdir()
    (folder / "ssh").symlink_to(Path(__file__).with_name("stand_in.py"))
    monkeypatch.setenv("PATH", f"{folder}:{Path(sys.executable).parent}:/usr/bin:/bin")
    monkeypatch.setenv("STAND_IN", str(folder))
    monkeypatch.delenv("PC_DOCTOR_TIMEOUT", raising=False)
    return folder
