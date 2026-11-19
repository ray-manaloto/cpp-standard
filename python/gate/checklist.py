"""The gate checklist checker (D119): gate-items.toml and the run's report lines in, the results
JSON out. post-merge.yml (D119) runs the gate and the must-fail fixtures on every M1a preset after
each push to main and once a day; its jobs report what each check's outcome was, and this script
writes the results JSON — one entry per item, passed / failed / not run — that ticks the checklist
(D119) and, later, review:digest reads. An item whose check did not run is reported "not run",
never passed (spec #133); any item not passed exits non-zero, so the run fails.

A report line is `<job> <item> <passed|failed>`: only a check with an outcome writes a line, so a
skipped or cancelled check has no line and its items come out "not run".

Run: python3 -I python/gate/checklist.py gate-items.toml results.txt gate-results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

# This run's environment (environment-standard.md G7): the linux items are post-merge.yml's to
# tick; an item of another environment, such as a macOS one (D46), belongs to that workflow's run.
ENVIRONMENT = "linux"
# The statuses a report line may carry; the absence of a line is "not run".
REPORTED = ("passed", "failed")
FIELDS = ("what", "environment", "job", "check")
OPTIONAL_FIELDS = ("preset", "fixture")


class ChecklistError(Exception):
    """A checklist or report line this checker refuses."""


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ChecklistError(f"cannot read {path}: {error}") from error


def load_items(path: Path) -> list[dict]:
    """The checklist's linux items, each with its id and validated fields, in file order.

    A malformed checklist, an empty one, or one with no linux item raises: a checklist that
    ticks nothing must not pass silently. Items of another environment are skipped; they are
    that workflow's to tick (G7, D46)."""
    items = _read_toml(path).get("items")
    if not isinstance(items, dict) or not items:
        raise ChecklistError(f"{path} lists no [items] entry")
    rows = []
    for item_id, row in items.items():
        where = f"{path}'s item {item_id}"
        if not isinstance(row, dict):
            raise ChecklistError(f"{where} is not a table")
        for field in FIELDS:
            if not isinstance(row.get(field), str):
                raise ChecklistError(f"{where} has no string {field}")
        for field in OPTIONAL_FIELDS:
            if field in row and not isinstance(row[field], str):
                raise ChecklistError(f"{where} has a non-string {field}")
        unknown = sorted(set(row) - set(FIELDS) - set(OPTIONAL_FIELDS))
        if unknown:
            raise ChecklistError(f"{where} has unknown fields: {', '.join(unknown)}")
        if row["environment"] != ENVIRONMENT:
            continue
        rows.append({"id": item_id, **row})
    if not rows:
        raise ChecklistError(f"{path} lists no {ENVIRONMENT} item")
    return rows


def load_results(path: Path) -> dict[tuple[str, str], str]:
    """The run's report lines as (job, item_id) -> passed or failed."""
    results: dict[tuple[str, str], str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ChecklistError(
                f"{path}:{number} is not <job> <item> <passed|failed>: {line}"
            )
        job, item_id, status = parts
        if status not in REPORTED:
            raise ChecklistError(
                f"{path}:{number} reports {status!r}, not {' or '.join(REPORTED)}"
            )
        if (job, item_id) in results:
            raise ChecklistError(f"{path}:{number} reports {job} {item_id} twice")
        results[(job, item_id)] = status
    return results


def check(items: list[dict], results: dict[tuple[str, str], str]) -> list[dict]:
    """Each item with its result: passed, failed, or not run — a check with no report
    line did not run (spec #133)."""
    rows = []
    for item in items:
        reported = (item["job"], item["id"])
        rows.append({**item, "result": results.get(reported, "not run")})
    return rows


def summary(rows: list[dict]) -> str:
    """The run-summary table: until review:digest exists, the run summary shows the
    checklist (D119)."""
    lines = [
        "## Gate checklist (D119)",
        "",
        "| item | what | check | result |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {row['id']} | {row['what']} | {row['check']} | {row['result']} |"
        for row in rows
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="checklist",
        description="Write the gate checklist's results JSON from the run's report lines (D119).",
    )
    parser.add_argument("items", type=Path, help="the gate-items.toml checklist")
    parser.add_argument(
        "results",
        type=Path,
        help="the run's report lines: '<job> <item> <passed|failed>'",
    )
    parser.add_argument("out", type=Path, help="the results JSON to write")
    parser.add_argument(
        "--summary",
        type=Path,
        help="append the results table to this file (the run summary)",
    )
    args = parser.parse_args(argv)
    try:
        rows = check(load_items(args.items), load_results(args.results))
    except (ChecklistError, OSError) as error:
        print(f"checklist: FAIL {error}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps({"items": rows}, indent=2) + "\n", encoding="utf-8")
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as file:
            file.write(summary(rows))
    for row in rows:
        print(f"checklist: {row['id']} {row['result']}")
    open_items = sum(1 for row in rows if row["result"] != "passed")
    if open_items:
        print(
            f"checklist: FAIL {open_items} of {len(rows)} items not green "
            "(not run or failed; a not-run item never passes, spec #133)"
        )
        return 1
    print(f"checklist: PASS all {len(rows)} items green")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
