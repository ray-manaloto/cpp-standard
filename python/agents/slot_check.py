"""Check slot.py's refusal paths against #179's acceptance lines, offline: a scratch state directory and stand-in
ssh and docker on PATH (ssh -G maps the alias `pc` to a made-up host; its load comes from STUB_PC_* variables). It never touches the real grant record, the
real ssh config or a Docker daemon. Prints one line per case and exits 1 when any fails.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
STANDIN = """#!{python} -I
import os, sys
name = os.path.basename(sys.argv[0])
if name == "ssh" and sys.argv[1:2] == ["-G"]:
    host = {{"pc": "pc-host.example", "pc-host.example": "pc-host.example"}}.get(sys.argv[2], sys.argv[2])
    print("user dev")
    print("hostname " + host)
elif name == "ssh" and sys.argv[-1] == "cat /proc/loadavg; nproc":
    if os.environ.get("STUB_PC_FAIL"):
        sys.stderr.write("ssh: connect to host pc-host.example port 22: Connection refused\\n")
        sys.exit(255)
    print(f"0.50 {{os.environ.get('STUB_PC_LOAD', '1.00')}} 0.40 2/900 4242")
    print(os.environ.get("STUB_PC_CORES", "16"))
elif name == "docker" and sys.argv[1:3] == ["context", "inspect"]:
    print({{"pcctx": "ssh://dev@pc", "localctx": "unix:///var/run/docker.sock"}}.get(sys.argv[3], ""))
else:
    sys.exit(97)
