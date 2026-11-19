"""Check supervise.py against #304's acceptance lines, offline: stand-in agent, shell, herdr-app and hc executables
that log their argv and their CLAUDE_CODE_* variables and exit 0, never a real agent. Prints one line per case and
exits 1 when any fails.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I leaves the script's directory off sys.path
import supervise

TERMINAL = "tX"
REQUEST = {"session_id": "sid1", "remote_control_off": False, "request_id": "req1"}
AGAIN = {"session_id": "sid2", "remote_control_off": False, "request_id": "req2"}
SHELL_RUN = ["login-shell", "-li"]
# Every stand-in logs one JSON object per run: its argv and the CLAUDE_CODE_* variables it was given. A claude
# stand-in whose run is a resume copies STANDIN_REQUEST_BODY to STANDIN_REQUEST once (the marker file stops a second
# copy), so the check can make the supervisor loop and can hand it a follow-up request of its own.
STANDIN = """#!{python} -I
import json, os, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["STANDIN_LOG"], "a") as log:
    log.write(json.dumps({{"argv": [name, *sys.argv[1:]],
                          "claude_code": sorted(k for k in os.environ
                                                if k.startswith("CLAUDE_CODE_"))}}) + "\\n")
if name == "claude" and "--resume" in sys.argv[1:]:
    target = os.environ.get("STANDIN_REQUEST")
    body = os.environ.get("STANDIN_REQUEST_BODY")
    marker = os.environ.get("STANDIN_REQUEST_MARKER")
    if target and body and marker and not os.path.exists(marker):
        open(marker, "w").close()
        with open(target, "w") as out:
            out.write(open(body).read())
