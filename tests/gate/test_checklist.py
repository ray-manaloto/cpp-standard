"""Tests of the gate checklist and its checker (D119 as amended by D182, spec #133).

Covers:
1. post-merge.yml has exactly one trigger, a push to main; its daily schedule ended with the
   2026-11-27 sunset (D182). apt-bump.yml runs only by hand and builder.yml keeps its push,
   dispatch, pull-request and merge-queue triggers; none of the three has a schedule (D182).
2. Every post-merge.yml job runs on ubuntu-26.04-arm, the free hosted arm64 runner (G8).
3. The checker writes one entry per item, passed / failed / not run: an item whose
   check has no report line is "not run" and exits non-zero, never passed.
4. A full green result set passes; a red, malformed or duplicate report fails.
5. Every gate-items.toml item maps to a job (and, where set, a preset) that
   post-merge.yml runs and reports and to a check that exists; the workflow gates
   exactly the presets the gate (.mise/tasks/ci/_default) lists and runs exactly
   the fixtures expected.toml lists, each with its checklist item.

Run: python3 -I tests/gate/test_checklist.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/gate"))

import checklist

POST_MERGE = ROOT / ".github/workflows/post-merge.yml"
APT_BUMP = ROOT / ".github/workflows/apt-bump.yml"
BUILDER = ROOT / ".github/workflows/builder.yml"
ITEMS_FILE = ROOT / "gate-items.toml"
EXPECTED = ROOT / "fixtures/must-fail/expected.toml"
CI_DEFAULT = ROOT / ".mise/tasks/ci/_default"

TWO_ITEMS = """\
[items.build-gcc16-coverage]
what = "gcc16-coverage configures and builds"
environment = "linux"
job = "gate-linux-arm64"
preset = "gcc16-coverage"
check = "ci"

[items.must-fail-toolchain-unattested]
what = "toolchain:fetch refuses an unattested release"
environment = "linux"
job = "must-fail"
fixture = "toolchain-unattested"
check = "toolchain:fetch"
"""

GREEN = "gate-linux-arm64 build-gcc16-coverage passed\nmust-fail must-fail-toolchain-unattested passed\n"
GATE_FAILED = "gate-linux-arm64 build-gcc16-coverage failed\n"
GATE_MALFORMED = "gate-linux-arm64 build-gcc16-coverage\n"
GATE_UNKNOWN_STATUS = "gate-linux-arm64 build-gcc16-coverage green\n"
MUST_FAIL_ONLY = "must-fail must-fail-toolchain-unattested passed\n"


def _on_block(text: str) -> str:
    """The top-level `on:` block: from `on:` to the next unindented, non-blank line."""
    lines = text.splitlines()
    start = lines.index("on:")
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0].isspace()):
        end += 1
    return "\n".join(lines[start + 1 : end])


def _job_blocks(text: str) -> dict[str, str]:
    """The `jobs:` block split into per-job sections, keyed by job id."""
    blocks: dict[str, str] = {}
    job: str | None = None
    lines = text.splitlines()
    for line in lines[lines.index("jobs:") + 1 :]:
        m = re.match(r"^  ([a-z0-9-]+):$", line)
        if m:
            job = m.group(1)
            blocks[job] = ""
        elif job is not None:
            blocks[job] += line + "\n"
    return blocks


def _triggers(path: Path) -> list[str]:
    """The trigger names in a workflow's `on:` block, in file order."""
    return re.findall(
        r"^  ([a-z_-]+):", _on_block(path.read_text(encoding="utf-8")), re.MULTILINE
    )


class Triggers(unittest.TestCase):
    """Rule 1: one trigger, a push to main, and no other (the daily schedule ended with D182)."""

    def setUp(self) -> None:
        self.block = _on_block(POST_MERGE.read_text(encoding="utf-8"))

    def test_exactly_a_push_to_main(self) -> None:
        self.assertEqual(_triggers(POST_MERGE), ["push"])
        self.assertRegex(
            self.block,
            re.compile(r"^  push:\n    branches: \[main\]$", re.MULTILINE),
        )

    def test_no_other_trigger(self) -> None:
        for word in ("workflow_dispatch", "pull_request", "merge_group"):
            self.assertNotIn(word, self.block)


