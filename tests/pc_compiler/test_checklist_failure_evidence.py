"""Offline regression for the host checklist's exit trap and no-install gate."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = (ROOT / ".mise/tasks/certify/ubuntu").read_text()
CLEANUP = DRIVER[DRIVER.index("check_files=(") : DRIVER.index("want()")]
RULE_START = DRIVER.index('if [[ "$actions_host" == 1 ]]; then\n  docker diff')
RULE = DRIVER[RULE_START : DRIVER.index("inst_after=", RULE_START)]
VOLUME = DRIVER[DRIVER.index("p2996_vol=") : DRIVER.index("scratch=")]


RECEIPTS = {
    "body.txt",
    "lines1.txt",
    "lines2.txt",
    "lines3.txt",
    "limits",
    "timing-cpu",
    "timing-events.jsonl",
    "ab-cpu",
    "ab-events.jsonl",
    "ab_c",
    "ab_h",
    "rootfs.diff",
}
SEED = (
    "for name in "
    + " ".join(sorted(RECEIPTS))
    + '; do echo fixture > "$scratch/$name"; done'
)


class ChecklistFailureEvidence(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.result = self.base / "result"
        self.result.mkdir()

    def run_guard(self, setup, diff="C /var/lib/dpkg/status", after=""):
        return subprocess.run(
            [
                "bash",
                "-c",
                """
set -uo pipefail
scratch="$PWD/scratch"
mkdir "$scratch" || exit 8
CERT_CPP_EVIDENCE="$PWD/result"
inst_mark="$PWD/marker"
actions_host=1 cname=fixture
docker() {
  [[ "$*" == 'diff fixture' ]] || return 99
  printf '%s\\n' "$diff"
}
"""
                + CLEANUP
                + setup
                + "\n"
                + RULE
                + after,
            ],
            check=False,
            cwd=self.base,
            env={"PATH": "/usr/bin:/bin", "diff": diff},
            text=True,
            capture_output=True,
            timeout=5,
        )

    def test_report_mask_keeps_rootfs_evidence_name(self):
        mask = DRIVER[
            DRIVER.index("mask() {") : DRIVER.index("\n}", DRIVER.index("mask() {")) + 2
        ]
        for user in ("root", "fixture-user"):
            with self.subTest(user=user):
                proc = subprocess.run(
                    ["bash", "-c", mask + '\nid() { echo "$fixture_account"; }; mask'],
                    env={
                        "PATH": "/usr/bin:/bin",
                        "HOME": f"/{user}",
                        "fixture_account": user,
                        "dest": "test-pc",
                        "label": "amd64",
                    },
                    input=f"{user}@test-pc /{user}/private rootfs 10 MB (see rootfs.diff)\n",
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                self.assertEqual(
                    proc.stdout,
                    "<user>@<pc> ~/private rootfs 10 MB (see rootfs.diff)\n",
                )

    def test_mask_failure_and_unwritable_output_fail_certification(self):
        footer = DRIVER[DRIVER.index("\nreport | mask") :]
        for output, mask_rc in [("", "1"), (str(self.result), "0")]:
            with self.subTest(output=output):
                proc = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'set -o pipefail; report() { echo row; }; mask() { cat; return "$mask_rc"; }; '
                        + footer,
                    ],
                    env={
                        "PATH": "/usr/bin:/bin",
                        "out": output,
                        "mask_rc": mask_rc,
                        "strict_timing_failed": "0",
                        "nfail": "0",
                    },
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
                self.assertEqual(proc.returncode, 2)

    def test_protected_change_keeps_partial_rows_and_path(self):
        proc = self.run_guard(
            """
