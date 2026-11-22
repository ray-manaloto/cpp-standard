"""Check agy_context.py offline: a scratch ~/.gemini, agy app folder, repository and transcripts. It never reads the
real agy folders. Prints one line per case and exits 1 when any fails.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agy_context

FAILS: list[str] = []


def case(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail and not ok else ''}")
    if not ok:
        FAILS.append(name)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


ROWS = [
    {"step_index": 0, "type": "USER_INPUT", "content": "hi"},
    {
        "step_index": 1,
        "type": "PLANNER_RESPONSE",
        "input_tokens": 1000,
        "cache_read_tokens": 200,
        "output_tokens": 30,
        "tool_calls": [
            {"name": "read_file", "args": {"Path": "/w/a.md"}},
            {"name": "run_command", "args": {"CommandLine": "ls   -la\n/w"}},
        ],
    },
    {"step_index": 2, "type": "GENERIC", "content": "x" * 400},
    {"step_index": 3, "type": "GENERIC", "content": "y" * 40, "truncated_fields": ["content"]},
    {
        "step_index": 4,
        "type": "PLANNER_RESPONSE",
        "input_tokens": 50,
        "cache_read_tokens": 1300,
        "output_tokens": 10,
        "tool_calls": [{"name": "call_mcp_tool", "args": {"ServerName": "exa", "ToolName": "fetch"}}],
    },
]


def build(root: Path) -> dict[str, Path]:
    gemini = root / "home" / ".gemini"
    app = gemini / "antigravity-cli"
    repo = root / "repo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "pkg"
    sub.mkdir()
    write(gemini / "GEMINI.md", "g" * 40)
    write(repo / "AGENTS.md", "a" * 80)
    write(sub / "GEMINI.md", "s" * 8)
    write(repo / ".agents" / "rules" / "r.md", "r" * 12)
    write(repo / ".agents" / "skills" / "one" / "SKILL.md", "---\nname: one\ndescription: d\n---\n" + "body" * 100)
    write(gemini / "config" / "rules" / "global.md", "q" * 4)
    write(gemini / "config" / "plugins" / "p1" / "rules" / "AGENTS.md", "p" * 16)
    write(gemini / "config" / "plugins" / "p1" / "skills" / "ps" / "SKILL.md", "no frontmatter")
    write(app / "builtin" / "skills" / "b" / "SKILL.md", "---\nname: b\n")  # unterminated frontmatter
    (gemini / "config" / "skills").mkdir(parents=True)
    (gemini / "config" / "skills" / "linked").symlink_to(repo / ".agents" / "skills" / "one")
    old = write(app / "brain" / "c-old" / ".system_generated" / "logs" / "transcript.jsonl", jsonl(ROWS[:1]))
    os.utime(old, (1, 1))
    write(app / "brain" / "c-new" / ".system_generated" / "logs" / "transcript.jsonl", "compact\n")
    full = write(app / "brain" / "c-new" / ".system_generated" / "logs" / "transcript_full.jsonl", jsonl(ROWS))
    return {"gemini": gemini, "app": app, "repo": repo, "sub": sub, "full": full, "old": old}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        p = build(Path(tmp))
        entries = agy_context.discover(p["sub"], p["gemini"], p["app"])
        names = [(e["kind"], e["source"], Path(e["path"]).name) for e in entries]
        case(
            "discovery order and sources",
            names
            == [
                ("rule", "global", "GEMINI.md"),
                ("rule", "workspace", "GEMINI.md"),
                ("rule", "workspace", "AGENTS.md"),
                ("rule", "workspace", "r.md"),
                ("skill", "workspace", "SKILL.md"),
                ("rule", "global", "global.md"),
                ("rule", "plugin:p1", "AGENTS.md"),
                ("skill", "plugin:p1", "SKILL.md"),
                ("skill", "global", "SKILL.md"),
            ],
            repr(names),
        )
        skill = entries[4]
        case("skill counts frontmatter only", skill["bytes"] == len("---\nname: one\ndescription: d\n---"), repr(skill))
        case("symlinked skill counted once", sum(e["path"].endswith("one/SKILL.md") for e in entries) == 1)
        case("rule estimate is bytes/4", entries[2]["est_tokens"] == 20, repr(entries[2]))
        outside = Path(tmp) / "outside"
        outside.mkdir()
        write(outside / "AGENTS.md", "o")
        case(
            "outside a repository only cwd is searched",
            [e["source"] for e in agy_context.discover(outside, p["gemini"], p["app"])].count("workspace") == 1,
        )

        brain = p["app"] / "brain"
        case("newest conversation, full transcript preferred", agy_context.find_transcript(brain, None) == p["full"])
        case("named conversation, compact fallback", agy_context.find_transcript(brain, "c-old") == p["old"])
        case("missing conversation", agy_context.find_transcript(brain, "nope") is None)
        case("empty brain", agy_context.find_transcript(Path(tmp) / "none", None) is None)

        ledger = agy_context.Ledger()
        for row in ROWS:
            ledger.feed(row)
        calls = ledger.calls
        case("calls paired with results", [c["est_tokens"] for c in calls] == [100, 10, None], repr(calls))
        case("command target collapses spaces", calls[1]["target"] == "$ ls -la /w", repr(calls[1]))
        case("mcp target", calls[2]["target"] == "mcp exa/fetch", repr(calls[2]))
        case("truncated result flagged", calls[1].get("truncated") is True)
        case("turn context is input + cache read", [t["context_tokens"] for t in ledger.turns] == [1200, 1350])
        case("unknown args give empty target", agy_context.target({"x": 1}) == "")

        data = agy_context.report(entries, ledger, p["full"], 2700, tmp)
        case("report context measured with percentage", data["context"] == {
            "measured": True, "tokens": 1350, "step": 4, "capacity": 2700, "percentage": 50.0
        }, repr(data["context"]))
        case("report paths shortened to ~", data["transcript"].startswith("~/"), data["transcript"])
        case("report labels estimates", data["auto_loaded"]["estimated"] and data["tool_results"]["estimated"])
        empty = agy_context.report([], agy_context.Ledger(), None, None, "")
        case("report with no transcript", empty["context"] == {"measured": False} and empty["transcript"] is None)

        out = io.StringIO()
        agy_context.render(data, out)
        text = out.getvalue()
        case("text render", "Context now: 1,350 tokens of 2,700 (50.0%)" in text and "pending" in text
             and "(truncated in transcript)" in text, text)
        out = io.StringIO()
        agy_context.render(empty, out)
        case("text render without turns", "no model turn recorded yet" in out.getvalue())

        partial = write(Path(tmp) / "partial.jsonl", jsonl(ROWS[:2]) + "not json\n" + '{"step_index": 9')
        rows, offset = agy_context.complete_rows(partial, 0)
        case("partial last line waits", len(rows) == 2 and offset == len(jsonl(ROWS[:2]) + "not json\n"))

        live = write(Path(tmp) / "live.jsonl", jsonl(ROWS[:2]))
        lg = agy_context.Ledger()
        r0, off = agy_context.complete_rows(live, 0)
        for row in r0:
            lg.feed(row)
        out = io.StringIO()

        def grow() -> None:
            time.sleep(0.15)
            with live.open("a") as fh:
                fh.write(jsonl(ROWS[2:]))

        t = threading.Thread(target=grow)
        t.start()
        agy_context.follow(live, off, lg, out, 0.1, 6, "")
        t.join()
        followed = out.getvalue()
        case("follow prints new results and turns", followed.count("read_file") == 1 and "context 1,350 tokens" in followed,
             followed)

        argv = ["--cwd", str(p["sub"]), "--gemini-home", str(p["gemini"])]
        out = io.StringIO()
        rc = agy_context.main([*argv, "--json", "--capacity", "2700"], out)
        parsed = json.loads(out.getvalue())
        case("main json", rc == 0 and parsed["context"]["percentage"] == 50.0, out.getvalue()[:200])
        out = io.StringIO()
        rc = agy_context.main([*argv, "--transcript", str(live), "--follow", "--polls", "1", "--interval", "0"], out)
        case("main follow", rc == 0 and "Following" in out.getvalue())
        rc = agy_context.main([*argv, "--transcript", str(Path(tmp) / "gone.jsonl")], io.StringIO())
        case("main missing transcript", rc == 2)
        rc = agy_context.main([*argv, "--conversation", "nope"], io.StringIO())
        case("main missing conversation", rc == 2)

        proc = subprocess.run(
            [sys.executable, "-I", str(HERE / "agy_context.py"), *argv, "--app-dir", str(p["app"])],
            capture_output=True, text=True, timeout=60,
        )
        case("cli text run", proc.returncode == 0 and "Auto-loaded files" in proc.stdout, proc.stderr)

    print(f"{len(FAILS)} failed" if FAILS else "all passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
