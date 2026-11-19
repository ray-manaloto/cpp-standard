"""pr-create opens a pull request; pr-merge is a lead's self-merge, done only once every gate holds, in one form."""

# The gates are the owner's self-merge ruling's (2026-11-15), as D169 changed it: a repository names its merge gate in
# repotools.toml's [pr-merge] gate, read from origin's default branch, never from the checkout under merge.
# - local-hk, the default (dotfiles): hk check --pr passes on the exact head, then
#   `gh pr merge --merge --match-head-commit <sha>` with the account's noreply address as the merge author, then a wait
#   until it has merged and a check of the merge commit's author.
# - required-checks (cpp-standard): every gate but hk, no local hk run, a wait for the pull request's checks to pass,
#   then `gh pr merge <number> --match-head-commit <sha>`, which puts the pull request in the merge queue; the queue
#   runs the required CI checks and squashes. The author-email workflow on main checks the squash commit's author.
# No review is required (owner ruling, 2026-11-17).

import json
import re
import subprocess
import sys
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from . import process
from .git import git
from .models import GateResult, Merged, PrMerge, PrText, Queued

# The merging account's noreply address (merge-author-noreply ruling): never a personal email on a public repository.
NOREPLY = "1428022+sortakool@users.noreply.github.com"
# A merge queue squashes, and its commit's author is the pull request's author, not --author-email: a pull request an
# agent opened under the cpp-standard-agents App lands with that App's noreply address. Owner ruling 2026-11-18
# (#158): either noreply address is accepted; any other author, a personal email above all, is still refused.
AUTHORS = (NOREPLY, "356338082+cpp-standard-agents[bot]@users.noreply.github.com")
# CodeRabbit appends its release notes to a pull request's body between these markers (seen on dotfiles #720).
BOT_OPEN = "<!-- This is an auto-generated comment: release notes by coderabbit.ai -->"
BOT_CLOSE = "<!-- end of auto-generated comment: release notes by coderabbit.ai -->"
# Where a repository names its merge gate, and the gates it may name; the first is the default.
SETTINGS = "repotools.toml"
LOCAL_HK = "local-hk"
REQUIRED_CHECKS = "required-checks"
# A body's /verify verdict line: PASS, or SKIP followed by its reason (#161, owner ruling 2026-11-18, report-only).
# A line naming verify (any case), then PASS or SKIP in capitals; SKIP's reason is on the same line.
VERDICT = re.compile(r"^.*?\b(?i:verify)\b.*?\b(?:PASS\b|SKIP\b[^\w\n]*\w)", re.MULTILINE)
NO_VERDICT = "repotools pr-create: warning: the body has no /verify verdict line (PASS, or SKIP with its reason)\n"


class Clock:
    """The wait's time: a monotonic now and a sleep. Tests put a clock of their own in CLOCK, so the reads a wait
    makes and the pauses between them do not depend on how fast the machine runs."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


CLOCK = Clock()
# jouet wait's exit code when its --timeout ran out.
JOUET_TIMEOUT = 124
# Reads in a row with no queue entry, after one was seen, that make a dropped pull request.
DROP_READS = 2
# What the wait reads of a pull request. gh fills {owner} and {repo} from the checkout's remote; a number with no
# pull request makes gh exit 1 ("Could not resolve to a PullRequest"), which ends the wait as an error.
READ = (
    "query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) {"
    " pullRequest(number: $number) { merged state mergeQueueEntry { position } mergeCommit { oid } } } }"
)


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, check=True, text=True).stdout


def base() -> str:
    """The branch a pull request goes into: origin's default branch, as this clone recorded it."""
    ref = "refs/remotes/origin/HEAD"
    done = subprocess.run(["git", "symbolic-ref", "--short", ref], capture_output=True, check=False, text=True)
    if done.returncode != 0:
        msg = f"{ref} is not set, so origin's default branch is unknown; run git remote set-head origin --auto"
        raise ValueError(msg)
    return done.stdout.strip().removeprefix("origin/")


def create(text: PrText) -> None:
    """Open the pull request, its body piped to gh as the file's bytes."""
    body = Path(text.body_file).read_bytes()
    command = ["gh", "pr", "create", "--base", base(), "--title", text.title, "--body-file", "-"]
    done = process.run(command, body, capture_stdout=False)
    # The helper always captures stderr; only stdout may be None.
    sys.stderr.write(cast("bytes", done.stderr).decode(errors="replace"))
    # Report-only: the pull request is open either way; a refusal waits for the pilot's count of false alarms.
    if not VERDICT.search(body.decode(errors="replace")):
        sys.stderr.write(NO_VERDICT)


def view(number: int, fields: str) -> dict[str, Any]:
    return json.loads(gh("pr", "view", str(number), "--json", fields))


