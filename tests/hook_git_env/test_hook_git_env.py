"""Tests of hook git-env isolation and core.worktree rejection (ticket #280).

Covers:
1. A planted test in an hk step during a real `git commit` leaves HEAD, the index,
   and the shared git config unchanged and never runs a commit hook recursively.
2. Every hk step and mise task that runs tests or fixtures clears git's local
   repository variables (`git rev-parse --local-env-vars`).
3. `mise run repo:git-config-check` fails when `core.worktree` is set in the
   common git config (naming the value and unset command) and passes otherwise.
4. `hk check` / `hk run pre-commit` fail when `core.worktree` is set in the
   common git config and pass when unset.
5. The six required check names in `.github/rulesets/main.json` and
   `.github/workflows/ci.yml` remain unchanged.

Run: python3 -I tests/hook_git_env/test_hook_git_env.py
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HK_PKL = ROOT / "hk.pkl"
GIT_CONFIG_CHECK = ROOT / ".mise/tasks/repo/git-config-check"
RULESET = ROOT / ".github/rulesets/main.json"
CI_YML = ROOT / ".github/workflows/ci.yml"
EXPECTED_REQUIRED_CHECKS = [
    "artifact-check",
    "gate-linux-arm64",
    "lint",
    "must-fail",
    "pins-validate",
    "resolve",
]
TEST_FIXTURE_HK_STEPS = (
    "pctools-test",
    "pins-cov",
    "suites-cov",
    "agents-cov",
    "artifact-cov",
    "toolchain-cov",
)
SUITE_HK_STEPS = ("repo-check", "workflow-check")
TEST_FIXTURE_TASKS = (
    ".mise/tasks/ci-must-fail",
    ".mise/tasks/artifact/cov",
    ".mise/tasks/toolchain/cov",
    ".mise/tasks/pctools/test",
    ".mise/tasks/pins/cov",
    ".mise/tasks/pins/validate",
    ".mise/tasks/suites/cov",
    ".mise/tasks/agents/cov",
    ".mise/tasks/agents/testtab-check",
    ".mise/tasks/slot/guard-check",
)
CLEAR_ENV_SNIPPET = "unset $(git rev-parse --local-env-vars)"

_LOCAL_GIT_VARS = frozenset(
    subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split()
)
_OUTER_TOOL_VARS = frozenset(
    {
        "HK_FILE",
        "MISE_PROJECT_ROOT",
        "MISE_CONFIG_ROOT",
        "MISE_ORIGINAL_CWD",
        "MISE_TASK_NAME",
        "MISE_ENV",
    }
)


def clean_env(tmp_dir: Path | None = None) -> dict[str, str]:
    """Return an environment stripped of git repo-local and outer mise/hk vars."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _LOCAL_GIT_VARS and k not in _OUTER_TOOL_VARS
    }
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    if tmp_dir is not None:
        env["MISE_TRUSTED_CONFIG_PATHS"] = str(tmp_dir)
        env["MISE_TASK_RUN_AUTO_INSTALL"] = "false"
    return env


