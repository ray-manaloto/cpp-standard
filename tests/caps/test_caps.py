"""Tests of the capability comparison (python/caps/caps.py check, D42): a planted
disagreement between a probe's result and the capability lock fails naming the
capability, and a probe that matches the lock passes. Offline: the probe file and
the lock are temp files, never a live configure (D42). Run:
python3 -I tests/caps/test_caps.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/caps"))

import caps

# The lock's linux-arm64 entries, as committed (the Valgrind contradiction #134
# fixes: the shared image installs Valgrind, the lock keeps it gcc16-only, D37).
LOCK = {
    "schema": 1,
    "environments": {
        "linux-arm64": {
            "presets": {
                "clang23-coverage": {
                    "capabilities": {
                        "asan": True,
                        "ubsan": True,
                        "tsan": True,
                        "valgrind": False,
                    }
                },
                "gcc16-coverage": {
                    "capabilities": {
                        "asan": True,
                        "ubsan": True,
                        "tsan": True,
                        "valgrind": True,
                    }
                },
            }
        }
    },
}


def probe(compiler: str, valgrind: bool) -> dict:
    """A configure's probe results for one compiler, everything else as committed."""
    return {
        "compiler": compiler,
        "preset": f"{compiler}-coverage",
        "environment": "linux-arm64",
        "capabilities": {
            "asan": True,
            "ubsan": True,
            "tsan": True,
            "valgrind": valgrind,
        },
    }


