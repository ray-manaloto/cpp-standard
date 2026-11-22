"""Offline controls for quiet-window admission and CPU attribution."""

import contextlib
import io
import json
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
QUIET = runpy.run_path(str(ROOT / "docs/standard/gha-runner/pc-compiler-quiet.py"))


def sample(usage, *, pid="10"):
    return {"a": ("/incumbent", pid, "start", "0", "/cgroup", usage)}


class QuietPreflightTest(unittest.TestCase):
    def run_sample(self, *samples):
        main = QUIET["main"]
        with (
            patch.dict(
                main.__globals__,
                {
                    "WINDOW_SECONDS": 30,
                    "snapshot": unittest.mock.Mock(side_effect=samples),
                },
            ),
            patch.object(QUIET["time"], "sleep"),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            exit_code = main()
        return exit_code, json.loads(output.getvalue())

    def test_budget_boundary_and_per_container_deltas(self):
        for total, expected in ((800_000, 0), (800_001, 1)):
            with self.subTest(total=total):
                exit_code, report = self.run_sample(
                    sample(10), sample(210), sample(10 + total)
                )
                self.assertEqual(exit_code, expected)
                self.assertEqual(report["total_cpu_us"], total)
                self.assertEqual(
                    [item["cpu_us"] for item in report["samples"]],
                    [
                        {"a": 0},
                        {"a": 200},
                        {"a": total},
                    ],
                )

    def test_fails_on_inventory_change_restart_and_counter_reset(self):
        cases = (
            ({}, "inventory changed"),
            (sample(210, pid="11"), "identity changed"),
            (sample(110), "went backwards"),
            (FileNotFoundError("cgroup disappeared"), "cgroup disappeared"),
        )
        for final, error in cases:
            with self.subTest(error=error):
                exit_code, report = self.run_sample(sample(10), sample(210), final)
                self.assertEqual(exit_code, 1)
                self.assertFalse(report["ready"])
                self.assertIn(error, report["error"])
                self.assertEqual(len(report["samples"]), 2)