def shown_body(live: str, given: str) -> bool:
    """Whether GitHub's body is the given one, or it with only CodeRabbit's release-notes block appended after."""
    if live == given:
        return True
    rest = live.removeprefix(given)
    added = rest.strip("\n")
    return (
        rest != live
        and added.startswith(BOT_OPEN)
        and added.endswith(BOT_CLOSE)
        and added.count(BOT_OPEN) == added.count(BOT_CLOSE) == 1
    )


def checks(options: PrMerge, head: str) -> Iterator[tuple[str, str | None]]:
    """Every gate but hk, in order, each as its name and its refusal or None: a clean checkout at head, and an open
    pull request into GitHub's default branch whose head is head, whose title and body are the given ones. Lazy, so a
    merge that stops at the first refusal asks GitHub nothing for a dirty checkout."""
    dirty = "the checkout has changes or untracked files, so hk check --pr would not test the head alone"
    yield "clean", dirty if git("status", "--porcelain") else None
    moved = git("rev-parse", "HEAD").strip() != head
    yield "head", f"this checkout's HEAD moved from {head} while pr-merge ran" if moved else None
    pr = view(options.number, "headRefOid,state,baseRefName,title,body")
    default = default_branch()
    number = f"pull request #{options.number}"
    given = Path(options.body_file).read_bytes().decode()  # bytes: text mode would turn a CRLF body into LF
    refusals = [
        ("open", pr["state"] != "OPEN", f"{number} is {pr['state']}, not open"),
        ("base", pr["baseRefName"] != default, f"{number} goes into {pr['baseRefName']}, not {default}"),
        (
            "pr-head",
            pr["headRefOid"] != head,
            f"{number}'s head is {pr['headRefOid']}, but this checkout's HEAD is {head}",
        ),
        ("title", pr["title"] != options.title, f"{number}'s title on GitHub is not the given title"),
        ("body", not shown_body(pr["body"], given), f"{number}'s body on GitHub is not the given body"),
    ]
    for name, refused, msg in refusals:
        yield name, msg if refused else None


def default_branch() -> str:
    """GitHub's default branch for the repository."""
    return gh("repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name").strip()


def merge_gate(default: str) -> str:
    """The [pr-merge] gate in SETTINGS as origin's default branch has it, so a pull request cannot change its own gate;
    no file, or no table or key in it, means local-hk."""
    ref = f"origin/{default}"
    listed = subprocess.run(["git", "ls-tree", "--name-only", ref, "--", SETTINGS], capture_output=True, check=False)
    if listed.returncode != 0:
        msg = f"{ref} is not in this clone, so its {SETTINGS} cannot be read; run git fetch origin"
        raise ValueError(msg)
    if not listed.stdout.strip():
        return LOCAL_HK
    gate = tomllib.loads(git("show", f"{ref}:{SETTINGS}")).get("pr-merge", {}).get("gate", LOCAL_HK)
    if gate not in (LOCAL_HK, REQUIRED_CHECKS):
        msg = f"{SETTINGS} on {ref} sets [pr-merge] gate = {gate!r}; it takes {LOCAL_HK} or {REQUIRED_CHECKS}"
        raise ValueError(msg)
    return gate


def skipped(default: str) -> str:
    """Why hk does not run under required-checks, naming the setting."""
    return (
        f'{SETTINGS} on origin/{default} sets [pr-merge] gate = "{REQUIRED_CHECKS}": the merge queue\'s required checks'
        " are the gate, so hk check --pr does not run"
    )


def gates(options: PrMerge, head: str) -> None:
    """Refuse at the first gate but hk that fails."""
    for _, refusal in checks(options, head):
        if refusal is not None:
            raise ValueError(refusal)


def hk(head: str) -> str | None:
    """hk check --pr on the checkout, its own output passing through so a failure shows the step that failed."""
    checked = subprocess.run(["hk", "check", "--pr"], check=False).returncode
    return f"hk check --pr failed (exit {checked}) on {head}" if checked != 0 else None


def checks_pass(options: PrMerge, head: str, deadline: float) -> None:
    """Step one of the wait: jouet waits for the pull request's checks on head, within what is left of the limit."""
    left = max(1, int(deadline - CLOCK.now()))
    command = ["jouet", "wait", "ci", str(options.number), "--sha", head, "--timeout", f"{left}s"]
    done = subprocess.run(command, capture_output=True, check=False, text=True)
    if done.returncode != 0:
        said = (done.stdout + done.stderr).strip().splitlines()
        how = f"within the {float(options.time_limit)}s time limit " if done.returncode == JOUET_TIMEOUT else ""
        exit_code = f"(jouet wait ci exit {done.returncode})"
        msg = f"the checks of pull request #{options.number} on {head} did not pass {how}{exit_code}"
        raise ValueError(f"{msg}: {said[-1]}" if said else msg)