class Check(unittest.TestCase):
    def run_check(self, probe_data: dict, lock: dict) -> tuple[int, str, str]:
        """caps.check on temp files; the exit code and what it printed."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            probe_path = d / "capabilities.json"
            probe_path.write_text(json.dumps(probe_data), encoding="utf-8")
            lock_path = d / "capabilities.lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = caps.check(probe_path, lock_path)
            return rc, out.getvalue(), err.getvalue()

    def test_a_planted_mismatch_fails_naming_the_capability(self) -> None:
        # The contradiction the shared image had: Valgrind on every compiler's
        # PATH while the lock records it for gcc16 only (D37, D42).
        rc, _, err = self.run_check(probe("clang23", valgrind=True), LOCK)
        self.assertNotEqual(rc, 0)
        self.assertIn("capability valgrind: probe True, lock False", err)
        self.assertIn("on clang23-coverage (linux-arm64)", err)

    def test_ci_caps_entry_point_rejects_planted_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "capabilities.json").write_text(
                json.dumps(probe("clang23", valgrind=True))
            )
            lock_path = directory / "lock.json"
            lock_path.write_text(json.dumps(LOCK))
            result = subprocess.run(
                ["bash", str(ROOT / ".mise/tasks/ci/caps")],
                env={
                    **os.environ,
                    "MISE_PROJECT_ROOT": str(ROOT),
                    "usage_build_dir": tmp,
                    "CPPSTD_CAPS_LOCK": str(lock_path),
                },
                capture_output=True,
                check=False,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ci:caps: FAIL", result.stderr)
        self.assertIn("capability valgrind: probe True, lock False", result.stderr)

    def test_the_gate_reports_a_lock_disabled_tsan_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            lock_path = directory / "lock.json"
            report = directory / "report.txt"
            entry = {
                "capabilities": dict.fromkeys(caps.CAPABILITIES, False),
                "skip_reasons": {"tsan": "test runtime unavailable"},
            }
            data = {
                "environments": {"linux-arm64": {"presets": {"clang23-tsan": entry}}}
            }
            (directory / "python").symlink_to(ROOT / "python", target_is_directory=True)
            scripts = {
                "cmake": '[[ "$*" == "--preset clang23-coverage -B build/clang23-tsan -DCPPSTD_GATE_PRESET=clang23-tsan" ]] || exit 1\n'
                "mkdir -p build/clang23-tsan && cp probe.json build/clang23-tsan/capabilities.json",
                "mise": 'case "$*" in\n'
                '  "run -q vcpkg:bootstrap --check") exit 0 ;;\n'
                '  "run -q ci:caps clang23-tsan") usage_preset=clang23-tsan exec bash "$CAPS_TASK" ;;\n'
                "  *) exit 1 ;;\nesac",
            }
            for name, script in scripts.items():
                path = directory / name
                path.write_text("#!/bin/bash\n" + script + "\n")
                path.chmod(0o755)
            for locked, observed, expected in [
                (
                    False,
                    False,
                    [
                        "caps-clang23-tsan passed",
                        "build-clang23-tsan skipped",
                        "sanitizers-clang23-tsan skipped",
                    ],
                ),
                (False, True, ["caps-clang23-tsan failed"]),
                (True, True, ["build-clang23-tsan failed"]),
            ]:
                with self.subTest(locked=locked, observed=observed):
                    report.unlink(missing_ok=True)
                    entry["capabilities"]["tsan"] = locked
                    lock_path.write_text(json.dumps(data))
                    (directory / "probe.json").write_text(
                        json.dumps(
                            {
                                "compiler": "clang23",
                                "environment": "linux-arm64",
                                "preset": "clang23-tsan",
                                "capabilities": {
                                    **entry["capabilities"],
                                    "tsan": observed,
                                },
                            }
                        )
                    )
                    result = subprocess.run(
                        ["bash", str(ROOT / ".mise/tasks/ci/_default")],
                        env={
                            "PATH": f"{tmp}:{os.defpath}",
                            "MISE_PROJECT_ROOT": tmp,
                            "CPPSTD_GATE_PRESETS": "clang23-tsan",
                            "CAPS_TASK": str(ROOT / ".mise/tasks/ci/caps"),
                            "CPPSTD_CAPS_ENVIRONMENT": "linux-arm64",
                            "CPPSTD_CAPS_LOCK": str(lock_path),
                            "CPPSTD_GATE_REPORT": str(report),
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode == 0, not observed, result.stderr
                    )
                    self.assertEqual(
                        report.read_text().splitlines(),
                        ["gate-linux-arm64 " + row for row in expected],
                    )

    def test_same_omission_in_probe_and_lock_is_refused(self) -> None:
        data = probe("clang23", valgrind=False)
        lock = json.loads(json.dumps(LOCK))
        del data["capabilities"]["ubsan"]
        del lock["environments"]["linux-arm64"]["presets"]["clang23-coverage"][
            "capabilities"
        ]["ubsan"]
        rc, _, err = self.run_check(data, lock)
        self.assertEqual(rc, 1)
        self.assertIn("ubsan: missing from both", err)

    def test_numeric_capability_is_not_a_boolean(self) -> None:
        data = probe("clang23", valgrind=False)
        data["capabilities"]["valgrind"] = 0
        rc, _, err = self.run_check(data, LOCK)
        self.assertEqual(rc, 1)
        self.assertIn("non-boolean capabilities: valgrind", err)

    def test_a_probe_that_matches_the_lock_passes(self) -> None:
        rc, out, err = self.run_check(probe("clang23", valgrind=False), LOCK)
        self.assertEqual(rc, 0, err)
        self.assertIn(
            "PASS: probes match the capability lock (clang23-coverage, linux-arm64)",
            out,
        )

    def test_a_capability_missing_from_the_probe_fails_by_name(self) -> None:
        # The lock lists valgrind for gcc16; a probe that omits it is a mismatch.
        planted = json.loads(json.dumps(probe("gcc16", valgrind=True)))
        del planted["capabilities"]["valgrind"]
        rc, _, err = self.run_check(planted, LOCK)
        self.assertNotEqual(rc, 0)
        self.assertIn("capability valgrind: the lock lists it, the probe did not", err)
        self.assertIn("on gcc16-coverage (linux-arm64)", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
