"""Check slot.py and the agent-bin docker shim against #179's and #194's acceptance lines, offline: a scratch state
directory and stand-in ssh and docker on PATH (ssh -G maps the alias `pc` to a made-up host; its load comes from
STUB_PC_* variables; the stand-in docker prints the words it got). It never touches the real grant record, the real
ssh config or a Docker daemon. Prints one line per case and exits 1 when any fails.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIM = HERE.parent.parent / ".mise" / "agent-bin" / "docker"
STANDIN = """#!{python} -I
import json, os, sys
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
elif name in ("docker", "docker-compose") and sys.argv[1:3] == ["context", "inspect"]:
    known = {{"pcctx": "ssh://dev@pc", "localctx": "unix:///var/run/docker.sock"}}
    if sys.argv[3] not in known:
        sys.exit(1)
    print(known[sys.argv[3]])
elif name in ("docker", "docker-compose"):
    print("real " + name + " " + json.dumps(sys.argv[1:]))
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


def run(
    env: dict[str, str], *argv: str, name: str = "docker"
) -> subprocess.CompletedProcess[str]:
    """The shim itself, as an agent shell runs it (docker-compose through its link)."""
    return subprocess.run(
        [str(SHIM.parent / name), *argv],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def cases(env: dict[str, str]) -> list[tuple[str, Callable[[], bool]]]:
    me = env | {"SLOT_HOLDER": "t1", "SLOT_LOAD_LINE": "100000"}
    other = env | {"SLOT_HOLDER": "t2", "SLOT_LOAD_LINE": "100000"}
    nobody = {
        k: v for k, v in env.items() if k not in {"SLOT_HOLDER", "HC_TERMINAL_ID"}
    }
    # A folder with docker but no ssh (main makes it): the hook must block when it cannot resolve a host.
    no_ssh = str(Path(env["XDG_STATE_HOME"]).parent / "bin-no-ssh")
    bin_dir = env["PATH"].split(os.pathsep)[0]
    real = str(Path(bin_dir) / "docker")
    agent_bin = str(SHIM.parent)

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

    def under_each(answer: Callable[[], int]) -> list[int]:
        """The answer with no grant, only the mac grant, only the pc grant, and both."""
        codes = []
        for hosts in ((), ("mac",), ("pc",), ("mac", "pc")):
            clear()
            for host in hosts:
                also(host)
            codes.append(answer())
        return codes

    def aim(command: str, extra: dict[str, str] | None = None) -> list[int]:
        """The hook's exit code for one command under each set of grants."""
        return under_each(lambda: hook(me | (extra or {}), command)[0])

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
        """A record with no holder is unreadable, not a grant to None."""
        clear()
        records.mkdir(parents=True, exist_ok=True)
        pc_record.write_text("{}")
        done = slot(me, "check", "--host", "pc")
        pc_record.unlink()
        return done.returncode == 1 and "has no holder" in done.stderr

    # The exec verdict: 0 lets the shim run real docker, 1 refuses.
    def verdict(
        argv: list[str], extra: dict[str, str] | None = None, name: str = "docker"
    ) -> list[int]:
        return under_each(
            lambda: (
                slot(me | (extra or {}), "exec", "--real", real, name, *argv).returncode
            )
        )

    pcdir = Path(env["DOCKER_CONFIG"]).parent / "docker-pc"
    pcdir.mkdir(exist_ok=True)
    (pcdir / "config.json").write_text('{"currentContext": "pcctx"}')

    here, there, both = [2, 0, 2, 0], [2, 2, 0, 0], [2, 2, 2, 0]
    free = [0, 0, 0, 0]
    x_here, x_there, x_free, x_never = (
        [1, 0, 1, 0],
        [1, 1, 0, 0],
        [0, 0, 0, 0],
        [1, 1, 1, 1],
    )
    at_pc = {"DOCKER_HOST": "ssh://pc"}
    on_pcctx = {"DOCKER_CONTEXT": "pcctx"}

    # The shim's table: docker's own options x the environment x the current context, under each set of grants.
    # Heavy is main's set by position: run, create, build, container run|create, image build, builder build,
    # buildx build|bake, compose up|run|create|build. Words after the subcommand are the container's.
    exec_table: list[tuple[list[str], dict[str, str], str | None, list[int]]] = [
        (["run", "x"], {}, None, x_here),
        (["create", "x"], {}, None, x_here),
        (["build", "."], {}, None, x_here),
        (["container", "run", "x"], {}, None, x_here),
        (["container", "create", "x"], {}, None, x_here),
        (["image", "build", "."], {}, None, x_here),
        (["builder", "build", "."], {}, None, x_here),
        (["buildx", "build", "."], {}, None, x_here),
        (["buildx", "--builder", "b", "bake"], {}, None, x_here),
        (["compose", "-f", "a.yml", "up", "-d"], {}, None, x_here),
        (["compose", "run", "app"], {}, None, x_here),
        (["compose", "--profile", "p", "build"], {}, None, x_here),
        (["-l", "debug", "run", "x"], {}, None, x_here),
        (["run", "-c", "512", "img"], {}, None, x_here),
        (["run", "-h", "pc", "img"], {}, None, x_here),
        (
            ["run", "--rm", "img", "sh", "-c", "docker -H ssh://pc run y"],
            {},
            None,
            x_here,
        ),
        (["run", "-e", "DOCKER_HOST=ssh://pc", "img"], {}, None, x_here),
        (["run", "--privileged", "x"], {}, None, x_here),
        (["-H", "ssh://pc", "run", "x"], {}, None, x_there),
        (["-Hssh://pc", "run", "x"], {}, None, x_there),
        (["-H=ssh://pc", "run", "x"], {}, None, x_there),
        (["--host=ssh://dev@pc:22", "build", "."], {}, None, x_there),
        (["-H", "pc:2375", "run", "x"], {}, None, x_there),
        (["--context", "pcctx", "run", "x"], {}, None, x_there),
        (["-cpcctx", "run", "x"], {}, None, x_there),
        (["-c", "pcctx", "compose", "up"], {}, None, x_there),
        (["compose", "--context", "pcctx", "up"], {}, None, x_there),
        (["--config", str(pcdir), "run", "x"], {}, None, x_there),
        (["run", "x"], at_pc, None, x_there),
        (["run", "x"], {"DOCKER_HOST": "SSH://pc"}, None, x_there),
        (["run", "x"], on_pcctx, None, x_there),
        (["run", "x"], {}, "pcctx", x_there),
        (["image", "build", "."], at_pc, None, x_there),
        (["buildx", "bake"], at_pc, None, x_there),
        (["-H", "ssh://pc", "run", "--device", "/dev/fuse", "x"], {}, None, x_there),
        (["--context", "default", "run", "x"], at_pc, None, x_there),
        (["run", "x"], {"DOCKER_HOST": "", "DOCKER_CONTEXT": "pcctx"}, None, x_there),
        (["-c", "localctx", "run", "x"], at_pc, None, x_here),
        (["-H", "unix:///var/run/docker.sock", "run", "x"], at_pc, None, x_here),
        (["--context=localctx", "build", "."], on_pcctx, None, x_here),
        (["run", "x"], {"DOCKER_HOST": "unix:///var/run/docker.sock"}, "pcctx", x_here),
        (["--context", "default", "run", "x"], {}, "pcctx", x_here),
        (["run", "x"], {"DOCKER_CONTEXT": "localctx"}, "pcctx", x_here),
        (["ps"], at_pc, None, x_free),
        (["images"], {}, "pcctx", x_free),
        (["exec", "c", "make", "build"], {}, None, x_free),
        (["logs", "run"], {}, None, x_free),
        (["context", "use", "pcctx"], {}, None, x_free),
        (["-H", "ssh://pc", "ps"], {}, None, x_free),
        (["compose", "ps"], at_pc, None, x_free),
        (["--version"], {}, None, x_free),
        ([], {}, None, x_free),
        (["--context", "nosuchctx", "run", "x"], {}, None, x_never),
        (["run", "x"], {"DOCKER_CONTEXT": "nosuchctx"}, None, x_never),
        (["run", "x"], {}, "nosuchctx", x_never),
        (["-H", "ssh://pc", "run", "--privileged", "x"], {}, None, x_never),
        (["run", "--privileged=true", "x"], at_pc, None, x_never),
        (["run", "--cap-add=ALL", "x"], {}, "pcctx", x_never),
    ]

    def exec_row(
        argv: list[str], extra: dict[str, str], context: str | None, want: list[int]
    ) -> bool:
        if context is None:
            return verdict(argv, extra) == want
        return with_context(context, lambda: verdict(argv, extra) == want)

    def label(argv: list[str], extra: dict[str, str], context: str | None) -> str:
        where = " ".join(f"{k}={v}" for k, v in extra.items()) + (
            f" current context {context}" if context else ""
        )
        return f"exec: docker {' '.join(argv) or '(no words)'}{' with ' + where if where.strip() else ''}"

    # The hook's table. Rule 1 (owner): a command that names ssh as a word and starts heavy docker needs the pc
    # grant; the Mac part of such a command is the shim's. Rule 2: main's split, each heavy segment needing the grant
    # of the host its docker options and environment aim at. Never stricter than main except rule 1.
    hook_table: list[tuple[str, dict[str, str], list[int]]] = [
        ("ssh pc docker run x", {}, there),
        ("ssh -o BatchMode=yes pc 'docker run --rm x'", {}, there),
        ("ssh pc 'docker build . && docker run x'", {}, there),
        ("ssh pc 'docker build -t i .; docker run i'", {}, there),
        ("ssh pc 'cd /w && docker compose build && docker compose up -d'", {}, there),
        ("ssh pc bash -lc 'docker build . && docker run x'", {}, there),
        ("ssh pc <<'EOF'\ndocker build -t i .\ndocker run i\nEOF", {}, there),
        ("ssh pc bash -s <<EOF && echo sent\ndocker run x\nEOF\nls", {}, there),
        ("for i in 1 2; do ssh pc docker run x; done", {}, there),
        ("/usr/bin/ssh pc docker run x", {}, there),
        ("docker run a && ssh pc docker run b", {}, there),
        ("cat <<EOF | ssh pc bash\ndocker run x\nEOF", {}, there),
        # Rule 1 reads heavy docker after the ssh word, so an ssh call that comes first and starts nothing still
        # asks for the pc grant; the Mac start after it is the shim's (report-08 finding 2b, kept by rule 1).
        ("ssh pc true; docker run x", {}, there),
        ("ssh pc 'cat /proc/loadavg' && docker build .", {}, there),
        ("ssh otherhost ls && docker run x", {}, there),
        ("rsync -e ssh . pc:/x && docker build .", {}, there),
        # Finding 2b rows where docker starts before the ssh word, or ssh is not a word: main's reading, the mac grant.
        ("docker build -t i . && ssh pc docker pull i", {}, here),
        ("docker build -t i . && docker save i | ssh pc docker load", {}, here),
        ("docker build . && echo ssh", {}, here),
        ("docker build . && echo done # then ssh in", {}, here),
        ("docker build . || echo 'see the pc for logs'", {}, here),
        ("scp f pc:/x && docker run x", {}, here),
        ("docker -H ssh://pc images && docker build .", {}, here),
        ("docker build -t i . && git push ssh://git@github.com/a/b", {}, here),
        ("docker build --ssh default -t x . && docker run x", {}, here),
        ("docker run x", {}, here),
        ("docker run --rm alpine true", {}, here),
        ("cd /x && docker build .", {}, here),
        ("docker build . 2>&1 | grep -c warning", {}, here),
        ("docker build . 2>&1 | head -c 2000", {}, here),
        ("docker run --rm img | grep -c x", {}, here),
        ("docker run --rm img python -c 'print(1)'", {}, here),
        ("docker run --rm img psql -c 'select 1'", {}, here),
        ("docker run -c 512 img && echo ok", {}, here),
        (
            "docker compose up -d && docker compose exec app psql -c 'select 1'",
            {},
            here,
        ),
        ("docker build -t i . && docker save i | gzip -c > i.tgz", {}, here),
        ("docker run --hostname web img | tee log", {}, here),
        ("docker build --ssh default . | tee log", {}, here),
        ("docker run --rm -v ~/.ssh:/root/.ssh img && echo ok", {}, here),
        ("docker build -t sshd . && docker run sshd", {}, here),
        ("git clone ssh://git@github.com/a/b && docker build b", {}, here),
        ("docker run -e DOCKER_HOST=ssh://pc img", {}, here),
        ("docker run -h pc img", {}, here),
        ("docker --context localctx run x", at_pc, here),
        ("DOCKER_HOST= docker run x", at_pc, here),
        ("docker --context nosuchctx run x", {}, here),
        ("docker run x", {"DOCKER_CONTEXT": "nosuchctx"}, here),
        ("DOCKER_HOST=ssh://pc docker run x", {}, there),
        ("DOCKER_HOST=ssh://pc docker build . 2>&1 | grep -c warning", {}, there),
        ("docker -H ssh://pc run x", {}, there),
        ("docker -Hssh://pc run x", {}, there),
        ("docker --context pcctx run x && echo ok", {}, there),
        ("docker -c pcctx run x | tee log", {}, there),
        ("docker compose --context pcctx up", {}, there),
        ("DOCKER_CONTEXT=pcctx docker build .", {}, there),
        ("docker run x", at_pc, there),
        ("timeout 600 docker run x", at_pc, there),
        ("docker run a; DOCKER_HOST=ssh://pc docker run b", {}, both),
        ("docker ps", at_pc, free),
        ("ls -la && make build", {}, free),
        ('grep -rn "docker run" docs', {}, free),
        ("ssh otherhost ls && docker ps", {}, free),
        ("echo 'docker run x'; ssh pc ls", {}, free),
        # As on main: the split reads a commit message line that starts with docker run as a start.
        ("git commit -F - <<'EOF'\ndocker run x\nEOF", {}, here),
        # A shape main never read: left to the shim at exec time.
        ("(docker run x)", {}, free),
    ]

    def shim_env(**extra: str) -> dict[str, str]:
        return me | {"PATH": os.pathsep.join([agent_bin, bin_dir, env["PATH"]])} | extra

    def no_python() -> bool:
        """A call that starts nothing runs real docker with no uv or python on PATH: the fast path starts none."""
        clear()
        done = run(
            me | {"PATH": os.pathsep.join([agent_bin, bin_dir, "/usr/bin", "/bin"])},
            "ps",
            "-a",
        )
        return done.returncode == 0 and done.stdout == 'real docker ["ps", "-a"]\n'

    def fails_closed() -> bool:
        """A heavy call refuses when slot.py cannot run (no uv on PATH), grants held or not."""
        also("mac")
        done = run(
            me | {"PATH": os.pathsep.join([agent_bin, bin_dir, "/usr/bin", "/bin"])},
            "run",
            "x",
        )
        return done.returncode != 0 and "real docker" not in done.stdout

    def argv_untouched() -> bool:
        granted()
        words = ["run", "--rm", "-e", "A=b c", "img", "sh", "-c", 'echo "$X" * ; true']
        done = run(shim_env(), *words)
        return (
            done.returncode == 0
            and done.stdout == "real docker " + json.dumps(words) + "\n"
        )

    def shim_refuses() -> bool:
        """No grant: the shim's own message, and real docker never runs."""
        clear()
        done = run(shim_env(), "run", "x")
        return (
            done.returncode == 1
            and done.stderr.startswith("slot shim: refused: no mac slot grant")
            and "real docker" not in done.stdout
            and "Traceback" not in done.stderr
        )

    def shim_pc() -> bool:
        granted(host="pc")
        done = run(shim_env(SLOT_LOAD_LINE="0"), "-H", "ssh://pc", "run", "x")
        return done.returncode == 0 and done.stdout.startswith("real docker")

    def shim_twice() -> bool:
        """The shim's folder twice on PATH (a nested shell, a second session hook): real docker still found."""
        done = run(
            me
            | {"PATH": os.pathsep.join([agent_bin, agent_bin, bin_dir, env["PATH"]])},
            "ps",
        )
        return done.returncode == 0 and done.stdout.startswith("real docker")

    def shim_alone() -> bool:
        """No docker past the shim: a one-line error, exit 127."""
        done = run(me | {"PATH": agent_bin}, "ps")
        return done.returncode == 127 and "slot shim: no docker on PATH" in done.stderr

    def compose_link() -> bool:
        clear()
        refused_up = run(shim_env(), "up", "-d", name="docker-compose")
        granted()
        ran = run(shim_env(), "up", "-d", name="docker-compose")
        ps = run(nobody | {"PATH": shim_env()["PATH"]}, "ps", name="docker-compose")
        return (
            refused_up.returncode == 1
            and ran.stdout == 'real docker-compose ["up", "-d"]\n'
            and ps.returncode == 0
        )

    def holderless(argv: list[str], code: int, words: str = "") -> bool:
        """No SLOT_HOLDER and no HC_TERMINAL_ID: a heavy call refuses, grants or not; any other runs."""
        also("mac")
        also("pc")
        done = slot(nobody, "exec", "--real", real, "docker", *argv)
        return done.returncode == code and words in done.stderr

    def one_line(done: subprocess.CompletedProcess[str], words: str) -> bool:
        return (
            done.returncode == 1
            and words in done.stderr
            and "Traceback" not in done.stderr
            and done.stderr.count("\n") == 1
        )

    rows: list[tuple[str, Callable[[], bool]]] = [
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
            "task check with DOCKER_HOST at the PC: the PC's load",
            lambda: (
                granted(host="pc"),
                "the PC's (16 cores) load 1.0 < 12"
                in slot(mac_busy | {"DOCKER_HOST": "ssh://pc"}, "check").stdout,
            )[1],
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
            "check with a context that cannot be inspected: one line, no traceback (verify finding 4)",
            lambda: (
                all(
                    one_line(slot(me | extra, "check", *args), "cannot be inspected")
                    for extra in ({"DOCKER_CONTEXT": "nosuchctx"},)
                    for args in ((), ("--host", "mac"), ("--host", "pc"))
                )
                and with_context(
                    "nosuchctx",
                    lambda: one_line(slot(me, "check"), "cannot be inspected"),
                )
            ),
        ),
        (
            "a live grant survives clear-expired and another holder's release",
            keeps_live,
        ),
        ("clear-expired goes past an unreadable record", clears_past_bad),
        ("a record with no holder: refused as unreadable", no_holder),
        *(
            (
                f"hook: {command!r}" + (f" with {extra}" if extra else ""),
                lambda command=command, extra=extra, want=want: (
                    aim(command, extra) == want
                ),
            )
            for command, extra, want in hook_table
        ),
        *(
            (
                label(argv, extra, context),
                lambda a=argv, e=extra, c=context, w=want: exec_row(a, e, c, w),
            )
            for argv, extra, context, want in exec_table
        ),
        (
            "exec: docker-compose up is compose up, its ps is not heavy",
            lambda: (
                verdict(["up", "-d"], name="docker-compose") == x_here
                and verdict(["up"], at_pc, name="docker-compose") == x_there
                and verdict(["ps"], name="docker-compose") == x_free
            ),
        ),
        (
            "exec: no holder, heavy: refused naming SLOT_HOLDER, both grants held",
            lambda: holderless(["run", "x"], 1, "set SLOT_HOLDER"),
        ),
        (
            "exec: no holder, not heavy: allowed",
            lambda: holderless(["ps"], 0),
        ),
        (
            "exec: HC_TERMINAL_ID is the holder when SLOT_HOLDER is unset",
            lambda: (
                granted(),
                slot(
                    nobody | {"HC_TERMINAL_ID": "t1", "SLOT_LOAD_LINE": "100000"},
                    "exec",
                    "--real",
                    real,
                    "docker",
                    "run",
                    "x",
                ).returncode
                == 0,
            )[1],
        ),
        (
            "exec: the Mac's load at the line: refused, with the load",
            lambda: (
                granted(),
                one_line(
                    slot(mac_busy, "exec", "--real", real, "docker", "run", "x"),
                    "5-minute load",
                ),
            )[1],
        ),
        (
            "exec: the PC over its pause line: refused",
            lambda: (
                granted(host="pc"),
                one_line(
                    slot(
                        me | {"STUB_PC_LOAD": "15.00"},
                        "exec",
                        "--real",
                        real,
                        "docker",
                        "-H",
                        "ssh://pc",
                        "run",
                        "x",
                    ),
                    "over the pause line 14.4",
                ),
            )[1],
        ),
        (
            "exec: an unknown context: one line, no traceback",
            lambda: one_line(
                slot(
                    me,
                    "exec",
                    "--real",
                    real,
                    "docker",
                    "--context",
                    "nosuchctx",
                    "run",
                    "x",
                ),
                "cannot be inspected",
            ),
        ),
        (
            "exec: --privileged at the PC: refused by name",
            lambda: (
                also("pc"),
                one_line(
                    slot(
                        me,
                        "exec",
                        "--real",
                        real,
                        "docker",
                        "-H",
                        "ssh://pc",
                        "run",
                        "--privileged",
                        "x",
                    ),
                    "--privileged container on the PC",
                ),
            )[1],
        ),
        (
            "exec: ssh missing, so the target is unknown: refused",
            lambda: (
                also("mac"),
                slot(
                    me | {"PATH": no_ssh},
                    "exec",
                    "--real",
                    real,
                    "docker",
                    "-H",
                    "ssh://pc",
                    "run",
                    "x",
                ).returncode
                == 1,
            )[1],
        ),
        ("shim: a call that starts nothing needs no python", no_python),
        ("shim: a heavy call fails closed when slot.py cannot run", fails_closed),
        ("shim: real docker gets the words unchanged", argv_untouched),
        ("shim: no grant, its own one-line refusal", shim_refuses),
        ("shim: PC work with the pc grant runs, the Mac's load not read", shim_pc),
        ("shim: its folder twice on PATH", shim_twice),
        ("shim: no docker past it: exit 127", shim_alone),
        ("shim: the docker-compose link", compose_link),
    ]
    return rows


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
            ("bin", "docker-compose"),
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
        # The shim's folder never comes from this shell: each shim case puts it on PATH itself.
        rest = [
            p for p in os.environ["PATH"].split(os.pathsep) if p != str(SHIM.parent)
        ]
        env |= {
            "PATH": os.pathsep.join([str(bin_dir), *rest]),
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
