"""Verify receipts: the tree /verify examined, its verdict saved against that tree, and the staged tree at commit.

Every tree is written through a copy of the index, so the real index stays byte for byte as it was.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, ValidationError

from . import rounds
from .git import git, top
from .models import (
    Check,
    CommitCheck,
    Finding,
    GitHubCommit,
    Receipt,
    ReceiptStatus,
    Verdict,
    VerifyBegin,
    VerifyCommit,
    VerifyReading,
    VerifyReceipt,
    WorktreeVerify,
)

# Documentation, for the SKIP rule: every changed path must end in one of these.
DOCS = (".md", ".mdx", ".markdown", ".rst", ".adoc")
TRAILER = "Verify-Receipt"


def store() -> Path:
    """Receipts, one file per tree, beside the rounds' lane files in the same state store."""
    return rounds.store().parent / "receipts"


def git_path(name: str) -> Path:
    """A path in this worktree's own git dir: each worktree remembers its own tree."""
    return Path(git("rev-parse", "--path-format=absolute", "--git-path", name).strip())


def tree(*, working: bool) -> str:
    """The staged tree, or with working the tree of the working changes and every untracked, non-ignored file."""
    root = str(top())
    index = git_path("index")
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "index"
        if index.exists():
            # copy2 keeps the index's mtime: git's racy-clean check compares it with each entry's, and a fresh
            # mtime would let a same-size edit made in the index's second pass as unchanged.
            shutil.copy2(index, copy)
        env = {**os.environ, "GIT_INDEX_FILE": str(copy)}
        if working:
            git("-C", root, "add", "--all", env=env)
        return git("-C", root, "write-tree", env=env).strip()


def base() -> str:
    """Where the change starts: its merge-base with origin's default branch, so earlier commits on the branch count;
    HEAD when this clone records no default branch; the empty tree before the first commit."""
    for ask in (("merge-base", "refs/remotes/origin/HEAD", "HEAD"), ("rev-parse", "--verify", "--quiet", "HEAD")):
        try:
            return git(*ask).strip()
        except subprocess.CalledProcessError:
            continue
    return git("hash-object", "-t", "tree", os.devnull).strip()


def changed(examined: str) -> list[str]:
    """Paths that differ between where the change starts and the examined tree."""
    listed = git("diff-tree", "-r", "--no-renames", "--name-only", "-z", base(), examined)
    return [path for path in listed.split("\0") if path]


def state_file() -> Path:
    return git_path("workflowtools-verify.json")


def worktree() -> WorktreeVerify:
    path = state_file()
    return WorktreeVerify.model_validate_json(path.read_text()) if path.exists() else WorktreeVerify()


def remember(state: WorktreeVerify) -> None:
    state_file().write_text(state.model_dump_json() + "\n")


def problem(detail: str) -> Finding:
    return Finding(path=str(state_file()), check=Check.verify, detail=detail)


def begin() -> VerifyBegin:
    examined = tree(working=True)
    remember(worktree().model_copy(update={"begun": examined}))
    return VerifyBegin(kind="verify-begin", tree=examined)


def is_doc(path: str) -> bool:
    return path.lower().endswith(DOCS)


def save(verdict: Verdict) -> BaseModel:
    """Save the verdict against the remembered tree, or say why not: no PASS for content that changed under it."""
    state = worktree()
    if state.begun is None:
        return problem("no tree remembered: run workflowtools verify-receipt before /verify")
    if (examined := tree(working=True)) != state.begun:
        return problem(f"the content changed after {state.begun} was remembered: run verify-receipt and verify again")
    if verdict is Verdict.skip and (code := [path for path in changed(examined) if not is_doc(path)]):
        return problem(f"SKIP needs a documentation-only change; PASS is required for {', '.join(code)}")
    receipt = Receipt(kind="receipt", tree=examined, verdict=verdict, at=rounds.now())
    store().mkdir(parents=True, exist_ok=True)
    (store() / f"{examined}.json").write_text(receipt.model_dump_json() + "\n")
    # Each verdict needs its own remembered tree. A later commit is compared with the last tree that passed; after
    # FAIL or BLOCKED there is none, so an edited commit reads no receipt and never gets the failed tree's trailer.
    passed = verdict in {Verdict.pass_, Verdict.skip}
    remember(WorktreeVerify(begun=None, saved=examined if passed else None))
    return receipt


