"""What the subcommand modules of ``python -m automation_file`` share.

A subcommand prints one JSON document, may run a JSON action list first
(``--init``, to initialise a backend's client) and may record what it does in an
audit trail (``--audit``). :func:`command_scope` does the last two around one
command, on behalf of the user who typed it.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import sys
from collections.abc import Iterator
from typing import Any

from automation_file.events import actor_scope

_ACTOR_PREFIX = "cli"


def emit(document: Any) -> int:
    """Print ``document`` as indented JSON and return the exit code 0."""
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0


def add_setup_arguments(parser: argparse.ArgumentParser) -> None:
    """Add ``--init`` and ``--audit`` to a subcommand."""
    parser.add_argument(
        "--init",
        default=None,
        help="JSON action list to run first, e.g. to initialise a backend's client",
    )
    parser.add_argument(
        "--audit",
        default=None,
        metavar="DB",
        help="record this command's events and storage operations in this SQLite audit trail",
    )


def cli_actor() -> str:
    """Return the actor a command runs as: ``cli:<user>``, or ``cli`` when the user is unknown."""
    try:
        return f"{_ACTOR_PREFIX}:{getpass.getuser()}"
    except (OSError, KeyError, ImportError):
        # getpass finds no user in a stripped environment (no USERNAME, no passwd entry).
        return _ACTOR_PREFIX


def _run_init(raw: str | None) -> None:
    if not raw:
        return
    from automation_file.core.action_executor import execute_action

    execute_action(json.loads(raw))


@contextlib.contextmanager
def command_scope(args: argparse.Namespace) -> Iterator[None]:
    """Run one command: start the audit trail it asked for, name the actor, run ``--init``.

    The trail is closed afterwards, so the database is complete when the process ends.
    """
    audit_db = getattr(args, "audit", None)
    trail = None
    if audit_db:
        from automation_file.audit import configure_audit

        trail = configure_audit(audit_db)
    try:
        with actor_scope(cli_actor()):
            _run_init(getattr(args, "init", None))
            yield
    finally:
        if trail is not None:
            trail.close()
