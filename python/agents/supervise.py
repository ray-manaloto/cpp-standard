"""The tab's command under the same-tab supervisor (#304): run the agent, and each time it exits leaving a resume request, relaunch the same session in this same terminal; without one, become a login shell.

  python -I supervise.py --state DIR --agent claude|codex|agy|opencode [--prompt TEXT] [--name NAME] -- <agent argv...>

The launcher passes the first prompt and the session name as options, never inside the agent argv, so a relaunch is
only the agent argv plus the agent's resume form (claude `--resume <id>`, codex `resume <id>` right after the
program, agy `--conversation <id>`, opencode `--session <id>`), and an argv that ends in `--settings PATH` is never
mistaken for a prompt. The agent runs with every CLAUDE_CODE_* variable stripped from its environment. After each
exit the supervisor consumes `DIR/resume-<HC_TERMINAL_ID>.json`
(`{"session_id": "...", "remote_control_off": false, "request_id": "..."}`): it deletes the file first (a request is
consumed once), appends one record to `DIR/relaunch.jsonl`
(`{"time", "terminal", "session_id", "request_id", "argv", "settings_copy"}`), and relaunches, looping while
requests keep arriving. With `remote_control_off` true (claude only) that one relaunch reads a one-use copy of the
session's settings file (the `--settings PATH` in the argv, else `~/.claude/settings.json`) with only
`"remoteControlAtStartup": false` added; the next relaunch starts from the original argv again, so it reads the
original file, which is never modified. With no request, or an invalid one (the reason is logged), the supervisor
replaces itself with a login shell (`$SHELL`, else /bin/zsh).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

# Each agent's resume form: tokens appended to the argv, or, for codex, the subcommand that sits right after the
# program. The session-name flag is per agent too; only claude's is known, so the other agents take no name.
RESUME = {
    "claude": ("flag", ("--resume",)),
    "codex": ("subcommand", ("resume",)),
    "agy": ("flag", ("--conversation",)),
    "opencode": ("flag", ("--session",)),
}
NAME_FLAG = {"claude": ("-n",)}
FALLBACK_SHELL = "/bin/zsh"
# request_id names the settings copy, so it may not carry a path separator or start with a dot.
REQUEST_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}")


def parse_request(text: str) -> tuple[dict[str, str | bool] | None, str]:
    """The valid request ({session_id, request_id, remote_control_off}), or None with the reason it is not."""
    try:
        data = json.loads(text)
    except ValueError as error:
        return None, f"not JSON: {error}"
    if not isinstance(data, dict):
        return None, f"a JSON {type(data).__name__}, not an object"
    session_id = data.get("session_id")
    request_id = data.get("request_id")
    off = data.get("remote_control_off", False)
    if not isinstance(session_id, str) or not session_id:
        return None, "no session_id string"
    if not isinstance(request_id, str) or not request_id:
        return None, "no request_id string"
    if not REQUEST_ID.fullmatch(request_id):
        return (
            None,
            "request_id has characters other than letters, digits, '.', '_' and '-'",
        )
    if not isinstance(off, bool):
        return None, "remote_control_off is not a bool"
    return (
        {
            "session_id": session_id,
            "request_id": request_id,
            "remote_control_off": off,
        },
        "",
    )


def without_claude_env(env: dict[str, str]) -> dict[str, str]:
    """The environment without every CLAUDE_CODE_* variable, so a child never reads its launcher's session."""
    return {
        name: value
        for name, value in env.items()
        if not name.startswith("CLAUDE_CODE_")
    }


def launch_argv(
    agent: str, argv: list[str], prompt: str | None, name: str | None
) -> list[str]:
    """The first launch: the agent argv, then its name flag (when the agent has one) and the prompt, each only when
    given. No relaunch ever re-adds them, so a resume carries neither the prompt nor the name."""
    out = list(argv)
    if name and agent in NAME_FLAG:
        out += [*NAME_FLAG[agent], name]
    if prompt:
        out.append(prompt)
    return out


def resume_argv(agent: str, argv: list[str], session_id: str) -> list[str]:
    """The relaunch: the agent argv plus the agent's resume form, built fresh from the original argv each time."""
    how, tokens = RESUME[agent]
    if how == "subcommand":
        return [*argv[:1], *tokens, session_id, *argv[1:]]
    return [*argv, *tokens, session_id]


def settings_path(argv: list[str]) -> Path:
    """The session's settings file: the --settings value in the argv, else the user's settings.json."""
    for i, word in enumerate(argv[:-1]):
        if word == "--settings":
            return Path(argv[i + 1])
    return Path.home() / ".claude" / "settings.json"