class SunsetTriggers(unittest.TestCase):
    """Rule 1, D182: the scheduled workflows lost their schedules and kept workflow_dispatch."""

    def test_apt_bump_runs_only_by_hand(self) -> None:
        self.assertEqual(_triggers(APT_BUMP), ["workflow_dispatch"])

    def test_builder_keeps_its_other_triggers(self) -> None:
        self.assertEqual(
            _triggers(BUILDER),
            ["push", "workflow_dispatch", "pull_request", "merge_group"],
        )

    def test_no_schedule_or_cron(self) -> None:
        for path in (POST_MERGE, APT_BUMP, BUILDER):
            block = _on_block(path.read_text(encoding="utf-8"))
            with self.subTest(workflow=path.name):
                self.assertNotIn("schedule", block)
                self.assertNotIn("cron", block)


class RunnerLabels(unittest.TestCase):
    """Rule 2: the free hosted arm64 runner, never a paid or larger one."""

    def test_every_job_is_on_the_free_hosted_arm_runner(self) -> None:
        text = POST_MERGE.read_text(encoding="utf-8")
        labels = re.findall(r"^    runs-on: (.+)$", text, re.MULTILINE)
        jobs = _job_blocks(text)
        self.assertEqual(
            sorted(jobs),
            [
                "artifact-check",
                "checklist",
                "gate-linux-arm64",
                "must-fail",
                "resolve",
            ],
        )
        self.assertEqual(len(labels), len(jobs), "one runs-on per job")
        for label in labels:
            self.assertEqual(label, "ubuntu-26.04-arm", "a paid or larger runner")


class Checker(unittest.TestCase):
    """Rules 3 and 4: the checker's results JSON and its exit codes."""

    def run_check(
        self, items: str, results: str | None, summary: bool = False
    ) -> tuple[int, dict | None, str | None]:
        """Run the checker on the two texts and return its exit code, the parsed
        JSON or None when it wrote none, and the summary text or None. A None
        results leaves the results file unwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            items_path = d / "gate-items.toml"
            items_path.write_text(items, encoding="utf-8")
            results_path = d / "results.txt"
            if results is not None:
                results_path.write_text(results, encoding="utf-8")
            out_path = d / "out.json"
            argv = [str(items_path), str(results_path), str(out_path)]
            summary_path = d / "summary.md"
            if summary:
                argv += ["--summary", str(summary_path)]
            with contextlib.redirect_stdout(io.StringIO()):
                rc = checklist.main(argv)
            out = (
                json.loads(out_path.read_text(encoding="utf-8"))
                if out_path.exists()
                else None
            )
            text = (
                summary_path.read_text(encoding="utf-8")
                if summary_path.exists()
                else None
            )
            return rc, out, text

    def test_a_missing_result_is_not_run_and_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(TWO_ITEMS, "")
        self.assertNotEqual(rc, 0)
        self.assertEqual(
            [entry["result"] for entry in out["items"]], ["not run", "not run"]
        )

    def test_a_full_green_result_set_passes(self) -> None:
        # The trailing empty line is what a cat'ed fragment leaves behind.
        rc, out, _ = self.run_check(TWO_ITEMS, GREEN + "\n")
        self.assertEqual(rc, 0)
        self.assertEqual(
            [entry["result"] for entry in out["items"]], ["passed", "passed"]
        )

    def test_a_failed_result_is_reported_and_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(TWO_ITEMS, GATE_FAILED)
        self.assertNotEqual(rc, 0)
        self.assertEqual(
            [entry["result"] for entry in out["items"]], ["failed", "not run"]
        )

    def test_a_check_that_did_not_run_is_not_run_while_others_pass(self) -> None:
        rc, out, _ = self.run_check(TWO_ITEMS, MUST_FAIL_ONLY)
        self.assertNotEqual(rc, 0)
        self.assertEqual(
            [entry["result"] for entry in out["items"]], ["not run", "passed"]
        )

    def test_a_malformed_report_line_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(TWO_ITEMS, GATE_MALFORMED)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_unknown_report_status_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(TWO_ITEMS, GATE_UNKNOWN_STATUS)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_a_report_written_twice_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(
            TWO_ITEMS, GREEN + "must-fail must-fail-toolchain-unattested passed\n"
        )
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_unreadable_checklist_fails_the_run(self) -> None:
        rc, out, _ = self.run_check("[items\n", GREEN)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_empty_checklist_fails_the_run(self) -> None:
        rc, out, _ = self.run_check("", GREEN)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_item_without_a_required_field_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(
            TWO_ITEMS.replace('what = "gcc16-coverage configures and builds"\n', ""),
            GREEN,
        )
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_item_with_an_unknown_field_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(
            TWO_ITEMS.replace(
                'check = "ci"\n',
                'check = "ci"\nboss = "no such field"\n',
                1,
            ),
            GREEN,
        )
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_optional_field_that_is_not_a_string_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(
            TWO_ITEMS.replace('preset = "gcc16-coverage"', "preset = 5"),
            GREEN,
        )
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_empty_items_table_fails_the_run(self) -> None:
        rc, out, _ = self.run_check("[items]\n", GREEN)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_item_that_is_not_a_table_fails_the_run(self) -> None:
        rc, out, _ = self.run_check("[items]\nbuild = 1\n", GREEN)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_an_item_of_another_environment_is_skipped(self) -> None:
        macos = """\