"""


def slot(
    env: dict[str, str], *args: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(HERE / "slot.py"), *args],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def hook(env: dict[str, str], command: str) -> tuple[int, str]:
    done = slot(
        env,
        "hook",
        stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
    )
    return done.returncode, done.stderr


def cases(env: dict[str, str]) -> list[tuple[str, Callable[[], bool]]]:
    me = env | {"SLOT_HOLDER": "t1", "SLOT_LOAD_LINE": "100000"}
    other = env | {"SLOT_HOLDER": "t2", "SLOT_LOAD_LINE": "100000"}
    nobody = {
        k: v for k, v in env.items() if k not in {"SLOT_HOLDER", "HC_TERMINAL_ID"}
    }
    # A folder with docker but no ssh (main makes it): the hook must block when it cannot resolve a host.
    no_ssh = str(Path(env["XDG_STATE_HOME"]).parent / "bin-no-ssh")

    records = Path(env["XDG_STATE_HOME"]) / "slots"
    mac_record, pc_record = records / "grant.json", records / "grant-pc.json"

    def clear() -> None:
        """No grant on either host."""
        mac_record.unlink(missing_ok=True)
        pc_record.unlink(missing_ok=True)

    def granted(minutes: str = "30", host: str = "mac", holder: str = "t1") -> None:
        """Only this grant, on this host."""
        clear()
        also(host, holder, minutes)

    def also(host: str, holder: str = "t1", minutes: str = "30") -> int:
        """One more grant beside what is held."""
        return slot(
            env, "grant", "cpp-standard", holder, "--minutes", minutes, "--host", host
        ).returncode

    def grant_cycle() -> bool:
        clear()
        first = slot(env, "grant", "cpp-standard", "t1").returncode
        second = slot(env, "grant", "cpp-standard", "t2").returncode
        released = slot(me, "release").returncode
        return (first, second, released) == (0, 1, 0) and not mac_record.exists()

    def refused(
        run_env: dict[str, str],
        words: str,
        setup: Callable[[], None] | None = None,
        *args: str,
    ) -> bool:
        clear()
        if setup:
            setup()
        done = slot(run_env, "check", *args)
        return done.returncode == 1 and words in done.stderr

    def two_holders(first: str, second: str) -> bool:
        """One holder on each host, each passing its own check and refused on the other's."""
        clear()
        made = (also(first, "t1"), also(second, "t2"))
        passes = [
            slot(run_env, "check", "--host", host).returncode
            for run_env, host in ((me, first), (other, second), (me, second))
        ]
        return made == (0, 0) and passes == [0, 0, 1]

    def blocked(run_env: dict[str, str], command: str, *words: str) -> bool:
        code, err = hook(run_env, command)
        return code == 2 and all(word in err for word in words)

    def clears_both() -> bool:
        clear()
        also("mac", "t1", "0")
        also("pc", "t2", "0")
        out = slot(env, "clear-expired").stdout
        return (
            "t1's expired mac grant" in out
            and "t2's expired pc grant" in out
            and not mac_record.exists()
            and not pc_record.exists()
        )

    def release_pc_only() -> bool:
        clear()
        also("mac")
        also("pc")
        done = slot(me, "release", "--host", "pc").returncode
        return done == 0 and mac_record.exists() and not pc_record.exists()

    def release_names_other() -> bool:
        """A bare release by the PC's holder must not read as done while the pc grant stays held."""
        granted(host="pc")
        done = slot(me, "release")
        return (
            done.returncode == 1 and "--host pc" in done.stderr and pc_record.exists()
        )

    def old_record() -> bool:
        """A record written before #194 has no host and sits in grant.json: it is the Mac's grant."""
        clear()
        records.mkdir(parents=True, exist_ok=True)
        mac_record.write_text(
            json.dumps(
                {
                    "lane": "cpp-standard",
                    "holder": "t1",
                    "granted_at": "2026-11-18T00:00:00Z",
                    "expires_at": "2999-01-01T00:00:00Z",
                }
            )
        )
        mac = slot(me, "check").returncode
        on_pc = slot(me, "check", "--host", "pc")
        return (mac, on_pc.returncode) == (
            0,
            1,
        ) and "holds only the mac grant" in on_pc.stderr

    # The Mac's line at 0: a PC case that passes was measured against the PC's load, not this machine's.
    mac_busy = me | {"SLOT_LOAD_LINE": "0"}

    def pc(command: str, extra: dict[str, str] | None = None, words: str = "") -> bool:
        """The hook on PC work with the pc grant: allowed when words is empty, else blocked with words in the reason."""
        granted(host="pc")
        code, err = hook(mac_busy | (extra or {}), command)
        return (code, words in err) == (2, True) if words else code == 0

    def aim(command: str, extra: dict[str, str] | None = None) -> list[int]:
        """The hook's exit code for one command with no grant, only the mac grant, only the pc grant, and both."""
        codes = []
        for hosts in ((), ("mac",), ("pc",), ("mac", "pc")):
            clear()
            for host in hosts:
                also(host)
            codes.append(hook(me | (extra or {}), command)[0])
        return codes

    def aims(
        want: list[int], *commands: str, extra: dict[str, str] | None = None
    ) -> bool:
        return all(aim(command, extra) == want for command in commands)

    def current_context(name: str) -> None:
        config = Path(env["DOCKER_CONFIG"])
        config.mkdir(parents=True, exist_ok=True)
        (config / "config.json").write_text(json.dumps({"currentContext": name}))

    def with_context(name: str, check: Callable[[], bool]) -> bool:
        current_context(name)
        try:
            return check()
        finally:
            (Path(env["DOCKER_CONFIG"]) / "config.json").unlink()

    def keeps_live() -> bool:
        """clear-expired and another holder's release both leave a live grant; an expired one is nobody's."""
        granted(host="pc")
        cleared = slot(env, "clear-expired").stdout
        taken = slot(other, "release", "--host", "pc")
        live = pc_record.exists()
        granted("0", host="pc")
        return (
            "nothing expired" in cleared
            and taken.returncode == 1
            and "t1's, not t2's" in taken.stderr
            and live
            and "holds only" not in slot(me, "check").stderr
        )

    def clears_past_bad() -> bool:
        """An unreadable mac record does not keep clear-expired from the PC's expired grant."""
        granted("0", host="pc")
        mac_record.write_text("{not json")
        done = slot(env, "clear-expired")
        cleared = not pc_record.exists()
        mac_record.unlink()
        return (
            done.returncode == 1 and cleared and "t1's expired pc grant" in done.stdout
        )

    def no_holder() -> bool:
        """A record without a holder is unreadable, not a grant to None."""
        clear()
        records.mkdir(parents=True, exist_ok=True)
        pc_record.write_text("{}")
        done = slot(me, "check", "--host", "pc")
        pc_record.unlink()
        return done.returncode == 1 and "has no holder" in done.stderr

    here, there, both = [2, 0, 2, 0], [2, 2, 0, 0], [2, 2, 2, 0]
    at_pc = {"DOCKER_HOST": "ssh://pc"}

    return [
        ("grant, second grant fails, release clears", grant_cycle),
        (
            "no grant: refused, naming the coordinator",
            lambda: refused(me, "chief-of-staff"),
        ),
        (
            "grant for another holder: refused",
            lambda: refused(other, "granted to t1", granted),
        ),
        (
            "expired grant: refused",
            lambda: refused(me, "expired", lambda: granted("0")),
        ),
        (
            "load at the line: refused, with the load",
            lambda: refused(me | {"SLOT_LOAD_LINE": "0"}, "5-minute load", granted),
        ),
        (
            "no holder outside herdr: refused",
            lambda: refused(nobody, "set SLOT_HOLDER", granted),
        ),
        (
            "valid grant below the line: allowed",
            lambda: (granted(), slot(me, "check").returncode == 0)[1],
        ),
        (
            "hook: ssh pc docker run, PC load under 0.75 x cores: allowed",
            lambda: pc("ssh -o BatchMode=yes pc 'docker run --rm x'"),
        ),
        (
            "hook: DOCKER_HOST=ssh://pc build at 0.75 x cores: blocked at the start line",
            lambda: pc(
                "DOCKER_HOST=ssh://pc docker build .",
                {"STUB_PC_LOAD": "12.00"},
                "PC's (16 cores) 5-minute load is 12.0, at or over the start line 12; the pause line is 14.4",
            ),
        ),
        (
            "hook: -H at the PC over 0.9 x cores: blocked, over the pause line",
            lambda: pc(
                "docker -H ssh://dev@pc run x",
                {"STUB_PC_LOAD": "15.00"},
                "over the pause line 14.4",
            ),
        ),
        (
            "hook: --context at the PC, ssh fails: blocked with ssh's reason",
            lambda: pc(
                "docker --context pcctx compose up -d",
                {"STUB_PC_FAIL": "1"},
                "Connection refused",
            ),
        ),
        (
            "hook: env DOCKER_HOST at the PC, no grant: blocked",
            lambda: (
                clear(),
                "chief-of-staff"
                in hook(me | {"DOCKER_HOST": "ssh://pc"}, "docker run x")[1],
            )[1],
        ),
        (
            "hook: --privileged at the PC with a grant: blocked",
            lambda: pc(
                "ssh pc 'docker run --privileged x'",
                words="--privileged container on the PC",
            ),
        ),
        (
            "hook: --privileged=1 at the PC with a grant: blocked",
            lambda: pc(
                "DOCKER_HOST=ssh://pc docker run --privileged=1 x",
                words="--privileged container",
            ),
        ),
        (
            "hook: local and PC work in one command: the Mac's load checked too",
            lambda: (
                granted(host="pc"),
                also("mac"),
                blocked(
                    mac_busy, "docker run a && ssh pc docker run b", "5-minute load is"
                ),
            )[2],
        ),
        (
            "hook: local and PC work in one command with only the pc grant: blocked, naming the mac grant",
            lambda: pc(
                "docker run a && ssh pc docker run b", words="no mac slot grant"
            ),
        ),
        (
            "a mac grant and a pc grant, two holders: both held, each for its own host",
            lambda: two_holders("mac", "pc"),
        ),
        (
            "a pc grant and a mac grant, the holders swapped: both held",
            lambda: two_holders("pc", "mac"),
        ),
        (
            "hook: PC work with only the mac grant: blocked, naming the pc grant",
            lambda: (
                granted(),
                blocked(
                    me,
                    "ssh pc 'docker run --rm x'",
                    "no pc slot grant",
                    "t1 holds only the mac grant",
                ),
            )[1],
        ),
        (
            "hook: Mac work with only the pc grant: blocked, naming the mac grant",
            lambda: (
                granted(host="pc"),
                blocked(
                    me,
                    "docker run --rm alpine true",
                    "no mac slot grant",
                    "t1 holds only the pc grant",
                ),
            )[1],
        ),
        (
            "hook: PC work, the pc grant is another holder's: blocked, naming both",
            lambda: (
                granted(host="pc", holder="t2"),
                also("mac"),
                blocked(
                    me,
                    "DOCKER_HOST=ssh://pc docker run x",
                    "the pc slot is granted to t2, not t1",
                    "holds only the mac grant",
                ),
            )[2],
        ),
        ("clear-expired clears an expired grant on each host", clears_both),
        ("release --host pc leaves the mac grant", release_pc_only),
        (
            "release without --host by the PC's holder: refused, naming --host pc",
            release_names_other,
        ),
        ("a record from before the per-host grants: the mac grant", old_record),
        (
            "check --host pc with no DOCKER_HOST: the pc grant and the PC's load",
            lambda: (
                granted(host="pc"),
                "the PC's (16 cores) load 1.0 < 12"
                in slot(mac_busy, "check", "--host", "pc").stdout,
            )[1],
        ),
        (
            "check --host mac with DOCKER_HOST at the PC and the mac grant: refused, the PC is the target",
            lambda: refused(
                me | {"DOCKER_HOST": "ssh://pc"},
                "Docker here is aimed at the PC",
                granted,
                "--host",
                "mac",
            ),
        ),
        (
            "hook: ssh missing, so the target is unknown: blocked",
            lambda: (
                granted(),
                hook(me | {"PATH": no_ssh}, "DOCKER_HOST=ssh://pc docker run x")[0]
                == 2,
            )[1],
        ),
        (
            "hook: --cap-add=ALL at the PC with a grant: blocked",
            lambda: pc(
                "DOCKER_HOST=ssh://pc docker run --cap-add=ALL x",
                words="--privileged container",
            ),
        ),
        (
            "hook: one --device at the PC with a grant: allowed",
            lambda: pc("DOCKER_HOST=ssh://pc docker run --device /dev/fuse x"),
        ),
        (
            "hook: docker ps at the PC: untouched",
            lambda: hook(nobody | {"DOCKER_HOST": "ssh://pc"}, "docker ps")[0] == 0,
        ),
        (
            "task check with DOCKER_HOST at the PC: the PC's load",
            lambda: (
                granted(host="pc"),
                "the PC's (16 cores) load 1.0 < 12"
                in slot(mac_busy | {"DOCKER_HOST": "ssh://pc"}, "check").stdout,
            )[1],
        ),
        (
            "hook: docker run with no grant: blocked",
            lambda: (
                clear(),
                hook(me, "docker run --rm alpine true")[0] == 2,
            )[1],
        ),
        (
            "hook: docker run with a grant: allowed",
            lambda: (granted(), hook(me, "docker run --rm alpine true")[0] == 0)[1],
        ),
        (
            "hook: non-docker commands untouched",
            lambda: hook(nobody, "ls -la && make build")[0] == 0,
        ),
        (
            "hook: a quoted remote command with more than one command is PC work",
            lambda: aims(
                there,
                "ssh pc 'cd /x && docker run y'",
                "ssh pc 'cd /x; docker build .'",
                "ssh pc 'docker pull x | cat; docker run y'",
                'ssh pc "docker pull x && docker run y"',
                "ssh pc '\ndocker run x\n'",
                "ssh pc 'bash -lc \"docker compose up -d\"'",
            ),
        ),
        (
            "hook: a here-document sent to ssh is PC work",
            lambda: aims(there, "ssh pc bash -s <<'EOF'\ndocker run x\nEOF"),
        ),
        (
            "hook: a here-document belongs to the command that opened it",
            lambda: aims(
                there, "ssh pc bash -s <<EOF && echo sent\ndocker run x\nEOF\nls"
            ),
        ),
        (
            "hook: docker run in a subshell or a command substitution is seen",
            lambda: aims(here, "(docker run x)", "echo $(docker run x)"),
        ),
        (
            "hook: docker run in a loop, an if or a group is seen",
            lambda: aims(
                here,
                "for i in 1 2; do docker run x; done",
                "if true; then docker run x; fi",
                "if ! docker run x; then :; else docker run y; fi",
                "while ! docker run x; do :; done",
                "{ docker run x; }",
            ),
        ),
        (
            "hook: ssh to the PC in a loop is PC work",
            lambda: aims(there, "for i in 1 2; do ssh pc docker run x; done"),
        ),
        (
            "hook: a here-string is not a here-document",
            lambda: aims(here, "cat <<< 'x'\ndocker run x"),
        ),
        (
            "hook: ssh by its path is PC work",
            lambda: aims(there, "/usr/bin/ssh pc docker run x"),
        ),
        (
            "hook: a target set by an earlier command is seen",
            lambda: aims(
                there,
                "export DOCKER_HOST=ssh://pc && docker run x",
                "export DOCKER_HOST=ssh://pc; docker run x",
                "export DOCKER_HOST=ssh://pc\ndocker run x",
                "DOCKER_HOST=ssh://pc; docker run x",
                "export DOCKER_CONTEXT=pcctx && docker build .",
                "docker context use pcctx && docker run x",
            ),
        ),
        (
            "hook: attached short options are read",
            lambda: aims(
                there,
                "docker -Hssh://pc run x",
                "docker -H=ssh://pc run x",
                "docker -cpcctx run x",
                "docker compose --context pcctx up",
            ),
        ),
        (
            "hook: the current docker context at the PC is PC work",
            lambda: with_context("pcctx", lambda: aims(there, "docker run x")),
        ),
        (
            "check with the current docker context at the PC: the pc grant",
            lambda: with_context(
                "pcctx",
                lambda: (
                    granted(host="pc"),
                    "may start on pc" in slot(mac_busy, "check").stdout,
                )[1],
            ),
        ),
        (
            "hook: words after the docker subcommand do not aim it",
            lambda: aims(
                here,
                "docker run -e DOCKER_HOST=ssh://pc img",
                "docker build --build-arg DOCKER_CONTEXT=pcctx .",
                "docker run img ssh pc docker ps",
                "docker run -c 512 img",
                "docker run -h pc img",
            ),
        ),
        (
            "hook: a target cleared or overridden in the command is Mac work",
            lambda: aims(
                here,
                "DOCKER_HOST= docker run x",
                "unset DOCKER_HOST; docker run x",
                "docker --context localctx run x",
                "docker -H unix:///var/run/docker.sock run x",
                extra=at_pc,
            ),
        ),
        (
            "hook: --context and DOCKER_CONTEXT in the command beat an inherited DOCKER_CONTEXT",
            lambda: aims(
                here,
                "docker --context localctx run x",
                "DOCKER_CONTEXT=localctx docker run x",
                extra={"DOCKER_CONTEXT": "pcctx"},
            ),
        ),
        (
            "hook: DOCKER_HOST beats DOCKER_CONTEXT, as in the docker CLI",
            lambda: aims(
                here,
                "DOCKER_HOST=unix:///var/run/docker.sock docker run x",
                extra={"DOCKER_CONTEXT": "pcctx"},
            ),
        ),
        (
            "hook: work in both places needs both grants",
            lambda: aims(
                both,
                "docker run a && ssh pc docker run b",
                "docker run a; DOCKER_HOST=ssh://pc docker run b",
            ),
        ),
        (
            "hook: quoting that cannot be read around docker: blocked",
            lambda: (
                also("mac"),
                also("pc"),
                blocked(me, "ssh pc 'docker run x", "cannot read"),
            )[2],
        ),
        (
            "hook: a comment with an apostrophe before docker run is read",
            lambda: aims(here, "# don't skip this\ndocker run x"),
        ),
        (
            "hook: a wrapper's own options do not hide the container start",
            lambda: aims(
                there,
                "caffeinate -i docker build .",
                "timeout -k 5 600 docker run x",
                "sudo -E docker run x",
                "nice -n 5 docker run x",
                "echo a | xargs -n 1 docker run",
                "for i in 1 2; do timeout 5 docker run x; done",
                extra=at_pc,
            ),
        ),
        (
            "hook: env -u and env -i clear the inherited target",
            lambda: aims(
                here,
                "env -u DOCKER_HOST docker run x",
                "env -i docker run x",
                extra=at_pc,
            ),
        ),
        (
            "hook: text given to a shell or eval is read as a command",
            lambda: aims(
                there,
                "bash -lc 'cd x && docker run y'",
                "eval 'docker run x'",
                "bash <<EOF\ndocker run x\nEOF",
                "bash -c 'ssh pc \"cd a && docker run x\"'",
                extra=at_pc,
            ),
        ),
        (
            "hook: a here-document that is not a command: untouched",
            lambda: all(
                hook(nobody, command)[0] == 0
                for command in (
                    "git commit -F - <<'EOF'\ndocker run x\nEOF",
                    "bash script.sh <<EOF\ndocker run x\nEOF",
                )
            ),
        ),
        (
            "hook: lines after a here-document or a shift are still read",
            lambda: aims(
                here,
                "echo $((1<<2))\ndocker run x",
                "cat <<\\EOF\nhi\nEOF\ndocker run x",
            ),
        ),
        (
            "hook: a here-document that never closes before docker: blocked",
            lambda: (
                also("mac"),
                also("pc"),
                blocked(me, "cat <<EOF\nnever\ndocker run x", "cannot read"),
            )[2],
        ),
        (
            "hook: text piped to ssh or a shell is read as its command",
            lambda: (
                aims(
                    there,
                    "cat <<EOF | ssh pc bash\ndocker run x\nEOF",
                    "echo 'docker run x' | ssh pc bash",
                )
                and aims(here, "echo 'docker run x' | bash")
                and hook(nobody, "echo 'docker run x'; ssh pc ls")[0] == 0
            ),
        ),
        (
            "hook: function, coproc, builtin, stdbuf, mise x and tailscale ssh are seen through",
            lambda: aims(
                there,
                "function f { docker run x; }; f",
                "time -p docker run x",
                "coproc docker run x",
                "builtin command docker run x",
                "stdbuf -oL docker run x",
                "timeout --foreground 60 docker run x",
                "mise x -- docker run x",
                "tailscale ssh pc docker run x",
                extra=at_pc,
            ),
        ),
        (
            "hook: declare -x, a bare host:port and other endpoint spellings aim at the PC",
            lambda: aims(
                there,
                "declare -x DOCKER_HOST=ssh://pc; docker run x",
                "DOCKER_HOST=pc:2375 docker run x",
                "docker -H pc:2375 run x",
                "DOCKER_HOST=SSH://pc docker run x",
                "ssh ssh://dev@pc:22 docker run x",
            ),
        ),
        (
            "hook: a target that holds a variable: blocked, a variable elsewhere is not",
            lambda: (
                (
                    also("mac"),
                    also("pc"),
                    all(
                        blocked(me, command, "not expanded")
                        for command in (
                            "H=ssh://pc; DOCKER_HOST=$H docker run x",
                            'docker -H "$PCH" run x',
                            "ssh $PCALIAS docker run x",
                        )
                    ),
                    hook(me, "docker run -e A=$B x")[0] == 0,
                )[2:]
                == (True, True)
            ),
        ),
        (
            "hook: the default context is DOCKER_HOST when that is set",
            lambda: aims(
                there,
                "docker --context default run x",
                "DOCKER_CONTEXT=default docker run x",
                extra=at_pc,
            ),
        ),
        (
            "hook: a line continued with a backslash is one command",
            lambda: aims(there, "docker \\\n  -H ssh://pc \\\n  run x"),
        ),
        (
            "a live grant survives clear-expired and another holder's release",
            keeps_live,
        ),
        ("clear-expired goes past an unreadable record", clears_past_bad),
        ("a record with no holder: refused as unreadable", no_holder),
        (
            "hook: docker named in a search: untouched",
            lambda: hook(nobody, 'grep -rn "docker run" docs')[0] == 0,
        ),
    ]


def main() -> None:
    failed = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch).resolve()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (root / "bin-no-ssh").mkdir()
        for folder, name in (
            ("bin", "ssh"),
            ("bin", "docker"),
            ("bin-no-ssh", "docker"),
        ):
            path = root / folder / name
            path.write_text(STANDIN.format(python=sys.executable), encoding="utf-8")
            path.chmod(0o755)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("DOCKER_", "SLOT_"))
        }
        env |= {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "XDG_STATE_HOME": str(root / "state"),
            # A scratch Docker config: the guard reads its current context, never this machine's.
            "DOCKER_CONFIG": str(root / "docker"),
        }
        env.pop("HC_TERMINAL_ID", None)
        for name, case in cases(env):
            ok = case()
            failed += not ok
            sys.stdout.write(f"{'ok  ' if ok else 'FAIL'} {name}\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
