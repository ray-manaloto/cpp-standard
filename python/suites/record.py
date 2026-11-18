"""One record per test-suite run: wall time, slowest tests and the 5-minute load at start and end (#186).

  python3 -I record.py run <suite> -- <command> [args...]   run the suite; its output and exit status pass through
  python3 -I record.py report                               each suite's last record, one JSON line per suite
  python3 -I record.py summary                              the same as a Markdown table, for a CI job summary

Standard library only, so it runs on whichever python3 the suite's task has, on the Mac and on CI's Linux runner.
Records live in SUITE_TIMES_DIR, else $XDG_STATE_HOME/cpp-standard/suite-times, else
~/.local/state/cpp-standard/suite-times: one <suite>.json each, written atomically, since hk runs two suites at once.
Recording never changes a run's result: any failure to read the load or write the record is one warning on stderr.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

SUITES = ("repo", "workflow", "pctools")
# pytest's --durations block: its header line, then one line per test until the next section rule.
HEADER = re.compile(r"=+ slowest (?:\d+ )?durations =+")
RULE = re.compile(r"[=-]{3,}")
KEEP = 25


def records_dir() -> Path:
    if os.environ.get("SUITE_TIMES_DIR"):
        return Path(os.environ["SUITE_TIMES_DIR"])
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "cpp-standard" / "suite-times"


def warn(message: str) -> None:
    sys.stderr.write(f"record: warning: {message}; the run's result stands\n")


def load() -> float | None:
    try:
        return round(os.getloadavg()[1], 2)
    except OSError as error:
        warn(f"cannot read the load: {error}")
        return None


class Slowest:
    """Collects the --durations block from the output lines as they pass."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.inside = False

    def feed(self, line: str) -> None:
        # mise's prefix output puts "[task] " before each line.
        text = re.sub(r"^\[[^\]]*\] ", "", line).strip()
        if HEADER.fullmatch(text):
            self.inside, self.lines = True, []
        elif self.inside and RULE.match(text):
            self.inside = False
        elif self.inside and text and len(self.lines) < KEEP:
            self.lines.append(text)


def write(suite: str, record: dict) -> None:
    folder = records_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=folder, prefix=f".{suite}.", delete=False, encoding="utf-8"
    ) as out:
        out.write(json.dumps(record) + "\n")
    Path(out.name).replace(folder / f"{suite}.json")


def run(suite: str, command: list[str]) -> int:
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    load_start = load()
    start = time.monotonic()
    slowest = Slowest()
    try:
        child = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except OSError as error:
        sys.stderr.write(f"record: {command[0]}: {error.strerror}\n")
        return 127 if isinstance(error, FileNotFoundError) else 126
    assert child.stdout is not None
    for raw in child.stdout:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
        slowest.feed(raw.decode(errors="replace"))
    status = child.wait()
    record = {
        "suite": suite,
        "started_at": started_at,
        "wall_s": round(time.monotonic() - start, 1),
        "status": status,
        "load_start": load_start,
        "load_end": load(),
        "slowest": slowest.lines,
    }
    try:
        write(suite, record)
    except OSError as error:
        warn(f"cannot write the {suite} record to {records_dir()}: {error}")
    return status


def last(suite: str) -> dict | None:
    try:
        record = json.loads(
            (records_dir() / f"{suite}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def report() -> None:
    for suite in SUITES:
        sys.stdout.write(
            json.dumps(last(suite) or {"suite": suite, "record": None}) + "\n"
        )


def summary() -> None:
    rows = [
        "| Suite | Wall time | Status | Load start / end | Slowest test |",
        "| --- | --- | --- | --- | --- |",
    ]
    details = []
    for suite in SUITES:
        record = last(suite)
        if record is None:
            rows.append(f"| {suite} | no record | | | |")
            continue
        top = record["slowest"][0] if record.get("slowest") else ""
        rows.append(
            f"| {suite} | {record.get('wall_s')} s | {record.get('status')} "
            f"| {record.get('load_start')} / {record.get('load_end')} | `{top}` |"
        )
        if record.get("slowest"):
            body = "\n".join(record["slowest"])
            details.append(
                f"<details><summary>{suite}: slowest tests</summary>\n\n```text\n{body}\n```\n\n</details>"
            )
    sys.stdout.write(
        "## Test suites\n\n" + "\n".join(rows) + "\n\n" + "\n".join(details) + "\n"
    )


def main(argv: list[str]) -> int:
    if argv[:1] == ["run"] and len(argv) >= 4 and argv[2] == "--":
        return run(argv[1], argv[3:])
    if argv == ["report"]:
        report()
        return 0
    if argv == ["summary"]:
        summary()
        return 0
    sys.stderr.write(__doc__.split("\n\n")[1] + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
