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
G5_ROW = "G5    N/A  rule, no probe: C++ dependencies for GCC come from vcpkg with the GCC triplet (K1)"


def shell_function(script, name):
    start = script.index(name + "() {")
    return script[start:].split("\n}", 1)[0] + "\n}"


class PrivateTimingSamples(unittest.TestCase):
    def test_receipts_match_aggregate_without_extra_counter_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            public = state / "result"
            private = state / "timing-private"
            public.mkdir()
            private.mkdir(mode=0o700)
            script = "\n".join(
                shell_function(DRIVER, name)
                for name in ("retain_cpu_sample", "others_cpu", "cpu_trust")
            )
            script += r"""
actions_host=1
cname=check
state="$1"
CERT_CPP_EVIDENCE="$state/result"
docker() {
    case "$*" in
        'ps -q --no-trunc') printf '%s\n' beta self alpha ;;
        *"{{.Id}}"*) echo self ;;
        *"{{.State.Pid}} alpha") echo 101 ;;
        *"{{.State.Pid}} beta") echo 102 ;;
        *) return 1 ;;
    esac
}
sed() {
    local pid="${3#/proc/}"
    printf '/example/%s\n' "${pid%/cgroup}"
}
awk() {
    printf '%s\n' "$2" >>"$state/reads"
    case "$2" in
        */101/cpu.stat) echo "$counter" ;;
        */102/cpu.stat) echo "$second" ;;
    esac
}
counter=100
second=20
before="$(others_cpu main-before)"
counter=1000101
after="$(others_cpu main-after)"
cpu_trust "$before" "$after"
printf '%s\n' "$before" "$after" "$cpu_evidence_ok/$busy/$why"
printf '%s\n' "$(others_cpu ab-before)"
second=invalid
printf '%s\n' "$(others_cpu ab-after)"
"""
            output = subprocess.check_output(
                ["bash", "-eu", "-c", script, "fixture", state], text=True
            )
            self.assertEqual(
                output.splitlines(),
                [
                    "alpha,beta 120 0",
                    "alpha,beta 1000121 0",
                    "1/1000/over one CPU-second elsewhere",
                    "alpha,beta 1000121 0",
                    "alpha,beta 1000101 1",
                ],
            )
            self.assertEqual(len((state / "reads").read_text().splitlines()), 8)
            self.assertEqual(list(public.iterdir()), [])
            self.assertEqual(len(list(private.iterdir())), 4)
            for index, endpoint in enumerate(
                ("main-before", "main-after", "ab-before", "ab-after")
            ):
                path = private / f"{endpoint}.tsv"
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                rows = path.read_text().splitlines()[1:]
                self.assertEqual(
                    rows,
                    [
                        f"alpha\t/example/101\t{100 if index == 0 else 1000101}",
                        f"beta\t/example/102\t{'-' if index == 3 else '20'}",
                    ],
                )
            private.rename(state / "unavailable")
            retry = subprocess.check_output(
                ["bash", "-eu", "-c", script, "fixture", state], text=True
            )
            self.assertEqual(retry, output)
            self.assertFalse(private.exists())


class AdvisoryTiming(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        doc = (ROOT / "docs/standard/ubuntu.md").read_text()
        self.ids = re.findall(r"^\*\*([A-Z]+\d+)\.", doc, re.MULTILINE)
        self.assertEqual(len(self.ids), 83)

    def fixture_rows(self):
        rows = [
            f"{check} {'N/A' if check in ARCHIVED_NA else 'PASS'} fixture"
            for check in self.ids
        ]
        rows[self.ids.index("G5")] = G5_ROW
        return rows

    def test_checklist_identity_and_g5_evidence(self):
        headings = "".join(f"**{key}.**\n" for key in self.ids)
        rows = "\n".join(self.fixture_rows()) + "\n"
        doc = self.scratch / "docs/standard/ubuntu.md"
        doc.parent.mkdir(parents=True)
        body = self.scratch / "body.txt"
        check = (
            shell_function(LAUNCHER, "check_compiler_rows")
            + "\ncheck_compiler_rows verified"
        )
        g2 = "G2 PASS fixture\n"
        for name, playbook, report, expected in (
            ("full", headings, rows, 0),
            (
                "both omit G2",
                headings.replace("**G2.**\n", ""),
                rows.replace(g2, ""),
                1,
            ),
            (
                "both substitute G3",
                headings.replace("G2.", "G3."),
                rows.replace("G2 ", "G3 "),
                1,
            ),
            ("headings duplicate G1", headings.replace("G2.", "G1."), rows, 1),
            (
                "G5 arbitrary N/A",
                headings,
                rows.replace(G5_ROW, "G5 N/A arbitrary"),
                1,
            ),
            ("G5 claims PASS", headings, rows.replace("G5    N/A ", "G5    PASS"), 1),
        ):
            with self.subTest(name=name):
                doc.write_text(playbook)
                body.write_text(report)
                checked = subprocess.run(
                    ["bash", "-c", check],
                    env={
                        **os.environ,
                        "source": str(self.scratch),
                        "result": str(self.scratch),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(checked.returncode, expected, checked.stderr)

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
        rows = self.fixture_rows()
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
