#!/usr/bin/env python3
"""Read-only session and token receipt inspector for npm:zcode-app-cli."""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import quote

DEFAULT_DB = Path("~/.zcode/cli/db/db.sqlite")
DEFAULT_ROLLOUT_DIR = Path("~/.zcode/cli/rollout")


def connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{quote(str(db_path.resolve()), safe='/:')}?mode=ro", uri=True
    )
    conn.row_factory = sqlite3.Row
    return conn


def find_session(
    conn: sqlite3.Connection,
    session_id: str | None,
    directory: str | None,
    since: int | None,
) -> dict | None:
    if session_id:
        row = conn.execute(
            "SELECT id, title, directory, time_created, time_updated, last_outcome, version "
            "FROM session WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None
    assert directory is not None
    raw = str(Path(directory).expanduser())
    resolved = str(Path(directory).expanduser().resolve())
    dirs = (raw,) if raw == resolved else (resolved, raw)
    placeholders = ", ".join("?" for _ in dirs)
    params: list[object] = list(dirs)
    clause = f"directory IN ({placeholders})"
    if since is not None:
        clause += " AND time_updated >= ?"
        params.append(since)
    row = conn.execute(
        "SELECT id, title, directory, time_created, time_updated, last_outcome, version "
        f"FROM session WHERE {clause} ORDER BY time_updated DESC LIMIT 1",
        params,
    ).fetchone()
    return dict(row) if row else None


def aggregate_sqlite_usage(
    conn: sqlite3.Connection, session_id: str, warnings: list[str]
) -> dict | None:
    try:
        rows = conn.execute(
            "SELECT provider_id, model_id, variant, mode, status, error_code, "
            "error_message, input_tokens, output_tokens, reasoning_tokens, "
            "cache_read_input_tokens, cache_creation_input_tokens, "
            "provider_total_tokens, computed_total_tokens "
            "FROM model_usage WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    except sqlite3.Error as error:
        warnings.append(f"model_usage unavailable: {error}")
        return None
    if not rows:
        return None
    statuses = Counter(row["status"] for row in rows if row["status"])
    provider_totals = [
        row["provider_total_tokens"]
        for row in rows
        if row["provider_total_tokens"] is not None
    ]
    return {
        "request_count": len(rows),
        "providers": sorted({row["provider_id"] for row in rows if row["provider_id"]}),
        "models": sorted({row["model_id"] for row in rows if row["model_id"]}),
        "variants": sorted({row["variant"] for row in rows if row["variant"]}),
        "modes": sorted({row["mode"] for row in rows if row["mode"]}),
        "statuses": dict(sorted(statuses.items())),
        "error_codes": sorted(
            {str(row["error_code"]) for row in rows if row["error_code"]}
        ),
        "error_messages": sorted(
            {
                row["error_message"].strip()[:240]
                for row in rows
                if isinstance(row["error_message"], str)
                and row["error_message"].strip()
            }
        ),
        "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
        "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
        "reasoning_tokens": sum(row["reasoning_tokens"] or 0 for row in rows),
        "cache_read_input_tokens": sum(
            row["cache_read_input_tokens"] or 0 for row in rows
        ),
        "cache_creation_input_tokens": sum(
            row["cache_creation_input_tokens"] or 0 for row in rows
        ),
        "provider_total_tokens": sum(provider_totals) if provider_totals else None,
        "computed_total_tokens": sum(row["computed_total_tokens"] or 0 for row in rows),
    }


def latest_sqlite_reply(
    conn: sqlite3.Connection, session_id: str, warnings: list[str]
) -> str | None:
    try:
        rows = conn.execute(
            "SELECT m.data AS msg_data, p.data AS part_data "
            "FROM part p JOIN message m ON p.message_id = m.id "
            "WHERE p.session_id = ? "
            "ORDER BY m.time_created DESC, COALESCE(m.sequence, 0) DESC, "
            "p.time_created DESC, COALESCE(p.sequence, 0) DESC",
            (session_id,),
        ).fetchall()
    except sqlite3.Error as error:
        warnings.append(f"message/part unavailable: {error}")
        return None
    for row in rows:
        try:
            msg = json.loads(row["msg_data"])
            part = json.loads(row["part_data"])
        except (TypeError, ValueError):
            continue
        if (
            isinstance(msg, dict)
            and msg.get("role") == "assistant"
            and isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        ):
            return part["text"]
    return None


def read_rollout(
    rollout_dir: Path, session_id: str, warnings: list[str]
) -> tuple[dict | None, str | None]:
    path = rollout_dir / f"model-io-{session_id}.jsonl"
    if not path.is_file():
        return None, None
    requests = 0
    models: set[str] = set()
    error_messages: set[str] = set()
    in_tok = out_tok = cache_rd = cache_wr = total_tok = 0
    last_text: str | None = None
    try:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                warnings.append(f"{path.name}:{line_no} malformed JSONL line skipped")
                continue
            requests += 1
            err = entry.get("error")
            err_msg = err.get("message") if isinstance(err, dict) else err
            if isinstance(err_msg, str) and err_msg.strip():
                error_messages.add(err_msg.strip()[:240])
            resp = (
                entry.get("response") if isinstance(entry.get("response"), dict) else {}
            )
            model = resp.get("modelId") or entry.get("model")
            if isinstance(model, str) and model:
                models.add(model)
            usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
            in_tok += int(usage.get("inputTokens") or 0)
            out_tok += int(usage.get("outputTokens") or 0)
            cache_rd += int(usage.get("cacheReadTokens") or 0)
            cache_wr += int(usage.get("cacheWriteTokens") or 0)
            total_tok += int(usage.get("totalTokens") or 0)
            text = resp.get("text")
            if isinstance(text, str) and text.strip():
                last_text = text
    except OSError as error:
        warnings.append(f"cannot read {path.name}: {error}")
        return None, None
    if requests == 0:
        return None, None
    usage_summary = {
        "request_count": requests,
        "providers": [],
        "models": sorted(models),
        "variants": [],
        "modes": [],
        "statuses": {},
        "error_codes": [],
        "error_messages": sorted(error_messages),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "reasoning_tokens": 0,
        "cache_read_input_tokens": cache_rd,
        "cache_creation_input_tokens": cache_wr,
        "provider_total_tokens": total_tok,
        "computed_total_tokens": total_tok,
    }
    return usage_summary, last_text


def build_receipt(args: argparse.Namespace) -> dict:
    db_path = Path(args.db).expanduser()
    rollout_dir = Path(args.rollout_dir).expanduser()
    warnings: list[str] = []
    session: dict | None = None
    usage: dict | None = None
    reply: str | None = None
    sources: list[str] = []

    if db_path.is_file():
        with connect_ro(db_path) as conn:
            session = find_session(conn, args.session, args.dir, args.since)
            if session:
                usage = aggregate_sqlite_usage(conn, session["id"], warnings)
                if usage:
                    sources.append("sqlite")
                if args.include_reply:
                    reply = latest_sqlite_reply(conn, session["id"], warnings)
    elif not args.session:
        raise ValueError(f"ZCode SQLite database not found: {db_path}")
    else:
        warnings.append(f"ZCode SQLite database not found: {db_path}")

    session_id = session["id"] if session else args.session
    if not session_id:
        raise ValueError("No matching ZCode session found in SQLite.")

    need_rollout = usage is None or (args.include_reply and reply is None)
    if need_rollout:
        rollout_usage, rollout_reply = read_rollout(rollout_dir, session_id, warnings)
        if usage is None and rollout_usage is not None:
            usage = rollout_usage
            sources.append("rollout")
        if args.include_reply and reply is None and rollout_reply is not None:
            reply = rollout_reply
            if "rollout" not in sources:
                sources.append("rollout")

    if session is None and usage is None:
        raise ValueError(
            f"No matching ZCode session or rollout found for {session_id}."
        )

    if session is None:
        session = {"id": session_id}
    if not sources and session:
        sources.append("sqlite")

    receipt: dict[str, object] = {
        "source": "+".join(sources),
        "session": session,
        "usage": usage,
        "warnings": warnings,
    }
    if args.include_reply:
        receipt["last_assistant_text"] = (
            reply[: args.max_reply_chars] if isinstance(reply, str) else None
        )
    return receipt


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--session", help="Exact ZCode session ID (sess_...)")
    target.add_argument("--dir", help="Working directory used by the ZCode session")
    parser.add_argument(
        "--since", type=int, help="Minimum session time_updated epoch ms (with --dir)"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to ZCode db.sqlite")
    parser.add_argument(
        "--rollout-dir",
        default=str(DEFAULT_ROLLOUT_DIR),
        help="Path to ZCode rollout dir",
    )
    parser.add_argument(
        "--include-reply",
        action="store_true",
        help="Include the latest assistant reply text",
    )
    parser.add_argument(
        "--max-reply-chars", type=int, default=4000, help="Truncate included reply text"
    )
    args = parser.parse_args(argv)
    if args.since is not None and not args.dir:
        parser.error("--since requires --dir")
    try:
        print(json.dumps(build_receipt(args), indent=2, sort_keys=True))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Receipt error: {error}\n")


if __name__ == "__main__":
    main()