printf 'P8 PASS fixture\n' > "$scratch/lines1.txt"
cp "$scratch/lines1.txt" "$scratch/body.txt"
touch "$scratch/unrelated"
ln -s "$scratch/unrelated" "$scratch/lines2.txt"
"""
        )
        self.assertEqual(proc.returncode, 3, proc.stderr)
        partial = self.result / "partial"
        self.assertEqual(
            sorted(p.name for p in partial.iterdir()),
            ["body.txt", "lines1.txt", "rootfs.diff"],
        )
        self.assertEqual(
            (partial / "rootfs.diff").read_text(), "C /var/lib/dpkg/status\n"
        )
        self.assertEqual((partial / "body.txt").read_text(), "P8 PASS fixture\n")
        self.assertFalse((self.result / "body.txt").exists())
        self.assertFalse((self.base / "scratch").exists())

    def test_installed_python_change_is_still_refused(self):
        path = "C /root/.local/share/mise/installs/python/3.14.8/lib/python3.14/os.py"
        proc = self.run_guard("", diff=path)
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertEqual((self.result / "partial/rootfs.diff").read_text(), path + "\n")

    def test_retention_error_preserves_original_refusal_and_cleanup(self):
        (self.result / "partial").touch()
        proc = self.run_guard("")
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertIn("partial", proc.stderr)
        self.assertFalse((self.base / "scratch").exists())

    def test_accepted_diff_retains_complete_top_level_evidence(self):
        proc = self.run_guard(
            SEED,
            diff="A /tmp/fixture",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual({p.name for p in self.result.iterdir()}, RECEIPTS)
        self.assertEqual((self.result / "body.txt").read_text(), "fixture\n")
        self.assertEqual((self.result / "rootfs.diff").read_text(), "A /tmp/fixture\n")
        self.assertFalse((self.result / "partial").exists())

    def test_complete_failed_checklist_is_retained_once(self):
        proc = self.run_guard(
            SEED,
            diff="A /tmp/fixture",
            after="exit 1",
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual((self.result / "body.txt").read_text(), "fixture\n")
        self.assertFalse((self.result / "partial").exists())

    def test_missing_required_receipt_never_publishes_final_counts(self):
        proc = self.run_guard(
            SEED + '\nrm "$scratch/timing-events.jsonl"',
            diff="A /tmp/fixture",
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual({p.name for p in self.result.iterdir()}, {"partial"})
        self.assertEqual(
            {p.name for p in (self.result / "partial").iterdir()},
            RECEIPTS - {"timing-events.jsonl"},
        )
        self.assertFalse((self.result / "body.txt").exists())
        self.assertEqual((self.result / "partial/body.txt").read_text(), "fixture\n")

    def test_timing_capture_retains_markers_and_refuses_incumbent_lifecycle(self):
        capture = DRIVER[
            DRIVER.index("prove_timing_events()") : DRIVER.index(
                "strict_timing_failed="
            )
        ]
        owner, other = "a" * 64, "b" * 64

        def event(actor, action):
            return json.dumps(
                {
                    "Type": "container",
                    "Action": action,
                    "Actor": {
                        "ID": actor,
                        "Attributes": {
                            "name": "fixture" if actor == owner else "private-name",
                            "label": "private-label",
                        },
                    },
                }
            )

        for actor, action, expected in [
            (other, "exec_create: private-command", 0),
            (other, "start", 1),
            (None, "start", 1),
        ]:
            with self.subTest(action=action):
                sample = self.base / "events"
                sample.write_text(
                    "\n".join(
                        [
                            event(owner, "exec_create: /bin/echo before"),
                            event(actor, action),
                            event(owner, "exec_create: /bin/echo after"),
                        ]
                    )
                )
                proc = subprocess.run(
                    [
                        "bash",
                        "-c",
                        """
set -uo pipefail
cname=fixture
docker() {
  case "$1" in
    inspect) echo "$owner" ;;
    events) cat events ;;
    *) return 99 ;;
  esac
}
"""
                        + capture
                        + "prove_timing_events 1 2 before after receipt",
                    ],
                    cwd=self.base,
                    env={
                        "PATH": os.environ["PATH"],
                        "HOME": str(Path.home()),
                        "owner": owner,
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(proc.returncode, expected, proc.stderr)
                data = (self.base / "receipt").read_text()
                self.assertNotIn("private", data)
                rows = [json.loads(line) for line in data.splitlines()]
                self.assertEqual(
                    rows[0]["Actor"], {"ID": owner, "Attributes": {"name": "fixture"}}
                )
                if actor is None:
                    self.assertEqual(len(rows), 1)
                    self.assertIn("invalid container event", proc.stderr)
                    continue
                self.assertEqual(rows[1]["Actor"], {"ID": other})
                self.assertEqual(rows[1]["Action"], "start" if expected else "other")

    def test_volume_hash_is_only_required_for_default_volume(self):
        for actions, override, expected in [(1, "", 0), (0, "custom", 0), (0, "", 2)]:
            with self.subTest(actions=actions, override=override):
                proc = subprocess.run(
                    [
                        "bash",
                        "-c",
                        "set -uo pipefail\nshasum() { touch invoked; return 127; }\n"
                        + VOLUME,
                    ],
                    check=False,
                    cwd=self.base,
                    env={
                        "PATH": os.defpath,
                        "actions_host": str(actions),
                        "pin": "a" * 40,
                        "root": str(ROOT),
                        "CERT_P2996_VOL": override,
                    },
                    capture_output=True,
                    timeout=5,
                )
                self.assertEqual(proc.returncode, expected, proc.stderr)
                self.assertEqual((self.base / "invoked").exists(), expected == 2)


if __name__ == "__main__":
    unittest.main()
