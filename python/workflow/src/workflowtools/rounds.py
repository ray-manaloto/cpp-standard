"""Rounds: open, pr and close events in one JSON-lines file per lane, and the report's open-rounds section."""

import fcntl
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError

from . import github, roadmap
from .models import (
    Check,
    ClosedPr,
    CloseEvent,
    Finding,
    OpenEvent,
    OpenRound,
    PrEvent,
    PrRef,
    ReportSection,
    RoundClose,
    RoundEvent,
    RoundOpen,
    RoundPr,
    SectionName,
    Unavailable,
)

EVENT: TypeAdapter[RoundEvent] = TypeAdapter(RoundEvent)
# The lane is the part of a round ID before its first -<8 digits>-; the ID's pattern guarantees one.
DATE = re.compile(r"-\d{8}-")


def store() -> Path:
    """$XDG_STATE_HOME/workflowtools/rounds, else ~/.local/state/workflowtools/rounds."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "workflowtools" / "rounds"


def lane_file(round_id: str) -> Path:
    return store() / f"{DATE.split(round_id, maxsplit=1)[0]}.jsonl"


def read(path: Path) -> list[RoundEvent]:
    """A lane's events; none when the file does not exist yet. Unreadable files and lines raise."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    events = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(EVENT.validate_json(line))
        except ValidationError:
            msg = f"{path} line {number}: not a round event"
            raise ValueError(msg) from None
    return events


def key(event: RoundEvent) -> tuple[str | int, ...]:
    """What makes an event the same event: a replay with this key adds nothing."""
    if isinstance(event, PrEvent):
        return (event.kind, event.round, event.repo, event.number)
    return (event.kind, event.round)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def problem(path: Path, detail: str) -> Finding:
    return roadmap.problem(str(path), detail, Check.rounds)


def stored(events: list[RoundEvent], wanted: tuple[str | int, ...]) -> RoundEvent | None:
    return next((event for event in events if key(event) == wanted), None)


@contextmanager
def locked(path: Path) -> Generator[list[RoundEvent]]:
    """A lane's events, read and then appended to under one exclusive lock, so two runs cannot both pass a check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield read(path)


def append(path: Path, event: RoundEvent) -> RoundEvent:
    with path.open("a") as stream:
        stream.write(event.model_dump_json() + "\n")
    return event


def round_prs(events: list[RoundEvent], round_id: str) -> list[PrEvent]:
    return [event for event in events if isinstance(event, PrEvent) and event.round == round_id]


def state_problem(path: Path, events: list[RoundEvent], round_id: str) -> Finding | None:
    if stored(events, ("open", round_id)) is None:
        return problem(path, f"round {round_id} was never opened")
    if stored(events, ("close", round_id)) is not None:
        return problem(path, f"round {round_id} is closed")
    return None


def open_round(options: RoundOpen) -> BaseModel:
    path = lane_file(options.round)
    opened = OpenEvent(kind="open", round=options.round, at=now())
    with locked(path) as events:
        return stored(events, key(opened)) or append(path, opened)


def add_pr(options: RoundPr) -> BaseModel:
    path = lane_file(options.round)
    event = PrEvent(kind="pr", round=options.round, repo=options.repo, number=options.number, at=now())
    with locked(path) as events:
        if replayed := stored(events, key(event)):
            return replayed
        if found := state_problem(path, events, options.round):
            return found
        # A pull request GitHub cannot read now is refused here: at close it would block the round for good.
        if isinstance(missing := github.head(options.repo, options.number), Unavailable):
            return missing
        return append(path, event)


def close_round(options: RoundClose) -> BaseModel:
    """Record each pull request's head commit now; when GitHub cannot say, write nothing so a retry can."""
    path = lane_file(options.round)
    # The lock is held while GitHub answers, so no pr lands between the heads read and the close written.
    with locked(path) as events:
        # A replay answers from the store before asking GitHub: the head it recorded stays the round's.
        if replayed := stored(events, ("close", options.round)):
            return replayed
        if found := state_problem(path, events, options.round):
            return found
        prs = []
        for pr in round_prs(events, options.round):
            head = github.head(pr.repo, pr.number)
            if isinstance(head, Unavailable):
                return head
            prs.append(ClosedPr(repo=pr.repo, number=pr.number, head=head))
        closed = CloseEvent(
            kind="close", round=options.round, at=now(), sessions=options.session, plan=options.plan, prs=prs
        )
        return append(path, closed)


def all_events() -> list[RoundEvent]:
    """Every lane's events; a store directory not created yet holds none."""
    directory = store()
    if not directory.exists():
        return []
    return [event for path in sorted(directory.iterdir()) if path.suffix == ".jsonl" for event in read(path)]


def open_rounds() -> list[BaseModel]:
    section = SectionName.open_rounds
    try:
        events = all_events()
    # OSError: a file or the directory cannot be read; ValueError: a line is not a round event.
    except (OSError, ValueError) as error:
        return [ReportSection(kind="section", section=section, count=None, unknown=str(error))]
    closed = {event.round for event in events if isinstance(event, CloseEvent)}
    lines: list[BaseModel] = [
        OpenRound(
            kind="open-round",
            round=event.round,
            opened_at=event.at,
            prs=[PrRef(repo=pr.repo, number=pr.number) for pr in round_prs(events, event.round)],
        )
        for event in events
        if isinstance(event, OpenEvent) and event.round not in closed
    ]
    return [*lines, ReportSection(kind="section", section=section, count=len(lines), unknown=None)]


def run(options: RoundOpen | RoundPr | RoundClose) -> BaseModel:
    """The event written or replayed, or why none was: a Finding or an Unavailable."""
    match options:
        case RoundOpen():
            return open_round(options)
        case RoundPr():
            return add_pr(options)
        case _:
            return close_round(options)