def receipt(examined: str) -> Receipt | None:
    path = store() / f"{examined}.json"
    return Receipt.model_validate_json(path.read_text()) if path.exists() else None


def commit(options: VerifyCommit) -> CommitCheck:
    """Compare the staged tree with the receipts; report-only, so a mismatch is a line and never a refusal."""
    staged = tree(working=False)
    saved = worktree().saved
    if found := receipt(staged):
        status, verified, verdict = ReceiptStatus.match, staged, found.verdict
        detail = f"the staged tree has a {verdict} receipt"
    elif saved is not None:
        status, verified, verdict = ReceiptStatus.mismatch, saved, None
        detail = f"the staged tree is not {saved}, the tree verified here: run verify-receipt and /verify again"
    else:
        status, verified, verdict = ReceiptStatus.no_receipt, None, None
        detail = "no verify receipt: run verify-receipt before /verify and verify-receipt --verdict after it"
    # A trailer claims a passing verdict: none for FAIL or BLOCKED, none without a receipt. On a mismatch it names the
    # tree that was verified, so a reader sees the commit's own tree differs from it (changed after verification).
    passed = verified is not None and verdict not in {Verdict.fail, Verdict.blocked}
    trailer = f"{TRAILER}: {verified} {options.plan}" if passed else None
    if trailer and options.message_file:
        git("interpret-trailers", "--in-place", "--if-exists", "replace", "--trailer", trailer, options.message_file)
    return CommitCheck(
        kind="verify-commit",
        status=status,
        staged=staged,
        verified=verified,
        verdict=verdict,
        trailer=trailer,
        detail=detail,
    )


def all_receipts() -> dict[str, Receipt]:
    """Every receipt in the store keyed by tree; a store directory not created yet holds none."""
    directory = store()
    if not directory.exists():
        return {}
    found: dict[str, Receipt] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix != ".json":
            continue
        try:
            item = Receipt.model_validate_json(path.read_text())
        except ValidationError:
            msg = f"{path}: not a verify receipt"
            raise ValueError(msg) from None
        found[item.tree] = item
    return found


def trailer_tree(message: str) -> str | None:
    """The verified tree from the commit's Verify-Receipt trailer, or None when absent."""
    parsed = git("interpret-trailers", "--parse", stdin=message)
    prefix = f"{TRAILER.lower()}:"
    values = [line.partition(":")[2].strip() for line in parsed.splitlines() if line.lower().startswith(prefix)]
    if not values:
        return None
    return values[-1].partition(" ")[0]


def read_commit(commit: GitHubCommit, stored: dict[str, Receipt]) -> tuple[VerifyReading, str]:
    """Read one commit against local verify receipts and its Verify-Receipt trailer, first fitting row."""
    commit_tree = commit.commit.tree.sha
    found = stored.get(commit_tree)
    doc_skip = (
        found is not None
        and found.verdict is Verdict.skip
        and commit.files is not None
        and all(is_doc(file.filename) for file in commit.files)
    )
    if found is not None and (found.verdict is Verdict.pass_ or doc_skip):
        return VerifyReading.verified, f"local {found.verdict} receipt for {commit_tree}"
    claimed = trailer_tree(commit.commit.message)
    if claimed is None:
        return VerifyReading.unverified, "no Verify-Receipt trailer"
    if claimed != commit_tree:
        return (
            VerifyReading.unverified,
            f"changed after verification: trailer names {claimed}, commit tree is {commit_tree}",
        )
    if found is not None:
        if found.verdict is Verdict.skip:
            return (
                VerifyReading.unverified,
                f"local SKIP receipt for {commit_tree} is not on a documentation-only change",
            )
        return VerifyReading.unverified, f"local receipt for {commit_tree} is {found.verdict}"
    return (
        VerifyReading.unknown,
        f"commit carries Verify-Receipt for {commit_tree}, but this machine has no receipt for it",
    )


def run(options: VerifyReceipt) -> BaseModel:
    return begin() if options.verdict is None else save(options.verdict)