def with_settings(argv: list[str], path: str) -> list[str]:
    """argv with its --settings value replaced by path, or path appended when there was none."""
    for i, word in enumerate(argv[:-1]):
        if word == "--settings":
            return [*argv[: i + 1], path, *argv[i + 2 :]]
    return [*argv, "--settings", path]


def rc_off_settings(
    argv: list[str], request_id: str, state: Path
) -> tuple[list[str], str | None, str]:
    """argv pointed at a one-use copy of the session's settings file with only `"remoteControlAtStartup": false`
    added: the argv, the copy's path and "" — or the original argv, None and the reason when the copy cannot be
    made. The original file is never written."""
    source = settings_path(argv)
    data: dict[str, object] = {}
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError as error:
        return argv, None, f"{source} cannot be read: {error}"
    if text.strip():
        try:
            loaded = json.loads(text)
        except ValueError as error:
            return argv, None, f"{source} is not JSON: {error}"
        if not isinstance(loaded, dict):
            return argv, None, f"{source} is not a JSON object"
        data = loaded
    data["remoteControlAtStartup"] = False
    copy = state / f"settings-rc-off-{request_id}.json"
    try:
        copy.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError as error:
        return argv, None, f"{copy} cannot be written: {error}"
    return with_settings(argv, str(copy)), str(copy), ""


def take_request(path: Path) -> tuple[dict[str, str | bool] | None, str]:
    """Read and delete the resume request: the valid request and "", or None with the reason (also "" when there is
    no request, an empty file included). Deleting comes before parsing, so a request is consumed once."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ""
    except OSError as error:
        return None, f"{path} cannot be read: {error}"
    try:
        path.unlink()
    except OSError as error:
        return None, f"{path} cannot be deleted: {error}"
    if not text.strip():
        return None, ""
    request, reason = parse_request(text)
    if request is None:
        return None, f"{path}: {reason}"
    return request, ""


def log_event(path: Path, record: dict[str, object]) -> None:
    """Append one JSON line to the relaunch log; a log that cannot be written only notes on stderr."""
    try:
        with open(path, "a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
    except OSError as error:
        sys.stderr.write(f"supervise: {path} cannot be written: {error}\n")


def now() -> str:
    """The local time with its offset, for relaunch.jsonl records."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def become_shell() -> NoReturn:
    """Replace this process with a login shell: the tab's fallback when no resume request is pending."""
    shell = os.environ.get("SHELL") or FALLBACK_SHELL
    try:
        os.execvp(shell, [shell, "-li"])
    except OSError as error:
        sys.exit(f"supervise: cannot become the login shell {shell}: {error}")


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--state",
        required=True,
        help="the tab's state dir: resume requests, relaunch log, settings copies",
    )
    parser.add_argument("--agent", required=True, choices=sorted(RESUME))
    parser.add_argument(
        "--prompt", help="the first prompt, given to the first launch only"
    )
    parser.add_argument(
        "--name", help="the session name, given to the first launch only"
    )
    parser.add_argument(
        "agent_argv",
        nargs="*",
        help="the agent argv, after --; never the prompt or name",
    )
    args = parser.parse_args()
    if not args.agent_argv:
        parser.error("the agent argv after -- is empty")
    return args


def main() -> None:
    args = parse()
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    terminal = os.environ.get("HC_TERMINAL_ID", "")
    requests = state / f"resume-{terminal}.json"
    argv = launch_argv(args.agent, args.agent_argv, args.prompt, args.name)
    while True:
        try:
            subprocess.run(argv, env=without_claude_env(dict(os.environ)), check=False)
        except KeyboardInterrupt:
            pass  # the agent took the interrupt with the terminal; fall through to the request check
        request, reason = take_request(requests)
        if request is None:
            if reason:
                sys.stderr.write(f"supervise: {reason}\n")
                log_event(
                    state / "relaunch.jsonl",
                    {"time": now(), "terminal": terminal, "error": reason},
                )
            become_shell()
        sys.stderr.write(
            f"supervise: resuming {request['session_id']} "
            f"(request {request['request_id']})\n"
        )
        relaunch = resume_argv(args.agent, args.agent_argv, str(request["session_id"]))
        copy: str | None = None
        extra = ""
        if request["remote_control_off"] and args.agent == "claude":
            relaunch, copy, extra = rc_off_settings(
                relaunch, str(request["request_id"]), state
            )
        record: dict[str, object] = {
            "time": now(),
            "terminal": terminal,
            "session_id": request["session_id"],
            "request_id": request["request_id"],
            "argv": relaunch,
            "settings_copy": copy,
        }
        if extra:
            record["error"] = extra
        log_event(state / "relaunch.jsonl", record)
        argv = relaunch


if __name__ == "__main__":
    main()
