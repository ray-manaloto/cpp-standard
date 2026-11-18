"""Every test runs outside the repository a git hook exported; the offline tests first check uv's cache."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from repotools.tools_install import TOOLS
from tests import drop_repo_git_env

REPO = Path(__file__).resolve().parents[3]
WARM = "run the warm step `mise run uv:cache-warm`"
# uv 0.13.9's two wordings: a resolution that finds no cached index entry, and a download of a locked file.
CACHE_MISS = re.compile(
    r"Because (\S+) was not found in the cache|Failed to download `([^`]+)`[^\n]*\n[^\n]*wasn't found in the cache"
)


@pytest.fixture(scope="session")
def uv_cache(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Fail every offline test with one line when uv's cache lacks what they install (#184): a new uv can rename its
    cache buckets, and the installs inside the tests then end in a bare SystemExit. The same offline sync and tool
    installs the tests make, once per worker, into scratch folders."""
    scratch = tmp_path_factory.mktemp("uv-cache")
    env = {
        **os.environ,
        "UV_OFFLINE": "1",
        "UV_PROJECT_ENVIRONMENT": str(scratch / "venv"),
        "UV_TOOL_DIR": str(scratch / "tools"),
        "UV_TOOL_BIN_DIR": str(scratch / "bin"),
    }
    env.pop("VIRTUAL_ENV", None)
    commands = [["uv", "sync", "--locked", "--project", "python/repo"]]
    commands += [["uv", "tool", "install", f"./{source}"] for source in TOOLS.values()]
    for command in commands:
        done = subprocess.run(command, cwd=REPO, env=env, capture_output=True, check=False, text=True)
        if done.returncode == 0:
            continue
        if missing := CACHE_MISS.search(done.stderr):
            pytest.fail(f"uv cache missing; {WARM}: {missing[1] or missing[2]} is not in uv's cache", pytrace=False)
        lines = done.stderr.splitlines()
        first = next((line for line in lines if line.startswith("error:")), f"exit {done.returncode}")
        pytest.fail(f"{' '.join(command)} failed offline: {first}; if uv's cache is missing, {WARM}", pytrace=False)


@pytest.fixture(autouse=True)
def no_repo_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts outside any repository a hook exported; see drop_repo_git_env."""
    drop_repo_git_env(monkeypatch)
