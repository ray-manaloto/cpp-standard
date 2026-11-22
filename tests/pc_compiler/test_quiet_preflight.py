"""Offline controls for quiet-window admission and CPU attribution."""

import contextlib
import errno
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
    def run_sample(
        self,
        *samples,
        monotonic=None,
        clock_guard=contextlib.nullcontext,
        identity=("nzxth1desktop", "x86_64"),
    ):
        main = QUIET["main"]
        with (
            patch.dict(
                main.__globals__,
                {
                    "WINDOW_SECONDS": 30,
                    "snapshot": unittest.mock.Mock(side_effect=samples),
                    "host_identity": unittest.mock.Mock(return_value=identity),
                    "event_anchor": unittest.mock.Mock(
                        return_value=("daemon", "incumbent", (100, 150))
                    ),
                    "top_marker": unittest.mock.Mock(return_value=(180, 200)),
                    "check_events": unittest.mock.Mock(return_value=2),
                    "stable_wall_clock": clock_guard,
                },
            ),
            patch.object(QUIET["time"], "sleep") as sleep,
            patch.object(
                QUIET["time"], "monotonic", side_effect=monotonic, return_value=0
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            exit_code = main()
            self.sleep_calls = sleep.call_args_list
        return exit_code, json.loads(output.getvalue())

    def test_budget_boundary_and_per_container_deltas(self):
        for total, expected in ((800_000, 0), (800_001, 1)):
            with self.subTest(total=total):
                exit_code, report = self.run_sample(
                    sample(10), sample(210), sample(10 + total)
                )
                self.assertEqual(exit_code, expected)
                self.assertEqual(report["host"], "nzxth1desktop")
                self.assertEqual(report["architecture"], "x86_64")
                self.assertEqual(report["total_cpu_us"], total)
                self.assertEqual(
                    [item["cpu_us"] for item in report["samples"]],
                    [
                        {"a": 0},
                        {"a": 200},
                        {"a": total},
                    ],
                )

    def test_wrong_host_or_architecture_is_rejected_before_sampling(self):
        for host, architecture in (
            ("other-desktop", "x86_64"),
            ("nzxth1desktop", "aarch64"),
        ):
            with self.subTest(host=host, architecture=architecture):
                exit_code, report = self.run_sample(identity=(host, architecture))
                self.assertEqual(exit_code, 1)
                self.assertFalse(report["ready"])
                self.assertEqual(
                    (report["host"], report["architecture"]), (host, architecture)
                )
                self.assertEqual(report["samples"], [])

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

    def test_missed_monotonic_sample_fails_instead_of_catching_up(self):
        exit_code, report = self.run_sample(
            sample(10), sample(20), sample(30), monotonic=[0, 0, 0, 18]
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(report["ready"])
        self.assertIn("missed CPU sample deadline at +15s", report["error"])
        self.assertEqual(len(report["samples"]), 1)

    def test_incomplete_baseline_fails_before_window_can_be_certified(self):
        exit_code, report = self.run_sample(
            sample(10), sample(20), sample(30), monotonic=[0, 3]
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(report["ready"])
        self.assertIn("missed CPU sample deadline at +0s", report["error"])
        self.assertEqual(report["samples"], [])

    def test_full_window_starts_after_a_slow_valid_baseline(self):
        exit_code, report = self.run_sample(
            sample(10),
            sample(20),
            sample(30),
            monotonic=[0, 1.8, 1.8, 16.85, 16.85, 31.85],
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["ready"])
        self.assertEqual(len(self.sleep_calls), 2)
        self.assertAlmostEqual(self.sleep_calls[0].args[0], 15)
        self.assertAlmostEqual(self.sleep_calls[1].args[0], 14.95)

    def test_clock_step_disqualifies_an_otherwise_quiet_sample(self):
        os_module = QUIET["os"]
        close = unittest.mock.Mock()
        with patch.multiple(
            os_module,
            timerfd_create=unittest.mock.Mock(return_value=123),
            timerfd_settime_ns=unittest.mock.Mock(),
            TFD_NONBLOCK=1,
            TFD_TIMER_ABSTIME=2,
            TFD_TIMER_CANCEL_ON_SET=4,
            read=unittest.mock.Mock(side_effect=OSError(errno.ECANCELED, "clock step")),
            close=close,
            create=True,
        ):
            exit_code, report = self.run_sample(
                sample(10),
                sample(20),
                sample(30),
                clock_guard=QUIET["stable_wall_clock"],
            )
        self.assertEqual(exit_code, 1)
        self.assertFalse(report["ready"])
        self.assertIn("wall clock stepped", report["error"])
        self.assertEqual(len(report["samples"]), 3)
        close.assert_called_once_with(123)

    def test_container_root_includes_services_outside_init_scope(self):
        container = "a" * 64
        scope = f"/system.slice/docker-{container}.scope"
        with patch.object(Path, "read_text", return_value=f"0::{scope}/init.scope\n"):
            self.assertEqual(
                QUIET["container_cgroup"](container, "10"),
                Path(f"/sys/fs/cgroup{scope}"),
            )
            with self.assertRaisesRegex(ValueError, "cannot identify"):
                QUIET["container_cgroup"]("b" * 64, "10")

    def test_short_lived_container_and_missing_history_fail_closed(self):
        anchor = ("daemon", "incumbent", (100, 150))
        closing = (180, 200)
        top = {
            "Type": "container",
            "Action": "top",
            "Actor": {"ID": "incumbent"},
            "timeNano": 125,
        }
        start = {
            "Type": "container",
            "Action": "start",
            "Actor": {"ID": "short"},
            "timeNano": 160,
        }
        die = {**start, "Action": "die", "timeNano": 165}
        end = {**top, "timeNano": 190}
        check = QUIET["check_events"]
        cases = (
            ([top, end], "daemon", None),
            ([top, start, die, end], "daemon", "lifecycle event"),
            ([], "daemon", "lost the start anchor"),
            ([top], "daemon", "lost the end anchor"),
            ([end, top], "daemon", "lost the end anchor"),
            ([top, end], "replacement", "daemon restarted"),
        )
        for events, invocation, error in cases:
            with (
                self.subTest(error=error),
                patch.dict(
                    check.__globals__,
                    {
                        "docker": unittest.mock.Mock(
                            return_value="\n".join(map(json.dumps, events))
                        ),
                        "daemon_invocation": unittest.mock.Mock(
                            return_value=invocation
                        ),
                    },
                ),
            ):
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        check(anchor, closing)
                else:
                    self.assertEqual(check(anchor, closing), 2)
