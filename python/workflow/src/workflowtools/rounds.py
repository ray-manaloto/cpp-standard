"""Rounds: open, pr, close and retro events in one JSON-lines file per lane, and the report's four sections."""

import fcntl
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, TypeAdapter, ValidationError

from . import github, receipts, roadmap
from .models import (
    Check,
    ClosedPr,
    CloseEvent,
    Disposition,
    Finding,
    GitHubPull,
    MergeInNoRound,
    MergeWithoutReceipt,
    OpenEvent,
    OpenRound,
    PrEvent,
    PrRef,
    Receipt,
    Report,
    ReportSection,
    RetroChange,
    RetroEvent,
    RetroOwed,
    RoundClose,
    RoundEvent,
    RoundOpen,
    RoundPr,
    RoundRetro,
    RoundWithoutReceipt,
    SectionName,
    Unavailable,
    VerifyReading,
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


def retro_round(options: RoundRetro) -> BaseModel:
    """Record a closed round's retro; the first one clears the debt, and a replay prints it and writes nothing."""
    path = lane_file(options.round)
    with locked(path) as events:
        if replayed := stored(events, ("retro", options.round)):
            return replayed
        if stored(events, ("open", options.round)) is None:
            return problem(path, f"round {options.round} was never opened")
        if stored(events, ("close", options.round)) is None:
            return problem(path, f"round {options.round} is not closed: close it before its retro")
        dispositions = (
            (Disposition.accepted, options.accepted),
            (Disposition.declined, options.declined),
            (Disposition.later, options.later),
        )
        changes = [
            RetroChange(change=change, disposition=disposition)
            for disposition, given in dispositions
            for change in given
        ]
        given = [change.change for change in changes]
        if twice := sorted({change for change in given if given.count(change) > 1}):
            return problem(path, f"a change has one disposition: {', '.join(twice)}")
        event = RetroEvent(
            kind="retro",
            round=options.round,
            at=now(),
            sources=options.source,
            findings=options.findings,
            findings_at=options.findings_at,
            changes=changes,
        )
        return append(path, event)


def all_events() -> list[RoundEvent]:
    """Every lane's events; a store directory not created yet holds none."""
    directory = store()
    if not directory.exists():
        return []
    return [event for path in sorted(directory.iterdir()) if path.suffix == ".jsonl" for event in read(path)]


def section_end(section: SectionName, lines: list[BaseModel], unknown: str | None = None) -> list[BaseModel]:
    count = None if unknown is not None else len(lines)
    return [*lines, ReportSection(kind="section", section=section, count=count, unknown=unknown)]


def open_rounds(events: list[RoundEvent]) -> list[BaseModel]:
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
    return section_end(SectionName.open_rounds, lines)


def owing_retro(events: list[RoundEvent]) -> list[BaseModel]:
    """Closed rounds with no retro event, each with the inputs its retro starts from."""
    retros = {event.round for event in events if isinstance(event, RetroEvent)}
    lines: list[BaseModel] = [
        RetroOwed(
            kind="retro-owed",
            round=event.round,
            closed_at=event.at,
            sessions=event.sessions,
            plan=event.plan,
            prs=event.prs,
        )
        for event in events
        if isinstance(event, CloseEvent) and event.round not in retros
    ]
    return section_end(SectionName.owing_retro, lines)


def report_repos(events: list[RoundEvent], extra: list[str]) -> list[str]:
    return sorted({*extra, *(event.repo for event in events if isinstance(event, PrEvent))})


def pr_rounds(events: list[RoundEvent]) -> dict[tuple[str, int], list[str]]:
    by_pr: dict[tuple[str, int], list[str]] = {}
    for event in events:
        if isinstance(event, PrEvent):
            by_pr.setdefault((event.repo, event.number), []).append(event.round)
    return by_pr


def closed_pr_heads(events: list[RoundEvent]) -> dict[tuple[str, int], list[tuple[str, str]]]:
    by_pr: dict[tuple[str, int], list[tuple[str, str]]] = {}
    for event in events:
        if isinstance(event, CloseEvent):
            for pr in event.prs:
                by_pr.setdefault((pr.repo, pr.number), []).append((event.round, pr.head))
    return by_pr


def read_receipts() -> tuple[dict[str, Receipt] | None, str | None]:
    try:
        return receipts.all_receipts(), None
    # OSError: a file or the directory cannot be read; ValueError: a file is not a verify receipt.
    except (OSError, ValueError) as error:
        return None, str(error)


def merged_by_repo(repos: list[str]) -> tuple[list[tuple[str, GitHubPull]], str | None]:
    merged: list[tuple[str, GitHubPull]] = []
    errors = []
    for repo in repos:
        result = github.merged_pulls(repo)
        if isinstance(result, Unavailable):
            errors.append(f"{repo}: {result.detail}")
        else:
            merged.extend((repo, pull) for pull in result)
    return merged, "; ".join(errors) or None


def evaluate_commit(
    repo: str,
    sha: str,
    stored_receipts: dict[str, Receipt],
    cache: dict[tuple[str, str], tuple[VerifyReading, str]],
) -> tuple[VerifyReading, str]:
    cached = cache.get((repo, sha))
    if cached is not None:
        return cached
    fetched = github.commit(repo, sha)
    if isinstance(fetched, Unavailable):
        reading = (VerifyReading.unknown, f"could not read commit {sha}: {fetched.detail}")
    else:
        reading = receipts.read_commit(fetched, stored_receipts)
    cache[(repo, sha)] = reading
    return reading


def merged_since(pull: GitHubPull, since: date) -> bool:
    """Whether the pull request merged on or after the date; GitHub gives merged_at in UTC (Z)."""
    return str(pull.merged_at)[:10] >= since.isoformat()


def without_receipt_lines(
    merged: list[tuple[str, GitHubPull]],
    by_pr: dict[tuple[str, int], list[str]],
    closed_by_pr: dict[tuple[str, int], list[tuple[str, str]]],
    stored_receipts: dict[str, Receipt],
    since: date,
) -> list[BaseModel]:
    cache: dict[tuple[str, str], tuple[VerifyReading, str]] = {}
    round_lines: list[BaseModel] = []
    merge_lines: list[BaseModel] = []
    for repo, pull in merged:
        key_pr = (repo, pull.number)
        for round_id, closed_head in closed_by_pr.get(key_pr, ()):
            reading, reason = evaluate_commit(repo, closed_head, stored_receipts, cache)
            if reading is not VerifyReading.verified:
                round_lines.append(
                    RoundWithoutReceipt(
                        kind="round-without-receipt",
                        round=round_id,
                        repo=repo,
                        number=pull.number,
                        head=closed_head,
                        reading=reading,
                        reason=reason,
                    )
                )
        if merged_since(pull, since):
            reading, reason = evaluate_commit(repo, pull.head.sha, stored_receipts, cache)
            if reading is not VerifyReading.verified:
                merge_lines.append(
                    MergeWithoutReceipt(
                        kind="merge-without-receipt",
                        repo=repo,
                        number=pull.number,
                        head=pull.head.sha,
                        merged_at=str(pull.merged_at),
                        rounds=by_pr.get(key_pr, []),
                        reading=reading,
                        reason=reason,
                    )
                )
    return [*round_lines, *merge_lines]


def reconcile(events: list[RoundEvent], extra_repos: list[str], since: date) -> list[BaseModel]:
    stored_receipts, receipt_error = read_receipts()
    merged, listing_unknown = merged_by_repo(report_repos(events, extra_repos))
    by_pr = pr_rounds(events)
    closed_by_pr = closed_pr_heads(events)
    verify_lines = (
        without_receipt_lines(merged, by_pr, closed_by_pr, stored_receipts, since)
        if stored_receipts is not None
        else []
    )
    receipt_unknown = "; ".join(part for part in (receipt_error, listing_unknown) if part) or None
    no_round_lines: list[BaseModel] = [
        MergeInNoRound(
            kind="merge-in-no-round",
            repo=repo,
            number=pull.number,
            head=pull.head.sha,
            merged_at=str(pull.merged_at),
        )
        for repo, pull in merged
        if (repo, pull.number) not in by_pr and merged_since(pull, since)
    ]
    return [
        *section_end(SectionName.without_receipt, verify_lines, receipt_unknown),
        *section_end(SectionName.merges_in_no_round, no_round_lines, listing_unknown),
    ]


def report(options: Report) -> list[BaseModel]:
    """Each section from one read of the store; when it cannot be read, every section is unknown with the reason."""
    try:
        events = all_events()
    # OSError: a file or the directory cannot be read; ValueError: a line is not a round event.
    except (OSError, ValueError) as error:
        return [
            ReportSection(kind="section", section=section, count=None, unknown=str(error)) for section in SectionName
        ]
    return [
        *open_rounds(events),
        *owing_retro(events),
        *reconcile(events, options.repo, date.fromisoformat(options.since)),
    ]


def run(options: RoundOpen | RoundPr | RoundClose | RoundRetro) -> BaseModel:
    """The event written or replayed, or why none was: a Finding or an Unavailable."""
    match options:
        case RoundOpen():
            return open_round(options)
        case RoundPr():
            return add_pr(options)
        case RoundRetro():
            return retro_round(options)
        case _:
            return close_round(options)