def eval_hk_config() -> dict[str, object]:
    """Evaluate the repository's hk.pkl to a Python dict via `pkl eval`."""
    proc = subprocess.run(
        ["pkl", "eval", "-f", "json", str(HK_PKL)],
        cwd=ROOT,
        env=clean_env(),
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(proc.stdout)


def run_git(
    *args: str, cwd: Path, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=check,
        text=True,
    )


def make_worktree_repo(tmp: Path) -> tuple[Path, Path]:
    """Create a throwaway main repo with one commit and one linked worktree."""
    env = clean_env(tmp)
    main = tmp / "main"
    wt = tmp / "wt"
    run_git("init", "-q", str(main), cwd=tmp, env=env)
    run_git("config", "user.name", "Test User", cwd=main, env=env)
    run_git("config", "user.email", "test@example.invalid", cwd=main, env=env)
    run_git("config", "commit.gpgsign", "false", cwd=main, env=env)
    (main / "README.md").write_text("seed\n", encoding="utf-8")
    run_git("add", "README.md", cwd=main, env=env)
    run_git("commit", "-qm", "initial", cwd=main, env=env)
    run_git("worktree", "add", "-q", "-b", "branch-1", str(wt), cwd=main, env=env)
    return main, wt


def write_exec(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def pkl_string(value: str) -> str:
    """Format a Python string as a Pkl custom-delimited string literal."""
    return f'#"{value}"#'


class HookGitEnvTest(unittest.TestCase):
    def test_planted_test_in_hk_step_under_real_commit_leaves_repo_unchanged_and_no_recursion(
        self,
    ) -> None:
        cfg = eval_hk_config()
        steps = cfg["steps"]
        assert isinstance(steps, dict)
        step = steps["toolchain-cov"]
        assert isinstance(step, dict)
        check_cmd = step["check"]
        globs = step["glob"]
        assert isinstance(check_cmd, str)
        assert isinstance(globs, list)

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d).resolve()
            main, wt = make_worktree_repo(tmp)
            env = clean_env(tmp)

            glob_items = ", ".join(pkl_string(str(g)) for g in globs)
            hk_text = (
                'amends "package://github.com/jdx/hk/releases/download/'
                'v2.13.0/hk@2.13.0#/Config.pkl"\n'
                'min_hk_version = "2.13.0"\n'
                "steps {\n"
                '  ["toolchain-cov"] {\n'
                f"    glob = List({glob_items})\n"
                f"    check = {pkl_string(check_cmd)}\n"
                "  }\n"
                "}\n"
            )
            (wt / "hk.pkl").write_text(hk_text, encoding="utf-8")
            run_git("add", "hk.pkl", cwd=wt, env=env)
            run_git("commit", "-qm", "add hk config", cwd=wt, env=env)

            planted_script = (
                f"#!{sys.executable}\n"
                "import os\n"
                "import subprocess\n"
                "from pathlib import Path\n"
                "\n"
                'scratch = Path(os.environ["PLANTED_SCRATCH"])\n'
                "scratch.mkdir(parents=True, exist_ok=True)\n"
                'subprocess.run(["git", "init", "-q", str(scratch)], check=True)\n'
                '(scratch / "planted.txt").write_text("planted\\n", encoding="utf-8")\n'
                "add = subprocess.run(\n"
                '    ["git", "add", "planted.txt"], cwd=scratch, check=False\n'
                ")\n"
                'Path(os.environ["PLANTED_ADD_RC"]).write_text(\n'
                '    str(add.returncode), encoding="utf-8"\n'
                ")\n"
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
                ")\n"
            )
            fake_bin = tmp / "fake-bin"
            write_exec(fake_bin / "mise", planted_script)

            hook_log = tmp / "hook.log"
            post_hk_head = tmp / "post_hk_head"
            post_hk_index = tmp / "post_hk_index"
            post_hk_config = tmp / "post_hk_config"
            common_config = main / ".git/config"
            hook_script = (
                "#!/bin/sh\n"
                "set -eu\n"
                'printf \'invoked pid=%s\\n\' "$$" >> "$HOOK_LOG"\n'
                "count=$(wc -l < \"$HOOK_LOG\" | tr -d ' ')\n"
                'if [ "$count" -gt 2 ]; then\n'
                '  echo "HOOK_RECURSION_ABORT count=$count" >&2\n'
                "  exit 1\n"
                "fi\n"
                "hk run pre-commit --no-progress\n"
                'git rev-parse HEAD > "$POST_HK_HEAD"\n'
                'git ls-files --stage > "$POST_HK_INDEX"\n'
                'cp "$COMMON_CONFIG" "$POST_HK_CONFIG"\n'
            )
            write_exec(main / ".git/hooks/pre-commit", hook_script)

            dummy = wt / "tests/toolchain/dummy.py"
            dummy.parent.mkdir(parents=True, exist_ok=True)
            dummy.write_text("x = 1\n", encoding="utf-8")
            run_git("add", "tests/toolchain/dummy.py", cwd=wt, env=env)

            head_before = run_git("rev-parse", "HEAD", cwd=wt, env=env).stdout.strip()
            index_before = run_git("ls-files", "--stage", cwd=wt, env=env).stdout
            config_before = common_config.read_text(encoding="utf-8")

            scratch = tmp / "scratch"
            add_rc = tmp / "add_rc"
            commit_env = env | {
                "PATH": f"{fake_bin}:{env['PATH']}",
                "PLANTED_SCRATCH": str(scratch),
                "PLANTED_ADD_RC": str(add_rc),
                "HOOK_LOG": str(hook_log),
                "POST_HK_HEAD": str(post_hk_head),
                "POST_HK_INDEX": str(post_hk_index),
                "POST_HK_CONFIG": str(post_hk_config),
                "COMMON_CONFIG": str(common_config),
            }
            commit_proc = run_git(
                "commit", "-m", "real commit", cwd=wt, env=commit_env, check=False
            )

            self.assertEqual(
                commit_proc.returncode,
                0,
                f"commit failed:\n{commit_proc.stdout}\n{commit_proc.stderr}",
            )
            hook_lines = hook_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                len(hook_lines),
                1,
                f"expected pre-commit hook to run once, got {hook_lines}",
            )
            self.assertEqual(common_config.read_text(encoding="utf-8"), config_before)
            self.assertNotIn("worktree", common_config.read_text(encoding="utf-8"))
            self.assertEqual(
                post_hk_head.read_text(encoding="utf-8").strip(), head_before
            )
            self.assertEqual(post_hk_index.read_text(encoding="utf-8"), index_before)
            self.assertEqual(post_hk_config.read_text(encoding="utf-8"), config_before)

            self.assertEqual(
                run_git("rev-parse", "HEAD~1", cwd=wt, env=env).stdout.strip(),
                head_before,
            )
            self.assertEqual(
                run_git("log", "-1", "--format=%s", cwd=wt, env=env).stdout.strip(),
                "real commit",
            )
            wt_files = run_git(
                "ls-tree", "-r", "--name-only", "HEAD", cwd=wt, env=env
            ).stdout.splitlines()
            self.assertIn("tests/toolchain/dummy.py", wt_files)
            self.assertNotIn("planted.txt", wt_files)

            self.assertEqual(add_rc.read_text(encoding="utf-8").strip(), "0")
            self.assertTrue((scratch / ".git").is_dir())
            self.assertEqual(
                run_git(
                    "log", "-1", "--format=%s", cwd=scratch, env=env
                ).stdout.strip(),
                "planted commit",
            )
            scratch_files = run_git(
                "ls-tree", "-r", "--name-only", "HEAD", cwd=scratch, env=env
            ).stdout.splitlines()
            self.assertIn("planted.txt", scratch_files)

    def test_every_test_and_fixture_hk_step_clears_git_local_env_vars(self) -> None:
        cfg = eval_hk_config()
        top_steps = cfg["steps"]
        hooks = cfg["hooks"]
        assert isinstance(top_steps, dict)
        assert isinstance(hooks, dict)
        check_hook = hooks["check"]
        assert isinstance(check_hook, dict)
        check_steps = check_hook["steps"]
        assert isinstance(check_steps, dict)

        for name in TEST_FIXTURE_HK_STEPS:
            for scope, mapping in (
                ("steps", top_steps),
                ("hooks.check.steps", check_steps),
            ):
                self.assertIn(name, mapping, f"missing {name} in {scope}")
                cmd = mapping[name]["check"]
                self.assertIsInstance(cmd, str, f"{scope}.{name}.check is not a str")
                self.assertIn(
                    CLEAR_ENV_SNIPPET,
                    cmd,
                    f"{scope}.{name}.check does not clear git local env vars: {cmd!r}",
                )

        for name in SUITE_HK_STEPS:
            self.assertIn(name, check_steps, f"missing {name} in hooks.check.steps")
            cmd = check_steps[name]["check"]
            self.assertIsInstance(cmd, str)
            self.assertIn(
                CLEAR_ENV_SNIPPET,
                cmd,
                f"hooks.check.steps.{name}.check does not clear git local env vars: {cmd!r}",
            )

        markers = (":test", ":cov", "pytest", "ci-must-fail", "tests/")
        for scope, mapping in (
            ("steps", top_steps),
            ("hooks.check.steps", check_steps),
        ):
            for name, step in mapping.items():
                cmd = step.get("check")
                if isinstance(cmd, str) and any(m in cmd for m in markers):
                    self.assertIn(
                        CLEAR_ENV_SNIPPET,
                        cmd,
                        f"{scope}.{name}.check runs tests/fixtures without clearing git env: {cmd!r}",
                    )

        command_markers = (
            "git -C",
            "git rev-parse --show-toplevel",
            "pytest",
            "python3",
            "uv run",
        )
        for rel in TEST_FIXTURE_TASKS:
            task_path = ROOT / rel
            self.assertTrue(task_path.is_file(), f"missing task {rel}")
            text = task_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            unset_idx = next(
                (i for i, line in enumerate(lines) if CLEAR_ENV_SNIPPET in line),
                None,
            )
            self.assertIsNotNone(
                unset_idx, f"{rel} does not contain `{CLEAR_ENV_SNIPPET}`"
            )
            assert unset_idx is not None
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if any(m in stripped for m in command_markers):
                    self.assertLess(
                        unset_idx,
                        i,
                        f"{rel} runs `{stripped}` at line {i + 1} before clearing git env at line {unset_idx + 1}",
                    )

    def test_git_config_check_task_fails_when_core_worktree_is_set_and_passes_when_unset(
        self,
    ) -> None:
        self.assertTrue(
            GIT_CONFIG_CHECK.is_file(),
            f"missing task script: {GIT_CONFIG_CHECK}",
        )
        self.assertTrue(
            os.access(GIT_CONFIG_CHECK, os.X_OK),
            f"task script is not executable: {GIT_CONFIG_CHECK}",
        )

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d).resolve()
            main, wt = make_worktree_repo(tmp)
            env = clean_env(tmp)

            for root in (main, wt):
                (root / "mise.toml").write_text("# scratch\n", encoding="utf-8")
                task_dst = root / ".mise/tasks/repo/git-config-check"
                task_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(GIT_CONFIG_CHECK, task_dst)

            for label, where in (("main", main), ("wt", wt)):
                ok = subprocess.run(
                    ["mise", "run", "repo:git-config-check"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(
                    ok.returncode,
                    0,
                    f"{label} failed when unset:\n{ok.stdout}\n{ok.stderr}",
                )

            cfg = main / ".git/config"
            run_git(
                "config", "--file", str(cfg), "core.worktree", str(wt), cwd=tmp, env=env
            )

            unset_cmd: list[str] | None = None
            for label, where in (("wt", wt), ("main", main)):
                bad = subprocess.run(
                    ["mise", "run", "repo:git-config-check"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                combined = bad.stdout + bad.stderr
                self.assertNotEqual(
                    bad.returncode,
                    0,
                    f"{label} unexpectedly passed with core.worktree set",
                )
                self.assertIn("core.worktree", combined)
                self.assertIn(str(wt), combined)
                self.assertIn("--unset-all core.worktree", combined)
                for line in bad.stderr.splitlines():
                    stripped = line.strip()
                    if (
                        stripped.startswith("git config --file")
                        and "--unset-all core.worktree" in stripped
                    ):
                        unset_cmd = shlex.split(stripped)
                        break

            self.assertIsNotNone(unset_cmd, "did not find unset command in stderr")
            assert unset_cmd is not None
            fix = subprocess.run(
                unset_cmd, cwd=tmp, env=env, capture_output=True, check=False, text=True
            )
            self.assertEqual(fix.returncode, 0, fix.stdout + fix.stderr)

            for label, where in (("wt", wt), ("main", main)):
                again = subprocess.run(
                    ["mise", "run", "repo:git-config-check"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(
                    again.returncode,
                    0,
                    f"{label} failed after unset:\n{again.stdout}\n{again.stderr}",
                )

            run_git("config", "--file", str(cfg), "core.worktree", "", cwd=tmp, env=env)
            for label, where in (("main", main), ("wt", wt)):
                empty_bad = subprocess.run(
                    ["mise", "run", "repo:git-config-check"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                combined = empty_bad.stdout + empty_bad.stderr
                self.assertNotEqual(
                    empty_bad.returncode,
                    0,
                    f"{label} unexpectedly passed with empty core.worktree",
                )
                self.assertIn("core.worktree", combined)
                self.assertIn("--unset-all core.worktree", combined)

    def test_hk_run_fails_when_core_worktree_is_set_and_passes_when_unset(
        self,
    ) -> None:
        self.assertTrue(
            GIT_CONFIG_CHECK.is_file(),
            f"missing task script: {GIT_CONFIG_CHECK}",
        )
        cfg = eval_hk_config()
        for scope, mapping in (
            ("steps", cfg["steps"]),
            ("hooks.check.steps", cfg["hooks"]["check"]["steps"]),
        ):
            assert isinstance(mapping, dict)
            self.assertIn(
                "git-config-check", mapping, f"missing git-config-check in {scope}"
            )
            step = mapping["git-config-check"]
            assert isinstance(step, dict)
            self.assertIsNone(
                step.get("glob"), f"{scope}.git-config-check must have no glob"
            )
            self.assertIsInstance(step.get("check"), str)

        check_cmd = cfg["steps"]["git-config-check"]["check"]
        assert isinstance(check_cmd, str)

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d).resolve()
            env = clean_env(tmp)
            main = tmp / "main"
            wt = tmp / "wt"

            run_git("init", "-q", str(main), cwd=tmp, env=env)
            run_git("config", "user.name", "Test User", cwd=main, env=env)
            run_git("config", "user.email", "test@example.invalid", cwd=main, env=env)
            run_git("config", "commit.gpgsign", "false", cwd=main, env=env)

            (main / "mise.toml").write_text("# scratch\n", encoding="utf-8")
            task_dst = main / ".mise/tasks/repo/git-config-check"
            task_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(GIT_CONFIG_CHECK, task_dst)
            hk_text = (
                'amends "package://github.com/jdx/hk/releases/download/'
                'v2.13.0/hk@2.13.0#/Config.pkl"\n'
                'min_hk_version = "2.13.0"\n'
                "steps {\n"
                '  ["git-config-check"] {\n'
                f"    check = {pkl_string(check_cmd)}\n"
                "  }\n"
                "}\n"
            )
            (main / "hk.pkl").write_text(hk_text, encoding="utf-8")
            run_git(
                "add",
                "mise.toml",
                ".mise/tasks/repo/git-config-check",
                "hk.pkl",
                cwd=main,
                env=env,
            )
            run_git("commit", "-qm", "initial", cwd=main, env=env)
            run_git(
                "worktree", "add", "-q", "-b", "branch-1", str(wt), cwd=main, env=env
            )

            for label, where in (("wt", wt), ("main", main)):
                ok = subprocess.run(
                    ["hk", "check", "--no-progress"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(
                    ok.returncode,
                    0,
                    f"{label} hk check failed when unset:\n{ok.stdout}\n{ok.stderr}",
                )

            git_cfg = main / ".git/config"
            run_git(
                "config",
                "--file",
                str(git_cfg),
                "core.worktree",
                str(wt),
                cwd=tmp,
                env=env,
            )

            for label, where in (("wt", wt), ("main", main)):
                bad = subprocess.run(
                    ["hk", "check", "--no-progress"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                combined = bad.stdout + bad.stderr
                self.assertNotEqual(
                    bad.returncode,
                    0,
                    f"{label} hk check unexpectedly passed with core.worktree set",
                )
                self.assertIn("core.worktree", combined)
                self.assertIn(str(wt), combined)
                self.assertIn("--unset-all core.worktree", combined)

            write_exec(
                main / ".git/hooks/pre-commit",
                "#!/bin/sh\nset -eu\nexec hk run pre-commit --no-progress\n",
            )
            (wt / "note.txt").write_text("hello\n", encoding="utf-8")
            run_git("add", "note.txt", cwd=wt, env=env)
            blocked = run_git("commit", "-m", "blocked", cwd=wt, env=env, check=False)
            blocked_out = blocked.stdout + blocked.stderr
            self.assertNotEqual(
                blocked.returncode,
                0,
                "git commit unexpectedly succeeded with core.worktree set",
            )
            self.assertIn("core.worktree", blocked_out)
            self.assertIn(str(wt), blocked_out)

            run_git(
                "config",
                "--file",
                str(git_cfg),
                "--unset-all",
                "core.worktree",
                cwd=tmp,
                env=env,
            )
            for label, where in (("wt", wt), ("main", main)):
                again = subprocess.run(
                    ["hk", "check", "--no-progress"],
                    cwd=where,
                    env=env,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(
                    again.returncode,
                    0,
                    f"{label} hk check failed after unset:\n{again.stdout}\n{again.stderr}",
                )

            unblocked = run_git(
                "commit", "-m", "unblocked", cwd=wt, env=env, check=False
            )
            self.assertEqual(
                unblocked.returncode,
                0,
                f"git commit failed after unset:\n{unblocked.stdout}\n{unblocked.stderr}",
            )

    def test_six_required_check_names_are_unchanged(self) -> None:
        ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
        contexts = [
            check["context"]
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
            for check in rule["parameters"]["required_status_checks"]
        ]
        self.assertEqual(sorted(contexts), EXPECTED_REQUIRED_CHECKS)

        ci_text = CI_YML.read_text(encoding="utf-8")
        for name in EXPECTED_REQUIRED_CHECKS:
            self.assertRegex(
                ci_text,
                re.compile(rf"^  {re.escape(name)}:\s*$", re.MULTILINE),
                f"missing required job {name} in ci.yml",
            )


if __name__ == "__main__":
    unittest.main()
