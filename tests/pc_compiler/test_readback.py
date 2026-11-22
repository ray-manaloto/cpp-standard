"""Offline regression controls for checkpoint and qualification reporting."""

import hashlib
import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = runpy.run_path(str(ROOT / "docs/standard/gha-runner/pc-compiler-readback.py"))


class ReadbackTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def test_checkpoint_uses_acquisition_time_and_rejects_other_attempts(self):
        note = self.root / ".planning/owner/progress.md"
        note.parent.mkdir(parents=True)
        note.write_text(
            "## 2026-11-21 UTC\n## Latest host sample\n- 23:28:17 UTC. LLVM 3723/8986\n"
        )
        (self.root / "sample-old.txt").write_text("2026-11-21T22:54:19Z\nactive\n")
        (self.root / "run-admitted.json").write_text('{"id": 7, "run_attempt": 1}')
        owner = self.root / "owner.json"
        receipt = {
            "run": 7,
            "attempt": 1,
            "acquired": "2026-11-22T00:20:50Z",
            "observation": "8556/8986",
        }
        owner.write_text(json.dumps(receipt))
        for poll, source in (("23:29:00", note),):
            report = REPORT["checkpoint"](
                self.root, REPORT["timestamp"](f"2026-11-21T{poll}Z"), [owner]
            )
            self.assertEqual(report["host_sample"]["source"], str(source))
        polled = REPORT["timestamp"]("2026-11-22T00:57:45Z")
        self.assertEqual(
            REPORT["checkpoint"](self.root, polled, [owner])["host_sample"]["source"],
            str(owner),
        )
        owner.write_text(json.dumps({**receipt, "attempt": 2}))
        with self.assertRaisesRegex(ValueError, "another attempt"):
            REPORT["checkpoint"](self.root, polled, [owner])

    def test_closeout_binds_keys_identity_and_reports_late_inventory(self):
        result = self.root / "host-result/result"
        result.mkdir(parents=True)
        (result / "assignment.json").write_text('{"run":"7","job":"8","runner_id":"9"}')
        (result / "built-image").write_text("sha256:" + "a" * 64)
        deadline = {
            "run": 7,
            "job": 8,
            "runner": 9,
            "target_utc": "2026-11-22T01:00:00Z",
            "drain_verified_utc": "2026-11-22T01:00:14Z",
        }
        (self.root / "deadline.json").write_text(json.dumps(deadline))
        report = REPORT["closeout"](self.root)
        self.assertIsNone(report["compiler_package"])
        self.assertEqual(report["seconds_from_target"]["drain_verified_utc"], 14)
        key = hashlib.sha256(b"{}").hexdigest()
        (result / "compiler-inputs.json").write_text("{}")
        (result / "compiler-cache.txt").write_text(
            f"inputs_sha256={key}\nsource=local\n"
        )
        (result / "compiler-package.json").write_text(
            json.dumps({"inputs_sha256": key, "archive_sha256": "a" * 64})
        )
        self.assertEqual(
            REPORT["closeout"](self.root)["compiler_package"]["source"], "local"
        )
        (result / "compiler-inputs.json").write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "key mismatch"):
            REPORT["closeout"](self.root)
        (self.root / "deadline.json").write_text(json.dumps({**deadline, "job": 10}))
        with self.assertRaisesRegex(ValueError, "job differs"):
            REPORT["closeout"](self.root)
