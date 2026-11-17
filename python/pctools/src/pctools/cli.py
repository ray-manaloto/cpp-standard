"""The pctools CLI: one command per mise task it does the work of."""

import argparse
from collections.abc import Sequence

from . import pcdoctor

# Each command's work. pc-doctor reports each input it could not read as unknown in its JSON lines and exits with
# its checks' code.
COMMANDS = {"pc-doctor": pcdoctor.doctor}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pctools")
    parser.add_argument("command", choices=list(COMMANDS))
    COMMANDS[parser.parse_args(argv).command]()
