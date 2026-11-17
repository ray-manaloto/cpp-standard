#!/usr/bin/env -S python3 -I
"""pc-doctor's ssh in its tests: each call answers from a script, so no test reaches the PC."""

# The PC is a networked host, so a test links this file as `ssh` in a folder ahead of the real one on PATH (trimmed
# from dotfiles' tests/stand_in.py, which also stands in for brew and mise). $STAND_IN/script.json maps a call, its
# argv as a JSON list with the link's name first, to {"stdout", "stderr", "code", "sleep"}, where "sleep" is the
# seconds it waits first, as a call that hangs (pc-doctor's time limit). A call it does not name fails with 127, as a
# missing command does. Every call's JSON argv is a line of $STAND_IN/calls.jsonl.

import json
import os
import sys
import time
from pathlib import Path

folder = Path(os.environ["STAND_IN"])
call = json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]])
with (folder / "calls.jsonl").open("a") as log:
    log.write(call + "\n")
answer = json.loads((folder / "script.json").read_text()).get(call)
if answer is None:
    sys.stderr.write(f"stand-in: no answer for {call}\n")
    raise SystemExit(127)
time.sleep(answer.get("sleep", 0))
sys.stdout.write(answer.get("stdout", ""))
sys.stderr.write(answer.get("stderr", ""))
raise SystemExit(answer.get("code", 0))
