"""``python -m automation_file storage ...``: the storage layer from a shell.

Every subcommand takes storage URIs (or plain local paths) and prints one JSON
document, so the output can be piped into ``jq`` or read by another program:

.. code-block:: text

    python -m automation_file storage ls s3://reports/2026 --recursive
    python -m automation_file storage cp report.csv s3://reports/2026/report.csv
    python -m automation_file storage sync ./site s3://www --delete --dry-run
    python -m automation_file storage checksum s3://reports/2026/report.csv

A remote backend needs its client initialised first. ``--init`` takes a JSON
action list that runs before the command:

.. code-block:: text

    python -m automation_file storage \\
        --init '[["FA_s3_later_init", {"region_name": "us-east-1"}]]' \\
        ls s3://reports
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from automation_file.storage import actions

_SOURCE = "source"
_TARGET = "target"
_URI = "uri"


def _emit(document: Any) -> int:
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0


def _run_init(raw: str | None) -> None:
    if not raw:
        return
    from automation_file.core.action_executor import execute_action

    execute_action(json.loads(raw))


def _cmd_ls(args: argparse.Namespace) -> int:
    return _emit(actions.storage_list(args.uri, recursive=args.recursive))


def _cmd_stat(args: argparse.Namespace) -> int:
    return _emit(actions.storage_stat(args.uri))


def _cmd_cat(args: argparse.Namespace) -> int:
    sys.stdout.write(actions.storage_read_text(args.uri, encoding=args.encoding))
    return 0


def _cmd_cp(args: argparse.Namespace) -> int:
    if args.recursive:
        summary = actions.storage_copy_tree(
            args.source, args.target, overwrite=not args.no_overwrite
        )
        _emit(summary)
        return 1 if summary["errors"] else 0
    return _emit(actions.storage_copy(args.source, args.target, overwrite=not args.no_overwrite))


def _cmd_mv(args: argparse.Namespace) -> int:
    return _emit(actions.storage_move(args.source, args.target, overwrite=not args.no_overwrite))


def _cmd_rm(args: argparse.Namespace) -> int:
    actions.storage_delete(args.uri, recursive=args.recursive, missing_ok=args.missing_ok)
    return _emit({"deleted": args.uri})


def _cmd_mkdir(args: argparse.Namespace) -> int:
    actions.storage_mkdir(args.uri)
    return _emit({"created": args.uri})


def _cmd_checksum(args: argparse.Namespace) -> int:
    return _emit(actions.storage_checksum(args.uri, algorithm=args.algorithm))


def _cmd_verify(args: argparse.Namespace) -> int:
    matched = actions.storage_verify(args.uri, args.expected, algorithm=args.algorithm)
    _emit({"uri": args.uri, "matches": matched})
    return 0 if matched else 1


def _cmd_sync(args: argparse.Namespace) -> int:
    summary = actions.storage_sync(
        args.source,
        args.target,
        delete=args.delete,
        checksum=args.checksum,
        dry_run=args.dry_run,
    )
    _emit(summary)
    return 1 if summary["errors"] else 0


def _cmd_schemes(_args: argparse.Namespace) -> int:
    return _emit(actions.storage_schemes())


def _dispatch(args: argparse.Namespace) -> int:
    _run_init(args.init)
    return int(args.storage_handler(args))


def _add_read_commands(commands: argparse._SubParsersAction) -> None:
    ls_parser = commands.add_parser("ls", help="list a directory")
    ls_parser.add_argument(_URI)
    ls_parser.add_argument("-r", "--recursive", action="store_true")
    ls_parser.set_defaults(storage_handler=_cmd_ls)

    stat_parser = commands.add_parser("stat", help="show one entry's metadata")
    stat_parser.add_argument(_URI)
    stat_parser.set_defaults(storage_handler=_cmd_stat)

    cat_parser = commands.add_parser("cat", help="print a file's text")
    cat_parser.add_argument(_URI)
    cat_parser.add_argument("--encoding", default="utf-8")
    cat_parser.set_defaults(storage_handler=_cmd_cat)

    checksum_parser = commands.add_parser("checksum", help="print a file's digest")
    checksum_parser.add_argument(_URI)
    checksum_parser.add_argument("--algorithm", default="sha256")
    checksum_parser.set_defaults(storage_handler=_cmd_checksum)

    verify_parser = commands.add_parser("verify", help="compare a file with an expected digest")
    verify_parser.add_argument(_URI)
    verify_parser.add_argument("expected", help="a digest, or 'algorithm:digest'")
    verify_parser.add_argument("--algorithm", default="sha256")
    verify_parser.set_defaults(storage_handler=_cmd_verify)

    schemes_parser = commands.add_parser("schemes", help="list the registered URI schemes")
    schemes_parser.set_defaults(storage_handler=_cmd_schemes)


def _add_write_commands(commands: argparse._SubParsersAction) -> None:
    cp_parser = commands.add_parser("cp", help="copy a file, or a directory tree with -r")
    cp_parser.add_argument(_SOURCE)
    cp_parser.add_argument(_TARGET)
    cp_parser.add_argument("-r", "--recursive", action="store_true")
    cp_parser.add_argument("--no-overwrite", action="store_true")
    cp_parser.set_defaults(storage_handler=_cmd_cp)

    mv_parser = commands.add_parser("mv", help="move a file")
    mv_parser.add_argument(_SOURCE)
    mv_parser.add_argument(_TARGET)
    mv_parser.add_argument("--no-overwrite", action="store_true")
    mv_parser.set_defaults(storage_handler=_cmd_mv)

    rm_parser = commands.add_parser("rm", help="delete a file or a directory")
    rm_parser.add_argument(_URI)
    rm_parser.add_argument("-r", "--recursive", action="store_true")
    rm_parser.add_argument("--missing-ok", action="store_true")
    rm_parser.set_defaults(storage_handler=_cmd_rm)

    mkdir_parser = commands.add_parser("mkdir", help="create a directory")
    mkdir_parser.add_argument(_URI)
    mkdir_parser.set_defaults(storage_handler=_cmd_mkdir)

    sync_parser = commands.add_parser("sync", help="mirror a directory tree into another")
    sync_parser.add_argument(_SOURCE)
    sync_parser.add_argument(_TARGET)
    sync_parser.add_argument("--delete", action="store_true", help="remove what the source lacks")
    sync_parser.add_argument("--checksum", action="store_true", help="compare digests, not times")
    sync_parser.add_argument("--dry-run", action="store_true", help="report without changing")
    sync_parser.set_defaults(storage_handler=_cmd_sync)


def add_storage_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``storage`` subcommand and its own subcommands."""
    parser = subparsers.add_parser("storage", help="files and directories in any storage backend")
    parser.add_argument(
        "--init",
        default=None,
        help="JSON action list to run first, e.g. to initialise a backend's client",
    )
    commands = parser.add_subparsers(dest="storage_command", required=True)
    _add_read_commands(commands)
    _add_write_commands(commands)
    parser.set_defaults(handler=_dispatch)
