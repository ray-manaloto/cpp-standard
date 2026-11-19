"""Tests of the `toolchain:smoke` task (.mise/tasks/toolchain/smoke, ticket #271): the smoke step
runs only the registered `standin_test` and fails when no test ran (--no-tests=error). Uses a
stand-in compiler and cmake driver (and a stdlib ctest shim only when ctest is absent from PATH).
Run: python3 -I tests/toolchain/test_smoke.py
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / ".mise/tasks/toolchain/smoke"
TESTS_CMAKE = ROOT / "tests/CMakeLists.txt"

CMAKE_SHIM = """import os, sys
from pathlib import Path

args = sys.argv[1:]
if "--build" in args:
    sys.exit(0)
if "-B" in args:
    build = Path(args[args.index("-B") + 1])
    build.mkdir(parents=True, exist_ok=True)
    (build / "CTestTestfile.cmake").write_text(
        os.environ["SMOKE_CTEST_FILE"], encoding="utf-8"
    )
"""

CTEST_SHIM = """import re, shlex, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
test_dir = Path(".")
regex = None
no_tests = "ignore"
i = 0
while i < len(args):
    a = args[i]
    if a == "--test-dir":
        test_dir = Path(args[i + 1])
        i += 2
    elif a in ("-R", "--tests-regex"):
        regex = re.compile(args[i + 1])
        i += 2
    elif a.startswith("--no-tests="):
        no_tests = a.split("=", 1)[1]
        i += 1
    else:
        i += 1

tests = []
for line in (test_dir / "CTestTestfile.cmake").read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if s.startswith("add_test(") and s.endswith(")"):
        parts = shlex.split(s[len("add_test(") : -1])
        if parts:
            tests.append((parts[0], parts[1:]))

selected = [(n, cmd) for n, cmd in tests if regex is None or regex.search(n)]
if not selected:
    print("No tests were found!!!")
    sys.exit(8 if no_tests == "error" else 0)

failed = 0
for name, cmd in selected:
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        print(f"FAIL: {name}")
        failed += 1
sys.exit(1 if failed else 0)
"""


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class SmokeStep(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.prefix = self.tmp / "toolchain"
        self.fake_bin = self.tmp / "bin"

        _write_exec(
            self.prefix / "bin/clang++",
            "#!/bin/sh\n"
            'if [ "${1:-}" = "-print-target-triple" ]; then\n'
            "  echo aarch64-unknown-linux-gnu\n"
            "else\n"
            "  echo clang version 21.0.0-standin\n"
            "fi\n",
        )
        cmake_py = self.tmp / "cmake_shim.py"
        cmake_py.write_text(CMAKE_SHIM, encoding="utf-8")
        _write_exec(
            self.fake_bin / "cmake",
            f'#!/bin/sh\nexec "{sys.executable}" -I "{cmake_py}" "$@"\n',
        )
        if shutil.which("ctest") is None:
            ctest_py = self.tmp / "ctest_shim.py"
            ctest_py.write_text(CTEST_SHIM, encoding="utf-8")
            _write_exec(
                self.fake_bin / "ctest",
                f'#!/bin/sh\nexec "{sys.executable}" -I "{ctest_py}" "$@"\n',
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_smoke(self, ctest_file: str) -> subprocess.CompletedProcess[str]:
        env = os.environ | {
            "PATH": f"{self.fake_bin}:{os.environ['PATH']}",
            "MISE_PROJECT_ROOT": str(self.project),
            "usage_prefix": str(self.prefix),
            "SMOKE_CTEST_FILE": ctest_file,
        }
        return subprocess.run(
            ["bash", str(SMOKE)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cmake_registers_standin_test(self) -> None:
        m = re.search(r"add_test\(\s*NAME\s+(\S+)", TESTS_CMAKE.read_text())
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group(1), "standin_test")

    def test_fails_when_no_test_is_registered(self) -> None:
        r = self.run_smoke("# no tests\n")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("PASS:", r.stdout)

    def test_fails_when_only_another_test_is_registered(self) -> None:
        r = self.run_smoke(
            'add_test(other_test "/bin/sh" "-c" "exit 0")\n'
            'add_test(standin_test_extra "/bin/sh" "-c" "exit 0")\n'
        )
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("PASS:", r.stdout)

    def test_runs_only_the_registered_standin_test(self) -> None:
        r = self.run_smoke(
            'add_test(standin_test "/bin/sh" "-c" "exit 0")\n'
            'add_test(unrelated_failing_test "/bin/sh" "-c" "exit 1")\n'
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS:", r.stdout)


if __name__ == "__main__":
    unittest.main()