[items.build-gcc16-macos]
what = "the macOS gate builds"
environment = "macos"
job = "mac-gate"
check = "ci"

"""
        rc, out, _ = self.run_check(macos + TWO_ITEMS, GREEN)
        self.assertEqual(rc, 0)
        self.assertEqual(
            [entry["id"] for entry in out["items"]],
            ["build-gcc16-coverage", "must-fail-toolchain-unattested"],
        )

    def test_a_checklist_without_a_linux_item_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(
            """\
[items.build-gcc16-macos]
what = "the macOS gate builds"
environment = "macos"
job = "mac-gate"
check = "ci"
""",
            GREEN,
        )
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_a_missing_results_file_fails_the_run(self) -> None:
        rc, out, _ = self.run_check(TWO_ITEMS, None)
        self.assertNotEqual(rc, 0)
        self.assertIsNone(out)

    def test_the_summary_shows_every_item(self) -> None:
        _, _, text = self.run_check(TWO_ITEMS, GREEN, summary=True)
        self.assertIn("## Gate checklist (D119)", text)
        for item_id in ("build-gcc16-coverage", "must-fail-toolchain-unattested"):
            self.assertIn(item_id, text)
        self.assertIn("| build-gcc16-coverage |", text)
        self.assertIn("| passed |", text)

    def test_a_presets_checks_have_independent_results(self) -> None:
        rc, out, _ = self.run_check(
            ITEMS_FILE.read_text(encoding="utf-8"),
            "gate-linux-arm64 build-gcc16-coverage passed\n"
            "gate-linux-arm64 tests-gcc16-coverage failed\n" + MUST_FAIL_ONLY,
        )
        self.assertNotEqual(rc, 0)
        results = {item["id"]: item["result"] for item in out["items"]}
        self.assertEqual(results["build-gcc16-coverage"], "passed")
        self.assertEqual(results["tests-gcc16-coverage"], "failed")
        self.assertEqual(results["coverage-gcc16-coverage"], "not run")
        self.assertEqual(results["must-fail-toolchain-unattested"], "passed")
        self.assertEqual(results["must-fail-toolchain-wrong-hash"], "not run")

    def test_the_real_checklist_passes_a_full_green_run(self) -> None:
        items = tomllib.loads(ITEMS_FILE.read_text(encoding="utf-8"))["items"]
        pairs = {(row["job"], item_id) for item_id, row in items.items()}
        results = "".join(f"{job} {item_id} passed\n" for job, item_id in sorted(pairs))
        rc, out, _ = self.run_check(ITEMS_FILE.read_text(encoding="utf-8"), results)
        self.assertEqual(rc, 0)
        # build, tests and coverage for each of the three M1a presets, plus one
        # item per must-fail fixture.
        self.assertEqual(len(out["items"]), 15)
        self.assertEqual({entry["result"] for entry in out["items"]}, {"passed"})


class Mapping(unittest.TestCase):
    """Rule 5: the checklist and the workflow name the same checks."""

    def setUp(self) -> None:
        self.text = POST_MERGE.read_text(encoding="utf-8")
        self.jobs = _job_blocks(self.text)
        self.items = tomllib.loads(ITEMS_FILE.read_text(encoding="utf-8"))["items"]
        self.expected = tomllib.loads(EXPECTED.read_text(encoding="utf-8"))["fixture"]
        presets = re.search(r"^        preset: \[(.+)\]$", self.text, re.MULTILINE)
        self.matrix_presets = [p.strip() for p in presets.group(1).split(",")]
        default = re.search(
            r"\$\{CPPSTD_GATE_PRESETS:-(.+?)\}", CI_DEFAULT.read_text(encoding="utf-8")
        )
        self.gate_presets = default.group(1).split()

    def _check_task(self, item_id: str, check: str) -> None:
        parts = check.split(":")
        task = (
            ROOT
            / ".mise/tasks"
            / parts[0]
            / ("_default" if len(parts) == 1 else parts[1])
        )
        self.assertTrue(
            task.exists(), f"{item_id}'s check {check} is no mise task at {task}"
        )

    def test_the_workflow_gates_exactly_the_gate_presets(self) -> None:
        self.assertEqual(self.matrix_presets, self.gate_presets)

    def test_every_preset_has_build_tests_and_coverage_items(self) -> None:
        for preset in self.gate_presets:
            for leg in ("build", "tests", "coverage"):
                self.assertIn(f"{leg}-{preset}", self.items)

    def test_every_fixture_has_an_item_naming_its_check(self) -> None:
        for name, fixture in self.expected.items():
            item = self.items.get(f"must-fail-{name}")
            self.assertIsNotNone(item, f"no checklist item for fixture {name}")
            self.assertEqual(item["fixture"], name, name)
            self.assertEqual(item["check"], fixture["check"], name)

    def test_every_item_maps_to_a_job_report_and_check_that_exist(self) -> None:
        for item_id, row in self.items.items():
            self.assertIn(row["environment"], ("linux", "macos"), item_id)
            self.assertIn(row["job"], self.jobs, f"{item_id}: no such job")
            block = self.jobs[row["job"]]
            if "preset" in row:
                self.assertIn(row["preset"], self.matrix_presets, item_id)
                stage = item_id.removesuffix(f"-{row['preset']}")
                command = {
                    "build": 'build "$preset"',
                    "tests": 'test_preset "$preset"',
                    "coverage": 'mise run -q ci:coverage "$preset"',
                }[stage]
                self.assertRegex(block, r"(?m)^          mise run ci$")
                self.assertIn("CPPSTD_GATE_REPORT:", block)
                gate = CI_DEFAULT.read_text(encoding="utf-8")
                self.assertIn(f'run_check "{stage}-$preset" {command}', gate)
                self.assertIn('cmake --build --preset "$1"', gate)
                self.assertIn('ctest --preset "$1" --no-tests=error', gate)
            else:
                fixture = row["fixture"]
                self.assertEqual(item_id, f"must-fail-{fixture}")
                self.assertEqual(row["check"], self.expected[fixture]["check"])
                self.assertRegex(block, r"(?m)^          mise run ci-must-fail$")
                self.assertIn("CPPSTD_GATE_REPORT:", block)
                runner = (ROOT / ".mise/tasks/ci-must-fail").read_text(encoding="utf-8")
                self.assertIn('"$dir/$name/run" </dev/null', runner)
                self.assertIn("must-fail must-fail-%s %s", runner)
            self._check_task(item_id, row["check"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
