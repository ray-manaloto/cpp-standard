"""Tests of the `ci-must-fail` runner (.mise/tasks/ci-must-fail, ticket #130): a fixture that goes
green fails the run, as do an unlisted fixture, a listed one with no `run` and an empty list. The
real toolchain fixture is planted green with MUST_FAIL_PLANT=accept, which needs neither gh nor the
network. Run: python3 -I tests/must_fail/test_ci_must_fail.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / ".mise/tasks/ci-must-fail"
# Under a git hook GIT_DIR and GIT_WORK_TREE name the outer repository: every git call and every
# fixture here runs without them, or a test commit would land in the real repository.
_REPO_VARS = subprocess.run(
    ["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True
).stdout.split()
CLEAN_ENV = {k: v for k, v in os.environ.items() if k not in _REPO_VARS}
_LOCAL_GIT_VARS = frozenset(
    subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split()
)


def clean_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _LOCAL_GIT_VARS}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(TASK)],
        env=CLEAN_ENV | {"MISE_PROJECT_ROOT": str(ROOT)} | env,
        capture_output=True,
        text=True,
        check=False,
    )


class Runner(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fixture(self, name: str, exit_code: int | None, listed: bool = True) -> None:
        d = self.dir / name
        d.mkdir()
        if exit_code is not None:
            (d / "run").write_text(f"#!/bin/sh\nexit {exit_code}\n")
            (d / "run").chmod(0o755)
        if listed:
            with open(self.dir / "expected.toml", "a") as f:
                f.write(f'[fixture.{name}]\ncheck = "some:check"\n')

    def local(self) -> subprocess.CompletedProcess[str]:
        (self.dir / "expected.toml").touch()
        return run({"CPPSTD_MUST_FAIL_DIR": str(self.dir)})

    def test_refused_fixtures_pass(self) -> None:
        self.fixture("a", 0)
        self.fixture("b", 0)
        r = self.local()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PASS: every must-fail fixture was refused", r.stdout)

    def test_a_green_fixture_fails_the_run(self) -> None:
        self.fixture("a", 0)
        self.fixture("b", 1)
        r = self.local()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("b went green", r.stderr)

    def test_an_unlisted_fixture_fails_the_run(self) -> None:
        self.fixture("a", 0)
        self.fixture("stray", 0, listed=False)
        r = self.local()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("stray is not listed", r.stderr)

    def test_a_listed_fixture_without_run_fails(self) -> None:
        self.fixture("a", None)
        r = self.local()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("has no executable run", r.stderr)

    def test_an_empty_list_fails(self) -> None:
        r = self.local()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lists no fixture", r.stderr)

    def test_the_toolchain_fixture_planted_green_fails_the_run(self) -> None:
        r = run({"MUST_FAIL_PLANT": "accept"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("toolchain-unattested went green", r.stderr)
        self.assertIn("installed 'refused'", r.stderr)
        # The wrong-hash fixture runs in the same planted run; it is green too, or could not run.
        self.assertRegex(r.stderr, r"toolchain-wrong-hash (went green|could not run)")

    def test_a_fixture_that_moves_head_fails_the_run(self) -> None:
        repo = self.dir / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=CLEAN_ENV)
        git = [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
        ]
        subprocess.run(
            [*git, "commit", "-q", "--allow-empty", "-m", "one"],
            check=True,
            env=CLEAN_ENV,
        )
        d = self.dir / "fx"
        d.mkdir()
        (d / "run").write_text(
            f"#!/bin/sh\n{' '.join(git)} commit -q --allow-empty -m two\nexit 0\n"
        )
        (d / "run").chmod(0o755)
        (self.dir / "expected.toml").write_text('[fixture.fx]\ncheck = "some:check"\n')
        r = run({"CPPSTD_MUST_FAIL_DIR": str(self.dir), "MISE_PROJECT_ROOT": str(repo)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("fx changed the repository", r.stderr)

    def test_no_expected_toml_fails(self) -> None:
        self.fixture("a", 0, listed=False)
        r = run({"CPPSTD_MUST_FAIL_DIR": str(self.dir)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot read", r.stderr)

    def test_a_row_without_check_fails(self) -> None:
        self.fixture("a", 0, listed=False)
        (self.dir / "expected.toml").write_text('[fixture.a]\nwhat = "no check"\n')
        r = run({"CPPSTD_MUST_FAIL_DIR": str(self.dir)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("names no check", r.stderr)

    def test_a_fixture_that_could_not_run_is_not_called_green(self) -> None:
        self.fixture("a", 3)
        r = self.local()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("a could not run", r.stderr)
        self.assertNotIn("went green", r.stderr)

    def test_a_fixture_name_is_matched_exactly(self) -> None:
        # "a.b" must not match a listed "axb" (a regex dot would).
        self.fixture("axb", 0)
        self.fixture("a.b", 0, listed=False)
        r = self.local()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("a.b is not listed", r.stderr)

    def test_fixture_does_not_inherit_repo_git_env(self) -> None:
        base_env = clean_git_env()
        repos = self.dir / "repos"
        main = repos / "main"
        wt = repos / "wt"
        repos.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(main)], cwd=repos, env=base_env, check=True
        )
        for key, val in (
            ("user.name", "Test User"),
            ("user.email", "test@example.invalid"),
            ("commit.gpgsign", "false"),
        ):
            subprocess.run(
                ["git", "config", key, val], cwd=main, env=base_env, check=True
            )
        (main / "README.md").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=main, env=base_env, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "initial"], cwd=main, env=base_env, check=True
        )
        subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "branch-1", str(wt)],
            cwd=main,
            env=base_env,
            check=True,
        )

        hook_log = self.dir / "hook.log"
        hook = main / ".git/hooks/pre-commit"
        hook.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            f'printf "invoked\\n" >> "{hook_log}"\n'
            f'count=$(wc -l < "{hook_log}" | tr -d " ")\n'
            'if [ "$count" -gt 2 ]; then\n'
            "  exit 1\n"
            "fi\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        fixtures_dir = self.dir / "fixtures"
        planted = fixtures_dir / "planted"
        planted.mkdir(parents=True)
        scratch = self.dir / "scratch"
        (fixtures_dir / "expected.toml").write_text(
            '[fixture.planted]\ncheck = "some:check"\n', encoding="utf-8"
        )
        run_script = planted / "run"
        run_script.write_text(
            f"#!{sys.executable}\n"
            "import subprocess\n"
            "from pathlib import Path\n"
            f"scratch = Path({str(scratch)!r})\n"
            "scratch.mkdir(parents=True, exist_ok=True)\n"
            'subprocess.run(["git", "init", "-q", str(scratch)], check=True)\n'
            '(scratch / "planted.txt").write_text("planted\\n", encoding="utf-8")\n'
            'subprocess.run(["git", "add", "planted.txt"], cwd=scratch, check=True)\n'
            "subprocess.run(\n"
            "    [\n"
            '        "git",\n'
            '        "-c",\n'
            '        "user.name=Planted",\n'
            '        "-c",\n'
            '        "user.email=planted@example.invalid",\n'
            '        "-c",\n'
            '        "commit.gpgsign=false",\n'
            '        "commit",\n'
            '        "--allow-empty",\n'
            '        "-qm",\n'
            '        "planted commit",\n'
            "    ],\n"
            "    cwd=scratch,\n"
            "    check=True,\n"
            ")\n",
            encoding="utf-8",
        )
        run_script.chmod(0o755)

        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt,
            env=base_env,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        index_before = subprocess.run(
            ["git", "ls-files", "--stage"],
            cwd=wt,
            env=base_env,
            capture_output=True,
            check=True,
            text=True,
        ).stdout
        config_before = (main / ".git/config").read_text(encoding="utf-8")

        poisoned_env = base_env | {
            "MISE_PROJECT_ROOT": str(ROOT),
            "CPPSTD_MUST_FAIL_DIR": str(fixtures_dir),
            "GIT_DIR": str(main / ".git/worktrees/wt"),
            "GIT_WORK_TREE": str(wt),
            "GIT_INDEX_FILE": str(main / ".git/worktrees/wt/index"),
            "GIT_PREFIX": "",
        }
        r = subprocess.run(
            ["bash", str(TASK)],
            env=poisoned_env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(hook_log.exists(), "throwaway pre-commit hook fired")
        self.assertEqual(
            (main / ".git/config").read_text(encoding="utf-8"), config_before
        )
        self.assertNotIn("worktree", (main / ".git/config").read_text(encoding="utf-8"))
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=wt,
            env=base_env,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        index_after = subprocess.run(
            ["git", "ls-files", "--stage"],
            cwd=wt,
            env=base_env,
            capture_output=True,
            check=True,
            text=True,
        ).stdout
        self.assertEqual(head_after, head_before)
        self.assertEqual(index_after, index_before)
        self.assertTrue((scratch / ".git").is_dir())
        scratch_msg = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=scratch,
            env=base_env,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(scratch_msg, "planted commit")
        scratch_files = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=scratch,
            env=base_env,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.splitlines()
        self.assertIn("planted.txt", scratch_files)


if __name__ == "__main__":
    unittest.main()
