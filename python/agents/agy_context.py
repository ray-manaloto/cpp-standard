"""List what fills an Antigravity CLI (agy) conversation's context: the files agy loads on its own, and the files and
commands its tools pulled in, with token counts.

agy has no command or export for its /context panel, and the panel names no file a tool read, so this rebuilds the
list from agy's discovery paths and the conversation's transcript. The transcript's per-turn token counts are
measured (input + cache read is the context the model saw). Every per-file and per-result size is an estimate:
bytes / 4. Skills count only their frontmatter, since agy loads a skill's name and description until it is used.

Standard library only; run as `python -I agy_context.py` (task `agy:context-files`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

PATH_KEYS = ("Path", "AbsolutePath", "path", "file_path")
WORKSPACE_DIRS = (".agents", ".agent", "_agents", "_agent")
COMMAND_WIDTH = 100


def est(n_bytes: int) -> int:
    """Estimated tokens for n_bytes of text."""
    return (n_bytes + 3) // 4


def frontmatter_bytes(skill_md: Path) -> int:
    """Bytes of a SKILL.md's frontmatter block, or of the whole file when it has none."""
    text = skill_md.read_text(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return len(text[: end + 4].encode())
    return len(text.encode())


def git_root(start: Path) -> Path | None:
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return None


def ancestors(cwd: Path) -> list[Path]:
    """cwd and each parent up to the repository root (only cwd outside a repository)."""
    root = git_root(cwd)
    if root is None:
        return [cwd]
    out = []
    for d in (cwd, *cwd.parents):
        out.append(d)
        if d == root:
            break
    return out


@dataclass
class Discovery:
    entries: list[dict[str, Any]] = field(default_factory=list)
    seen: set[Path] = field(default_factory=set)

    def add(self, kind: str, source: str, path: Path) -> None:
        if not path.is_file():
            return
        real = path.resolve()
        if real in self.seen:
            return
        self.seen.add(real)
        size = frontmatter_bytes(path) if kind == "skill" else path.stat().st_size
        self.entries.append(
            {
                "kind": kind,
                "source": source,
                "path": str(path),
                "bytes": size,
                "est_tokens": est(size),
            }
        )

    def rules_in(self, folder: Path, source: str) -> None:
        for p in sorted(folder.glob("*.md")):
            self.add("rule", source, p)

    def skills_in(self, folder: Path, source: str) -> None:
        for p in sorted(folder.glob("*/SKILL.md")):
            self.add("skill", source, p)


def discover(cwd: Path, gemini: Path, app_dir: Path) -> list[dict[str, Any]]:
    """The rule and skill files agy loads for a session started in cwd, in agy's discovery order."""
    found = Discovery()
    found.add("rule", "global", gemini / "GEMINI.md")
    for d in ancestors(cwd):
        for name in ("AGENTS.md", "GEMINI.md"):
            found.add("rule", "workspace", d / name)
        for wd in WORKSPACE_DIRS:
            found.rules_in(d / wd / "rules", "workspace")
            found.skills_in(d / wd / "skills", "workspace")
    found.rules_in(gemini / "config" / "rules", "global")
    for plugins in (gemini / "config" / "plugins", app_dir / "plugins"):
        for plugin in sorted(p for p in plugins.glob("*") if p.is_dir()):
            found.rules_in(plugin / "rules", f"plugin:{plugin.name}")
            found.skills_in(plugin / "skills", f"plugin:{plugin.name}")
    for folder in (
        gemini / "config" / "skills",
        gemini / "skills",
        gemini / "antigravity" / "skills",
        app_dir / "skills",
        app_dir / "builtin" / "skills",
    ):
        found.skills_in(folder, "global")
    return found.entries


def find_transcript(brain: Path, conversation: str | None) -> Path | None:
    """The full transcript (else the compact one) of a conversation, or of the newest one when none is named."""

    def pick(logs: Path) -> Path | None:
        for name in ("transcript_full.jsonl", "transcript.jsonl"):
            if (logs / name).is_file():
                return logs / name
        return None

    if conversation:
        return pick(brain / conversation / ".system_generated" / "logs")
    candidates = [
        t for t in (pick(p) for p in brain.glob("*/.system_generated/logs")) if t
    ]
    return max(candidates, key=lambda t: t.stat().st_mtime) if candidates else None


def target(args: dict[str, Any]) -> str:
    for key in PATH_KEYS:
        if isinstance(args.get(key), str):
            return args[key]
    if isinstance(args.get("CommandLine"), str):
        return "$ " + " ".join(args["CommandLine"].split())[:COMMAND_WIDTH]
    if args.get("ServerName") or args.get("ToolName"):
        return f"mcp {args.get('ServerName', '')}/{args.get('ToolName', '')}"
    return ""


@dataclass
class Ledger:
    """Tool calls with their result sizes, and each model turn's context, fed one transcript row at a time."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)

    def feed(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Take one row; return the calls whose results it completed and the turn it recorded, as events."""
        events: list[dict[str, Any]] = []
        kind = row.get("type")
        if kind == "PLANNER_RESPONSE":
            if "input_tokens" in row or "cache_read_tokens" in row:
                turn = {
                    "step": row.get("step_index"),
                    "context_tokens": int(row.get("input_tokens", 0))
                    + int(row.get("cache_read_tokens", 0)),
                    "output_tokens": int(row.get("output_tokens", 0)),
                }
                self.turns.append(turn)
                events.append({"event": "turn", **turn})
            for c in row.get("tool_calls") or []:
                call = {
                    "step": row.get("step_index"),
                    "tool": c.get("name", ""),
                    "target": target(c.get("args") or {}),
                    "result_bytes": None,
                    "est_tokens": None,
                }
                self.calls.append(call)
                self.pending.append(call)
        elif kind == "GENERIC" and self.pending:
            call = self.pending.pop(0)
            size = len(str(row.get("content") or "").encode())
            call["result_bytes"], call["est_tokens"] = size, est(size)
            if row.get("truncated_fields"):
                call["truncated"] = True
            events.append({"event": "call", **call})
        return events


def complete_rows(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """The rows of whole lines after byte offset, and the offset past the last whole line. agy may be mid-write, so
    a line without its newline waits for the next read."""
    with path.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    end = chunk.rfind(b"\n") + 1
    return read_rows(chunk[:end].decode(errors="replace").splitlines()), offset + end


def read_rows(lines: list[str]) -> list[dict[str, Any]]:
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def tilde(text: str, home: str) -> str:
    return text.replace(home, "~") if home else text


def report(
    entries: list[dict[str, Any]],
    ledger: Ledger,
    transcript: Path | None,
    capacity: int | None,
    home: str,
) -> dict[str, Any]:
    last = ledger.turns[-1] if ledger.turns else None
    context: dict[str, Any] = {"measured": last is not None}
    if last:
        context.update(tokens=last["context_tokens"], step=last["step"])
        if capacity:
            context.update(
                capacity=capacity,
                percentage=round(100 * last["context_tokens"] / capacity, 2),
            )
    return {
        "transcript": tilde(str(transcript), home) if transcript else None,
        "context": context,
        "auto_loaded": {
            "estimated": True,
            "total_est_tokens": sum(e["est_tokens"] for e in entries),
            "files": [{**e, "path": tilde(e["path"], home)} for e in entries],
        },
        "tool_results": {
            "estimated": True,
            "total_est_tokens": sum(c["est_tokens"] or 0 for c in ledger.calls),
            "calls": [{**c, "target": tilde(c["target"], home)} for c in ledger.calls],
        },
    }


def render(data: dict[str, Any], out: IO[str]) -> None:
    ctx = data["context"]
    out.write(f"Transcript: {data['transcript'] or 'none found'}\n")
    if ctx["measured"]:
        pct = (
            f" of {ctx['capacity']:,} ({ctx['percentage']}%)"
            if "capacity" in ctx
            else ""
        )
        out.write(
            f"Context now: {ctx['tokens']:,} tokens{pct}, measured at step {ctx['step']}\n"
        )
    else:
        out.write("Context now: no model turn recorded yet\n")
    auto = data["auto_loaded"]
    out.write(
        f"\nAuto-loaded files, ~{auto['total_est_tokens']:,} tokens (estimated; skills count frontmatter only)\n"
    )
    for e in auto["files"]:
        out.write(
            f"  {e['kind']:<5} {e['est_tokens']:>7,}  {e['source']:<24} {e['path']}\n"
        )
    tools = data["tool_results"]
    out.write(
        f"\nTool results in context, ~{tools['total_est_tokens']:,} tokens (estimated)\n"
    )
    for c in tools["calls"]:
        out.write(render_call(c))


def render_call(c: dict[str, Any]) -> str:
    size = "pending" if c["est_tokens"] is None else f"{c['est_tokens']:,}"
    mark = " (truncated in transcript)" if c.get("truncated") else ""
    return f"  step {c['step']!s:>5}  {c['tool']:<14} {size:>7}  {c['target']}{mark}\n"


def follow(
    path: Path,
    offset: int,
    ledger: Ledger,
    out: IO[str],
    interval: float,
    polls: int,
    home: str,
) -> None:
    """Print each completed call and each new turn as the transcript grows. polls=0 follows until interrupted."""
    n = 0
    while polls == 0 or n < polls:
        n += 1
        rows, offset = complete_rows(path, offset)
        for row in rows:
            for ev in ledger.feed(row):
                if ev["event"] == "turn":
                    out.write(
                        f"turn  step {ev['step']!s:>5}  context {ev['context_tokens']:,} tokens (measured)\n"
                    )
                else:
                    out.write(render_call({**ev, "target": tilde(ev["target"], home)}))
        out.flush()
        if polls == 0 or n < polls:
            time.sleep(interval)


def main(argv: list[str] | None = None, out: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--conversation", help="conversation ID (default: the newest transcript)"
    )
    parser.add_argument(
        "--transcript", type=Path, help="a transcript file, instead of looking one up"
    )
    parser.add_argument(
        "--cwd", type=Path, default=Path.cwd(), help="folder the agy session started in"
    )
    parser.add_argument("--gemini-home", type=Path, default=Path.home() / ".gemini")
    parser.add_argument(
        "--app-dir",
        type=Path,
        help="agy's app data folder (default: <gemini-home>/antigravity-cli)",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        help="context window in tokens, e.g. 1000000 from /context",
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON instead of text"
    )
    parser.add_argument(
        "--follow", action="store_true", help="keep printing new tool results and turns"
    )
    parser.add_argument("--interval", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--polls", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    app_dir = args.app_dir or args.gemini_home / "antigravity-cli"
    home = str(Path.home())
    transcript = args.transcript or find_transcript(
        app_dir / "brain", args.conversation
    )
    if args.transcript and not args.transcript.is_file():
        print(f"agy-context: no transcript at {args.transcript}", file=sys.stderr)
        return 2
    if args.conversation and transcript is None:
        print(
            f"agy-context: no transcript for conversation {args.conversation}",
            file=sys.stderr,
        )
        return 2

    ledger = Ledger()
    offset = 0
    if transcript:
        rows, offset = complete_rows(transcript, 0)
        for row in rows:
            ledger.feed(row)
    data = report(
        discover(args.cwd.resolve(), args.gemini_home, app_dir),
        ledger,
        transcript,
        args.capacity,
        home,
    )
    if args.json:
        out.write(json.dumps(data, indent=2) + "\n")
    else:
        render(data, out)
    if args.follow and transcript:
        out.write("\nFollowing (Ctrl+C stops):\n")
        try:
            follow(transcript, offset, ledger, out, args.interval, args.polls, home)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
