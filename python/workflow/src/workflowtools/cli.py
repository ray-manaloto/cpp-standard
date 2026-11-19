"""The workflowtools command: argv[0] names a generated Command, its generated model parses the rest."""

import subprocess
import sys
from collections.abc import Sequence

import yaml
from pydantic import BaseModel
from pydantic_settings import CliApp, CliSettingsSource

from . import frontmatter, receipts, rounds, settings_local, skill_table, tickets
from .models import (
    Command,
    Failure,
    Frontmatter,
    Options,
    Report,
    RoundClose,
    RoundOpen,
    RoundPr,
    RoundRetro,
    SettingsLocal,
    SkillTable,
    Tickets,
    VerifyCommit,
    VerifyReceipt,
)

OPTIONS: dict[Command, type[Options]] = {
    Command.frontmatter: Frontmatter,
    Command.skill_table: SkillTable,
    Command.tickets: Tickets,
    Command.settings_local: SettingsLocal,
    Command.round_open: RoundOpen,
    Command.round_pr: RoundPr,
    Command.round_close: RoundClose,
    Command.round_retro: RoundRetro,
    Command.report: Report,
    Command.verify_receipt: VerifyReceipt,
    Command.verify_commit: VerifyCommit,
}


def parse(argv: Sequence[str]) -> Options:
    if not argv or argv[0] not in set(Command):
        msg = f"workflowtools: the first argument is one of {', '.join(Command)}"
        raise ValueError(msg)
    command = Command(argv[0])
    model = OPTIONS[command]
    cli = CliSettingsSource(
        # CliApp.run documents BaseModel input; CliSettingsSource's annotation says BaseSettings only.
        model,  # ty: ignore[invalid-argument-type]
        cli_prog_name=f"workflowtools {command.value}",
        cli_kebab_case=True,
        cli_implicit_flags=True,
        cli_exit_on_error=False,
    )
    return CliApp.run(model, cli_args=list(argv[1:]), cli_settings_source=cli)


def emit(lines: Sequence[BaseModel]) -> None:
    sys.stdout.writelines(line.model_dump_json() + "\n" for line in lines)


def run(options: Options) -> None:
    """Print each finding as a JSON line and exit 1 when there is one."""
    match options:
        case Tickets():
            lines, markdown = tickets.run(options)
            if markdown:
                sys.stdout.write(markdown)
            else:
                emit(lines)
            if status := tickets.code(lines, require_github=options.require_github):
                raise SystemExit(status)
            return
        case SkillTable():
            result = skill_table.findings()
            found = [] if isinstance(result, BaseModel) else result
            emit([result] if isinstance(result, BaseModel) else result)
        case SettingsLocal():
            emit(found := settings_local.findings())
        case RoundOpen() | RoundPr() | RoundClose() | RoundRetro() | VerifyReceipt():
            # The event, tree or receipt written, or why none was: exit 1 on a finding (a round event out of order,
            # no verdict saved), 2 when GitHub could not answer.
            emit(lines := [receipts.run(options) if isinstance(options, VerifyReceipt) else rounds.run(options)])
            if status := tickets.code(lines, require_github=False):
                raise SystemExit(status)
            return
        case Report() | VerifyCommit():
            # Report-only: an unknown report section, and a mismatch or no receipt at commit, are lines in the
            # output, never a failing exit; the commit goes ahead.
            emit(rounds.report(options) if isinstance(options, Report) else [receipts.commit(options)])
            return
        case _:
            emit(found := frontmatter.findings())
    if found:
        raise SystemExit(1)


def main(argv: Sequence[str] | None = None) -> None:
    try:
        run(parse(sys.argv[1:] if argv is None else argv))
    except subprocess.CalledProcessError as error:
        sys.stderr.write(Failure(error=f"{error.cmd[0]} failed: {error.stderr}").model_dump_json() + "\n")
        raise SystemExit(1) from None
    # pydantic's and json's errors (ValueError subclasses), an installed SKILL.md whose YAML does not parse, and an
    # unreadable table, manifest or SKILL.md.
    except (ValueError, yaml.YAMLError, OSError) as error:
        sys.stderr.write(Failure(error=str(error)).model_dump_json() + "\n")
        raise SystemExit(1) from None
