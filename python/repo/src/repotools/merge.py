"""pr-create opens a pull request; pr-merge is a lead's self-merge, done only once every gate holds, in one form."""

# The gates are the owner's self-merge ruling's (2026-11-15): local hk check --pr passes on the exact head, then
# `gh pr merge --merge --match-head-commit <sha>` with the account's noreply address as the merge author. No review
# is required (owner ruling, 2026-11-17).

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from . import process
from .git import git
from .models import GateResult, Merged, PrMerge, PrText

# The merging account's noreply address (merge-author-noreply ruling): never a personal email on a public repository.
NOREPLY = "1428022+sortakool@users.noreply.github.com"
# CodeRabbit appends its release notes to a pull request's body between these markers (seen on dotfiles #720).
BOT_OPEN = "<!-- This is an auto-generated comment: release notes by coderabbit.ai -->"
BOT_CLOSE = "<!-- end of auto-generated comment: release notes by coderabbit.ai -->"


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
    default = gh("repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name").strip()
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


def gates(options: PrMerge, head: str) -> None:
    """Refuse at the first gate but hk that fails."""
    for _, refusal in checks(options, head):
        if refusal is not None:
            raise ValueError(refusal)


def hk(head: str) -> str | None:
    """hk check --pr on the checkout, its own output passing through so a failure shows the step that failed."""
    checked = subprocess.run(["hk", "check", "--pr"], check=False).returncode
    return f"hk check --pr failed (exit {checked}) on {head}" if checked != 0 else None


def check_only(options: PrMerge, head: str) -> None:
    """Run every gate, hk too, whatever an earlier one said; print each result and merge nothing."""
    results = [*checks(options, head), ("hk", hk(head))]
    for name, refusal in results:
        sys.stdout.write(GateResult(gate=name, refusal=refusal).model_dump_json() + "\n")
    refused = sum(refusal is not None for _, refusal in results)
    if refused:
        msg = f"check-only: {refused} of {len(results)} gates refused pull request #{options.number}"
        raise ValueError(msg)


def merge(options: PrMerge) -> None:
    """Refuse at the first gate that fails; merge only after all of them, then check the merge commit's author.
    With check_only, run and report every gate and merge nothing."""
    head = git("rev-parse", "HEAD").strip()
    if options.check_only:
        check_only(options, head)
        return
    gates(options, head)
    failed = hk(head)
    if failed is not None:
        raise ValueError(failed)
    # hk runs for minutes: the checkout or the pull request may have changed meanwhile, so every gate is
    # checked again. What is left between this and the merge is GitHub's to hold: --match-head-commit refuses a moved
    # head; a retarget or text edit within that last request is not caught.
    gates(options, head)
    gh("pr", "merge", str(options.number), "--merge", "--match-head-commit", head, "--author-email", NOREPLY)
    commit = view(options.number, "mergeCommit")["mergeCommit"]["oid"]
    email = gh("api", f"repos/{{owner}}/{{repo}}/commits/{commit}", "--jq", ".commit.author.email").strip()
    if email != NOREPLY:
        msg = f"merge commit {commit} has author {email}, not {NOREPLY}: report it to the owner"
        raise ValueError(msg)
    merged = Merged(number=options.number, merge_commit=commit, author_email=email)
    sys.stdout.write(merged.model_dump_json() + "\n")