def read(number: int) -> dict[str, Any]:
    """The pull request's merged flag, state, queue entry and merge commit, as GitHub has them now."""
    answer = gh(
        "api", "graphql", "-F", "owner={owner}", "-F", "name={repo}", "-F", f"number={number}", "-f", f"query={READ}"
    )
    return json.loads(answer)["data"]["repository"]["pullRequest"]


def landed(options: PrMerge, deadline: float) -> str:
    """Step two of the wait: read the pull request every interval until it has merged, and return its merge commit.

    Passing checks do not mean merged. A missing queue entry alone decides nothing: it is missing for a merged pull
    request and for one not queued yet. Only after a read has shown an entry do reads with none, unmerged, mean the
    queue dropped it, and DROP_READS of them in a row: one read can fall between the entry's removal and the merge.
    The last read is made at the time limit, not one interval before it."""
    number = f"pull request #{options.number}"
    queued = False
    missing = 0
    while True:
        pr = read(options.number)
        if pr["merged"]:
            return pr["mergeCommit"]["oid"]
        if pr["state"] == "CLOSED":
            msg = f"{number} was closed without being merged"
            raise ValueError(msg)
        entry = pr["mergeQueueEntry"]
        if entry is not None:
            queued, missing = True, 0
        elif queued:
            missing += 1
            if missing == DROP_READS:
                msg = f"{number} was dropped from the merge queue: no queue entry and not merged"
                raise ValueError(msg)
        left = deadline - CLOCK.now()
        if left <= 0:
            state = f"still queued at position {entry['position']}" if entry else "open, neither queued nor merged"
            msg = f"{number} did not merge within the {float(options.time_limit)}s time limit; last read: {state}"
            raise ValueError(msg)
        CLOCK.sleep(min(options.interval, left))


def check_only(options: PrMerge, head: str) -> None:
    """Run every gate, hk too, whatever an earlier one said; print each result and merge nothing. Under
    required-checks the hk gate is reported as skipped, with the setting that skips it."""
    results = [GateResult(gate=name, refusal=refusal) for name, refusal in checks(options, head)]
    default = default_branch()
    if merge_gate(default) == REQUIRED_CHECKS:
        results.append(GateResult(gate="hk", refusal=None, skipped=skipped(default)))
    else:
        results.append(GateResult(gate="hk", refusal=hk(head)))
    for result in results:
        sys.stdout.write(result.model_dump_json(exclude_defaults=True) + "\n")
    refused = sum(result.refusal is not None for result in results)
    if refused:
        msg = f"check-only: {refused} of {len(results)} gates refused pull request #{options.number}"
        raise ValueError(msg)


def merge(options: PrMerge) -> None:
    """Refuse at the first gate that fails; merge only after all of them and the pull request's passing checks, wait
    until GitHub has merged it (a merge queue may hold it a while), then check the merge commit's author. With
    check_only, run and report every gate and merge nothing. Under required-checks, after every gate but hk and its
    passing checks, queue it and report it queued."""
    head = git("rev-parse", "HEAD").strip()
    if options.check_only:
        check_only(options, head)
        return
    gates(options, head)
    if merge_gate(default_branch()) == REQUIRED_CHECKS:
        # The required checks pass on head first: a red one fails here, naming it, and gh then queues at once rather
        # than arming an auto-merge on pending checks.
        checks_pass(options, head, CLOCK.now() + options.time_limit)
        # The one form the ruleset allows: the queue picks the squash, so no --merge; its squash takes the pull
        # request's author, so no --author-email. With a merge queue gh enables auto-merge for it, which queues it.
        gh("pr", "merge", str(options.number), "--match-head-commit", head)
        sys.stdout.write(Queued(number=options.number, head_commit=head, merged=False).model_dump_json() + "\n")
        return
    failed = hk(head)
    if failed is not None:
        raise ValueError(failed)
    # hk runs for minutes: the checkout or the pull request may have changed meanwhile, so every gate is
    # checked again. What is left between this and the merge is GitHub's to hold: --match-head-commit refuses a moved
    # head; a retarget or text edit within that last request is not caught.
    gates(options, head)
    deadline = CLOCK.now() + options.time_limit
    checks_pass(options, head, deadline)
    # With a merge queue, gh adds the pull request to it and returns before anything has merged.
    gh("pr", "merge", str(options.number), "--merge", "--match-head-commit", head, "--author-email", NOREPLY)
    commit = landed(options, deadline)
    email = gh("api", f"repos/{{owner}}/{{repo}}/commits/{commit}", "--jq", ".commit.author.email").strip()
    if email not in AUTHORS:
        msg = f"merge commit {commit} has author {email}, not {' or '.join(AUTHORS)}: report it to the owner"
        raise ValueError(msg)
    merged = Merged(number=options.number, merge_commit=commit, author_email=email)
    sys.stdout.write(merged.model_dump_json() + "\n")