sys.exit(0)
"""


def run(
    root: Path,
    tag: str,
    argv: list[str],
    agent: str = "claude",
    prompt: str | None = None,
    name: str | None = None,
    request: object | None = None,
    again: dict | None = None,
    cc_env: bool = False,
) -> tuple[int, list[dict], list[dict], Path]:
    """Run supervise.py once: its exit code, the stand-in calls in order, the relaunch.jsonl records, the state dir.
    A supervisor that never reaches the shell fallback (a relaunch loop) is killed at the timeout and fails."""
    state = root / f"state-{tag}"
    log = root / f"calls-{tag}.jsonl"
    log.unlink(missing_ok=True)
    env = {
        "PATH": f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "HC_TERMINAL_ID": TERMINAL,
        "HOME": str(root),
        "SHELL": str(root / "bin" / "login-shell"),
        "STANDIN_LOG": str(log),
        **({"CLAUDE_CODE_FOO": "bar"} if cc_env else {}),
    }
    pending = state / f"resume-{TERMINAL}.json"
    if request is not None:
        state.mkdir(parents=True, exist_ok=True)
        pending.write_text(
            request if isinstance(request, str) else json.dumps(request),
            encoding="utf-8",
        )
    if again is not None:
        body = root / f"again-{tag}.json"
        body.write_text(json.dumps(again), encoding="utf-8")
        env |= {
            "STANDIN_REQUEST": str(pending),
            "STANDIN_REQUEST_BODY": str(body),
            "STANDIN_REQUEST_MARKER": str(root / f"marker-{tag}"),
        }
    supervised = [
        sys.executable,
        "-I",
        str(HERE / "supervise.py"),
        "--state",
        str(state),
        "--agent",
        agent,
        *(["--prompt", prompt] if prompt else []),
        *(["--name", name] if name else []),
        "--",
        *argv,
    ]
    try:
        done = subprocess.run(
            supervised,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        code = done.returncode
    except subprocess.TimeoutExpired:
        code = -99
    calls = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    records = state / "relaunch.jsonl"
    logged = (
        [json.loads(line) for line in records.read_text(encoding="utf-8").splitlines()]
        if records.exists()
        else []
    )
    return code, calls, logged, state


def cases(root: Path) -> list[tuple[str, Callable[[], bool]]]:
    def argvs(calls: list[dict]) -> list[list[str]]:
        return [c["argv"] for c in calls]

    def no_request() -> bool:
        code, calls, records, state = run(root, "plain", ["claude", "--model", "m1"])
        return (
            code == 0
            and argvs(calls) == [["claude", "--model", "m1"], SHELL_RUN]
            and not records
            and not (state / f"resume-{TERMINAL}.json").exists()
            and not any(c["argv"][0] in {"herdr-app", "hc"} for c in calls)
        )

    def claude_request() -> bool:
        settings = root / "settings-claude.json"
        settings.write_text(json.dumps({"env": {"A": "1"}}), encoding="utf-8")
        argv = ["claude", "--model", "m1", "--settings", str(settings)]
        code, calls, records, state = run(
            root,
            "claude1",
            argv,
            prompt="First prompt.",
            name="w1",
            request=REQUEST,
        )
        return (
            code == 0
            and argvs(calls)
            == [
                [*argv, "-n", "w1", "First prompt."],
                [*argv, "--resume", "sid1"],
                SHELL_RUN,
            ]
            and not (state / f"resume-{TERMINAL}.json").exists()
            and len(records) == 1
            and records[0]["terminal"] == TERMINAL
            and records[0]["session_id"] == "sid1"
            and records[0]["request_id"] == "req1"
            and records[0]["argv"] == [*argv, "--resume", "sid1"]
            and records[0]["settings_copy"] is None
            and bool(records[0]["time"])
            and not any(c["argv"][0] in {"herdr-app", "hc"} for c in calls)
        )

    def loop() -> bool:
        argv = ["claude", "--model", "m1"]
        code, calls, records, state = run(
            root, "loop", argv, request=REQUEST, again=AGAIN
        )
        return (
            code == 0
            and argvs(calls)
            == [
                argv,
                [*argv, "--resume", "sid1"],
                [*argv, "--resume", "sid2"],
                SHELL_RUN,
            ]
            and [r["session_id"] for r in records] == ["sid1", "sid2"]
            and [r["request_id"] for r in records] == ["req1", "req2"]
            and not (state / f"resume-{TERMINAL}.json").exists()
        )

    def rc_off_copy() -> bool:
        orig = root / "settings-rc.json"
        orig.write_text(json.dumps({"env": {"A": "1"}}), encoding="utf-8")
        orig_text = orig.read_text(encoding="utf-8")
        argv = ["claude", "--settings", str(orig)]
        code, calls, records, state = run(
            root,
            "rcoff",
            argv,
            request={
                "session_id": "sid1",
                "remote_control_off": True,
                "request_id": "req1",
            },
            again=AGAIN,
        )
        copy = state / "settings-rc-off-req1.json"
        relaunches = argvs(calls)
        copied = json.loads(copy.read_text(encoding="utf-8"))
        return (
            code == 0
            and relaunches[1] == ["claude", "--settings", str(copy), "--resume", "sid1"]
            and relaunches[2] == [*argv, "--resume", "sid2"]
            and copied == {"env": {"A": "1"}, "remoteControlAtStartup": False}
            and orig.read_text(encoding="utf-8") == orig_text
            and records[0]["settings_copy"] == str(copy)
            and records[1]["settings_copy"] is None
        )

    def rc_off_appends_settings() -> bool:
        code, calls, records, state = run(
            root,
            "rcappend",
            ["claude", "--model", "m1"],
            request={
                "session_id": "sid1",
                "remote_control_off": True,
                "request_id": "req1",
            },
        )
        copy = state / "settings-rc-off-req1.json"
        resumed = [
            "claude",
            "--model",
            "m1",
            "--resume",
            "sid1",
            "--settings",
            str(copy),
        ]
        copied = json.loads(copy.read_text(encoding="utf-8"))
        return (
            code == 0
            and argvs(calls) == [["claude", "--model", "m1"], resumed, SHELL_RUN]
            and copied == {"remoteControlAtStartup": False}
            and records[0]["settings_copy"] == str(copy)
        )

    def resume_form(agent: str, program: str, resumed: list[str]) -> bool:
        code, calls, records, _ = run(
            root,
            f"form-{agent}",
            [program, "--model", "m1"],
            agent=agent,
            name="w1",
            request=REQUEST,
        )
        return (
            code == 0
            and argvs(calls) == [[program, "--model", "m1"], resumed, SHELL_RUN]
            and len(records) == 1
        )

    def codex_form() -> bool:
        return resume_form(
            "codex", "codex-hc", ["codex-hc", "resume", "sid1", "--model", "m1"]
        )

    def agy_form() -> bool:
        return resume_form(
            "agy", "agy", ["agy", "--model", "m1", "--conversation", "sid1"]
        )

    def opencode_form() -> bool:
        return resume_form(
            "opencode", "opencode", ["opencode", "--model", "m1", "--session", "sid1"]
        )

    def invalid_request() -> bool:
        code, calls, records, state = run(
            root, "bad", ["claude", "--model", "m1"], request="{not json"
        )
        return (
            code == 0
            and argvs(calls) == [["claude", "--model", "m1"], SHELL_RUN]
            and not (state / f"resume-{TERMINAL}.json").exists()
            and len(records) == 1
            and "not JSON" in str(records[0].get("error", ""))
        )

    def claude_code_stripped() -> bool:
        code, calls, records, _ = run(
            root, "env", ["claude", "--model", "m1"], cc_env=True
        )
        return (
            code == 0
            and argvs(calls) == [["claude", "--model", "m1"], SHELL_RUN]
            and calls[0]["claude_code"] == []
            and not records
        )

    def unit_parse() -> bool:
        good, why = supervise.parse_request(json.dumps(REQUEST))
        none_sid, why_sid = supervise.parse_request('{"request_id": "r"}')
        not_object, why_object = supervise.parse_request("[]")
        bad_json, why_json = supervise.parse_request("{")
        traversal, why_traversal = supervise.parse_request(
            '{"session_id": "s", "request_id": "../x"}'
        )
        expected = {
            "session_id": "sid1",
            "request_id": "req1",
            "remote_control_off": False,
        }
        return (
            good == expected
            and why == ""
            and none_sid is None
            and "session_id" in why_sid
            and not_object is None
            and "not an object" in why_object
            and bad_json is None
            and "not JSON" in why_json
            and traversal is None
            and "request_id" in why_traversal
        )

    def unit_resume() -> bool:
        claude = supervise.resume_argv("claude", ["claude"], "s")
        codex = supervise.resume_argv("codex", ["codex-hc", "--model", "m"], "s")
        empty = supervise.resume_argv("codex", [], "s")
        agy = supervise.resume_argv("agy", ["agy"], "s")
        opencode = supervise.resume_argv("opencode", ["opencode"], "s")
        return (
            claude == ["claude", "--resume", "s"]
            and codex == ["codex-hc", "resume", "s", "--model", "m"]
            and empty == ["resume", "s"]
            and agy == ["agy", "--conversation", "s"]
            and opencode == ["opencode", "--session", "s"]
        )

    def unit_launch_settings_env() -> bool:
        default = Path.home() / ".claude" / "settings.json"
        named = supervise.launch_argv("claude", ["claude"], "P", "w1")
        plain = supervise.launch_argv("claude", ["claude"], None, None)
        codex = supervise.launch_argv("codex", ["codex-hc"], "P", "w1")
        replaced = supervise.with_settings(["claude", "--settings", "a"], "b")
        appended = supervise.with_settings(["claude"], "b")
        found = supervise.settings_path(["claude", "--settings", "s"])
        stripped = supervise.without_claude_env({"CLAUDE_CODE_X": "1", "HC": "t"})
        return (
            named == ["claude", "-n", "w1", "P"]
            and plain == ["claude"]
            and codex == ["codex-hc", "P"]
            and replaced == ["claude", "--settings", "b"]
            and appended == ["claude", "--settings", "b"]
            and found == Path("s")
            and supervise.settings_path(["claude"]) == default
            and stripped == {"HC": "t"}
        )

    return [
        ("no request: the agent ran once, then the login shell", no_request),
        (
            (
                "a claude request: first run has -n and the prompt, the relaunch only --resume, "
                "one record, request consumed, then the shell"
            ),
            claude_request,
        ),
        (
            "a request written again during the relaunch: a third run, each consumed once",
            loop,
        ),
        (
            "remote_control_off: that relaunch reads a one-use copy, the next the original again",
            rc_off_copy,
        ),
        (
            "remote_control_off with no --settings: --settings COPY is appended",
            rc_off_appends_settings,
        ),
        ("codex resumes with the subcommand right after the program", codex_form),
        ("agy resumes with --conversation", agy_form),
        ("opencode resumes with --session", opencode_form),
        (
            "an invalid request is logged with its reason, deleted, then the shell",
            invalid_request,
        ),
        (
            "CLAUDE_CODE_* set in the parent is absent in the child",
            claude_code_stripped,
        ),
        ("parse_request accepts the valid request and refuses the rest", unit_parse),
        ("resume_argv builds each agent's resume form", unit_resume),
        (
            "launch_argv, with_settings, settings_path and without_claude_env",
            unit_launch_settings_env,
        ),
    ]


def main() -> None:
    failed = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch).resolve()
        (root / "bin").mkdir()
        for name in (
            "claude",
            "codex-hc",
            "agy",
            "opencode",
            "hc",
            "herdr-app",
            "login-shell",
        ):
            path = root / "bin" / name
            path.write_text(STANDIN.format(python=sys.executable), encoding="utf-8")
            path.chmod(0o755)
        for name, case in cases(root):
            ok = case()
            failed += not ok
            sys.stdout.write(f"{'ok  ' if ok else 'FAIL'} {name}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
