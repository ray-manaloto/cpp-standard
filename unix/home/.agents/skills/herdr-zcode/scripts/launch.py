#!/usr/bin/env python3
"""Open watched ZCode TUI workers in the Herdr space containing the caller."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, cwd=cwd, check=False)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()[:300]
        raise ValueError(
            f"{' '.join(args[:2])} failed: {detail or f'exit {proc.returncode}'}"
        )
    return proc.stdout.strip()


def split_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return argv, []
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1 :]


def current_space() -> dict:
    terminal = os.environ.get("HC_TERMINAL_ID")
    if not terminal:
        raise ValueError("Run this from a Herdr terminal with HC_TERMINAL_ID set.")
    spaces = json.loads(run("herdr-app", "ls"))["spaces"]
    matches = [
        space
        for space in spaces
        if any(
            pane["terminal"] == terminal
            for tab in space["tabs"]
            for pane in tab["terminals"]
        )
    ]
    if len(matches) != 1 or matches[0].get("machine"):
        raise ValueError("Could not find the caller in a local Herdr space.")
    return matches[0]


def verify_doctor(entry: list[str], folder: Path, node: Path) -> None:
    env = {
        **os.environ,
        "ZCODE_NODE": str(node),
        "ZCODE_DISABLE_UPDATE_CHECK": "1",
        "NO_UPDATE_NOTIFIER": "1",
    }
    proc = subprocess.run(
        [*entry, "doctor", "--json"],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()[:300]
        raise ValueError(f"zcode doctor failed: {detail or proc.returncode}")
    try:
        report = json.loads(proc.stdout)
    except ValueError as error:
        raise ValueError(f"zcode doctor returned invalid JSON: {error}") from error
    cfg = report.get("configuration") if isinstance(report, dict) else None
    if not isinstance(cfg, dict) or not cfg.get("ok"):
        raise ValueError("zcode doctor reported invalid user/global configuration.")


def main(argv: list[str] | None = None) -> None:
    cli_args, passthrough = split_passthrough(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default=".", help="Working folder for all workers")
    parser.add_argument(
        "--skip-doctor",
        action="store_true",
        help="Skip `zcode doctor --json` preflight before opening tabs",
    )
    parser.add_argument("names", nargs="+", help="Distinct Herdr tab names")
    args = parser.parse_args(cli_args)
    if len(set(args.names)) != len(args.names) or any(
        not name.strip() for name in args.names
    ):
        parser.error("Supply distinct, nonempty names.")

    try:
        space = current_space()
        if {tab["name"] for tab in space["tabs"]}.intersection(args.names):
            raise ValueError("A requested tab name already exists in this space.")
        folder = Path(args.folder).expanduser().resolve(strict=True)
        if not folder.is_dir():
            raise ValueError(f"Working folder is not a directory: {folder}")
        zcode = Path(run("mise", "which", "zcode", cwd=Path.home()))
        node = Path(run("mise", "which", "node", cwd=Path.home()))
        if not zcode.is_file() or not node.is_file():
            raise ValueError("zcode or node is missing from the user mise install.")
        entry = (
            [str(node), str(zcode)] if zcode.resolve().suffix == ".js" else [str(zcode)]
        )
        if not args.skip_doctor:
            verify_doctor(entry, folder, node)
        command = [
            "/usr/bin/env",
            f"ZCODE_NODE={node}",
            "ZCODE_DISABLE_UPDATE_CHECK=1",
            "NO_UPDATE_NOTIFIER=1",
            *entry,
            *passthrough,
        ]
        for name in args.names:
            created = json.loads(
                run(
                    "herdr-app",
                    "do",
                    "tab.new",
                    "--space",
                    space["id"],
                    "--name",
                    name,
                    "--folder",
                    str(folder),
                    "--focus",
                    "false",
                    "--argv",
                    json.dumps(command),
                )
            )
            print(
                json.dumps(
                    {
                        "name": name,
                        "tab": created["tab"],
                        "terminal": created["terminal"],
                    }
                ),
                flush=True,
            )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Launch stopped: {error}\n")


if __name__ == "__main__":
    main()
