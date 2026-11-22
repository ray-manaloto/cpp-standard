"""Replay the archived busy windows without Docker, a runner or a dispatch."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = (ROOT / ".mise/tasks/certify/ubuntu").read_text()
LAUNCHER = (ROOT / "docs/standard/gha-runner/pc-compiler-once.sh").read_text()
ARCHIVED_NA = {"A4", "E1", "G5", "H1", "K1", "T1", "T6", "U2", "U3", "U4", "V5"}


def shell_function(script, name):
    start = script.index(name + "() {")
    return script[start:].split("\n}", 1)[0] + "\n}"


class AdvisoryTiming(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        doc = (ROOT / "docs/standard/ubuntu.md").read_text()
        self.ids = re.findall(r"^\*\*([A-Z]+\d+)\.", doc, re.MULTILINE)
        self.assertEqual(len(self.ids), 83)

    def replay(
        self, *, ab_after=1170124684, overhead=False, failure=None, advisory="1"
    ):
        # Archived 44989384337/1. The incumbent IDs are immaterial here.
        (self.scratch / "ab_c").write_text(
            f"{5300 if overhead else 5084} 246 36538639489 1270490722\n"
            f"{5300 if overhead else 5102} 246 36537725324 1270490728\n"
            f"{5300 if overhead else 5072} 246 36545707205 1270490726\n"
        )
        (self.scratch / "ab_h").write_text(
            "5093 244 36538347676 1270497623\n"
            "5067 245 36537472688 1270497622\n"
            "5083 245 36539509555 1270497624\n"
        )
        v6_start = DRIVER.index("import sys\ndef rows(path):")
        v6_code = DRIVER[v6_start:].split("\nPY\n", 1)[0]
        if failure == "incomplete-ab":
            (self.scratch / "ab_c").write_text("5072 246 36545707205 1270490726\n")
        if failure == "truncated-extra-ab":
            with (self.scratch / "ab_c").open("a") as evidence:
                evidence.write("12 34\n")
        v6 = subprocess.check_output(
            [
                "python3",
                "-c",
                v6_code,
                self.scratch / "ab_c",
                self.scratch / "ab_h",
                str((ab_after - 1168901434) // 1000),
                "11213",
                "737",
                "still-there" if failure == "rootfs" else "removed",
                "",
            ],
            text=True,
        )
        rows = [
            f"{check} {'N/A' if check in ARCHIVED_NA else 'PASS'} fixture"
            for check in self.ids
        ]
        rows[self.ids.index("V6")] = v6.rstrip()
        if failure in {"B3", "U3", "V4"}:
            rows[self.ids.index(failure)] = f"{failure} FAIL [timing] fixture"
        if failure == "missing-required":
            rows[self.ids.index("V1")] = "V1 N/A fixture"
        if failure == "skipped-required":
            rows[self.ids.index("A1")] = "A1 N/A fixture"
        if failure == "wrong-id":
            rows[self.ids.index("V1")] = "UNKNOWN PASS fixture"
        (self.scratch / "body.txt").write_text("\n".join(rows) + "\n")
        footer = DRIVER[
            DRIVER.index('\n[[ "$inst_after" == "$inst_before" ]] || exit 3') :
        ]
        gate = LAUNCHER[LAUNCHER.index('    check_compiler_rows "$(') :].split(
            "\n  }", 1
        )[0]
        body = (
            shell_function(DRIVER, "cpu_trust")
            + "\n"
            + shell_function(LAUNCHER, "check_compiler_rows")
            + """
cpu_trust 'incumbents 1168164713 0' 'incumbents 1168797477 0'
[[ -z "$why" ]] || exit 9
cpu_trust 'incumbents 1168901434 0' "incumbents $ab_after $missed"
strict_timing_failed=0
[[ -z "$why" ]] || strict_timing_failed=1
timing_integrity_failed=0
((cpu_evidence_ok)) && [[ "$failure" != invalid-events ]] || timing_integrity_failed=1
actions_host=1 rc_inner="" inst_before=same inst_after=same
[[ "$failure" != probe-exit ]] || rc_inner=pass2:1
[[ "$failure" != install-change ]] || inst_after=changed
nfail="$(grep -cE '^[A-Z0-9]+ +FAIL' "$scratch/body.txt")"
(
"""
            + footer
            + """
) || exit "$?"
set -e
certify_compiler_project() { printf 'project image: %s\n' "$1"; }
"""
            + gate
        )
        return subprocess.run(
            ["bash", "-c", body],
            env={
                **os.environ,
                "CERT_CPP_TIMING_ADVISORY": advisory,
                "CERT_CPP_EVIDENCE": str(self.scratch),
                "ab_after": str(ab_after),
                "candidate": "sha256:" + "a" * 64,
                "failure": failure or "",
                "missed": "1" if failure == "missing-cpu" else "0",
                "result": str(self.scratch),
                "scratch": str(self.scratch),
                "source": str(ROOT),
            },
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_archived_busy_window_continues_without_turning_strict_verdict_green(self):
        strict = self.replay(advisory="0")
        self.assertEqual(strict.returncode, 1, strict.stderr)
        routine = self.replay()
        self.assertEqual(routine.returncode, 0, routine.stderr)
        self.assertEqual(routine.stdout, "project image: sha256:" + "a" * 64 + "\n")
        self.assertEqual(
            (self.scratch / "timing-verdict.txt").read_text(), "unverified\n"
        )
        report = (self.scratch / "body.txt").read_text()
        self.assertIn(
            "compile 5072 vs 5067 ms (+0.1%), bench 246 vs 244 ms (+0.8%)", report
        )
        self.assertIn("others 1223 ms CPU", report)

    def test_quiet_overhead_miss_continues_with_strict_failure(self):
        result = self.replay(ab_after=1169801434, overhead=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "project image: sha256:" + "a" * 64 + "\n")
        self.assertEqual((self.scratch / "timing-verdict.txt").read_text(), "failed\n")

    def test_raw_microseconds_determine_strict_quietness(self):
        for delta, verdict in [(1_000_000, "verified"), (1_000_001, "unverified")]:
            with self.subTest(delta=delta):
                result = self.replay(ab_after=1168901434 + delta)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    (self.scratch / "timing-verdict.txt").read_text(), verdict + "\n"
                )

    def test_functional_and_integrity_failures_stop_before_project(self):
        for failure in (
            "B3",
            "U3",
            "V4",
            "incomplete-ab",
            "truncated-extra-ab",
            "rootfs",
            "missing-cpu",
            "invalid-events",
            "missing-required",
            "skipped-required",
            "wrong-id",
            "probe-exit",
            "install-change",
        ):
            with self.subTest(failure=failure):
                (self.scratch / "timing-verdict.txt").unlink(missing_ok=True)
                result = self.replay(failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
