"""Status, stop and start of the Antigravity desktop app, which shares agy's keychain sign-in (agy-worker's guard).

  python -I agy_ide.py status|stop|start [--app antigravity|ide] [--timeout SECONDS]

status exits 0 and prints "running" or "not running" (with any language_server left over); stop quits the app the
way the owner would, which closes the owner's open windows, so it runs only when the owner or an explicit task run
starts it; start opens the app in the background. Never automatic: nothing else calls stop or start.
"""

import argparse
import subprocess
import sys
import time

APPS = {
    "antigravity": "com.google.antigravity",  # /Applications/Antigravity.app 2.33.0
    "ide": "com.google.antigravity-ide",  # /Applications/Antigravity IDE.app 2.1.1
}
LANGUAGE_SERVER = "language_server"


def app_running(bundle: str) -> bool:
    try:
        done = subprocess.run(
            ["osascript", "-e", f'application id "{bundle}" is running'],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return done.returncode == 0 and done.stdout.strip() == "true"


def language_servers() -> list[str]:
    try:
        done = subprocess.run(
            ["pgrep", "-fl", LANGUAGE_SERVER],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    return [ln.split(None, 1)[0] for ln in done.stdout.splitlines() if ln.strip()]


def status(bundle: str) -> tuple[bool, list[str]]:
    return app_running(bundle), language_servers()


def describe(bundle: str, running: bool, servers: list[str]) -> str:
    text = f"{bundle}: {'running' if running else 'not running'}"
    return text + (f"; language_server pids {' '.join(servers)}" if servers else "")


def stop(bundle: str, timeout: float) -> int:
    subprocess.run(
        ["osascript", "-e", f'quit app id "{bundle}"'], check=False, capture_output=True
    )
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        running, servers = status(bundle)
        if not running and not servers:
            print(describe(bundle, running, servers))
            return 0
        time.sleep(1)
    running, servers = status(bundle)
    print(
        f"agy:ide-stop: timed out after {timeout:g}s; {describe(bundle, running, servers)}. "
        "Quit it by hand (a save prompt may be open); a language_server that survives is stopped by its pid, never pkill.",
        file=sys.stderr,
    )
    return 1


def start(bundle: str) -> int:
    done = subprocess.run(["open", "-g", "-b", bundle], check=False)
    return done.returncode


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="agy:ide")
    ap.add_argument("action", choices=("status", "stop", "start"))
    ap.add_argument("--app", choices=sorted(APPS), default="antigravity")
    ap.add_argument("--timeout", type=float, default=30)
    args = ap.parse_args(argv)
    bundle = APPS[args.app]
    if args.action == "status":
        running, servers = status(bundle)
        print(describe(bundle, running, servers))
        return 0 if not running and not servers else 1
    if args.action == "stop":
        return stop(bundle, args.timeout)
    return start(bundle)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
