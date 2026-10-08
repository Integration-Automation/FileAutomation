"""``python -m automation_file integrity|pipeline|audit ...``: the runtime from a shell.

Each subcommand is a thin call into the ``FA_*`` function of the same name and
prints one JSON document:

.. code-block:: text

    python -m automation_file integrity baseline s3://reports/2026 reports.baseline.json
    python -m automation_file integrity verify s3://reports/2026 reports.baseline.json
    python -m automation_file pipeline run daily.yaml --param date=2026-10-08 --store runs.db
    python -m automation_file pipeline history --store runs.db
    python -m automation_file audit search --db audit.sqlite --status error --limit 20

Exit codes: ``integrity verify`` exits 1 when the tree drifted, ``pipeline
validate`` when the definition is invalid, ``pipeline run`` / ``resume`` when the
run did not succeed. Everything else exits 0, or 1 with the exception.

A pipeline run is recorded in the process's memory unless ``--store`` names a
SQLite file; ``status``, ``history`` and ``resume`` need that file to find a run
of an earlier command.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from automation_file.audit import actions as audit
from automation_file.audit import audit_search, configure_audit
from automation_file.cli_common import add_setup_arguments, command_scope, emit
from automation_file.exceptions import ArgparseException
from automation_file.integrity import DEFAULT_ALGORITHM
from automation_file.integrity import actions as integrity
from automation_file.pipeline import SQLiteRunStore, set_default_run_store
from automation_file.pipeline import actions as pipeline

_TARGET = "target"
_BASELINE = "baseline"
_DEFINITION = "definition"
_STORE = "--store"
_SUCCEEDED = "succeeded"
_SECONDS_PER_DAY = 86400.0
_TIME_FILTERS = ("since", "until")
#: The filters of ``audit search`` / ``audit count``, as their option names say them.
_AUDIT_FILTERS = (
    "since",
    "until",
    "actor",
    "source",
    "pipeline",
    "task",
    "action",
    "resource_prefix",
    "backend",
    "status",
    "correlation_id",
    "text",
)

# ---------------------------------------------------------------------- integrity


def _cmd_snapshot(args: argparse.Namespace) -> int:
    return emit(integrity.integrity_snapshot(args.target, algorithm=args.algorithm))


def _cmd_baseline(args: argparse.Namespace) -> int:
    return emit(integrity.integrity_baseline(args.target, args.baseline, algorithm=args.algorithm))


def _cmd_verify(args: argparse.Namespace) -> int:
    report = integrity.integrity_verify(args.target, args.baseline, deep=not args.quick)
    emit(report)
    return 0 if report["ok"] else 1


def _cmd_accept(args: argparse.Namespace) -> int:
    return emit(integrity.integrity_accept(args.target, args.baseline))


def _add_integrity_commands(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("integrity", help="baseline and verify a directory tree")
    add_setup_arguments(parser)
    commands = parser.add_subparsers(dest="integrity_command", required=True)

    snapshot = commands.add_parser("snapshot", help="hash the tree and print its manifest")
    snapshot.add_argument(_TARGET)
    snapshot.add_argument("--algorithm", default=DEFAULT_ALGORITHM)
    snapshot.set_defaults(operation_handler=_cmd_snapshot)

    baseline = commands.add_parser("baseline", help="approve the tree as it is now")
    baseline.add_argument(_TARGET)
    baseline.add_argument(_BASELINE, help="where the baseline is stored (a path or a URI)")
    baseline.add_argument("--algorithm", default=DEFAULT_ALGORITHM)
    baseline.set_defaults(operation_handler=_cmd_baseline)

    verify = commands.add_parser("verify", help="compare the tree with its baseline")
    verify.add_argument(_TARGET)
    verify.add_argument(_BASELINE)
    verify.add_argument(
        "--quick",
        action="store_true",
        help="hash only the files whose size, time or etag changed",
    )
    verify.set_defaults(operation_handler=_cmd_verify)

    accept = commands.add_parser("accept", help="approve the current tree as the new baseline")
    accept.add_argument(_TARGET)
    accept.add_argument(_BASELINE)
    accept.set_defaults(operation_handler=_cmd_accept)

    parser.set_defaults(handler=_dispatch)


# ---------------------------------------------------------------------- pipeline


def _parameters(pairs: list[str] | None) -> dict[str, Any] | None:
    """Turn ``name=value`` pairs into run parameters; a value that is JSON keeps its type."""
    if not pairs:
        return None
    parameters: dict[str, Any] = {}
    for pair in pairs:
        name, separator, raw = pair.partition("=")
        if not separator or not name:
            raise ArgparseException(f"--param takes name=value, got {pair!r}")
        try:
            parameters[name] = json.loads(raw)
        except json.JSONDecodeError:
            parameters[name] = raw
    return parameters


def _use_store(path: str | None) -> None:
    if path:
        set_default_run_store(SQLiteRunStore(path))


def _cmd_run(args: argparse.Namespace) -> int:
    _use_store(args.store)
    run = pipeline.pipeline_run(
        args.definition, params=_parameters(args.param), dry_run=args.dry_run
    )
    emit(run)
    return 0 if run["status"] == _SUCCEEDED else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    result = pipeline.pipeline_validate(args.definition)
    emit(result)
    return 0 if result["valid"] else 1


def _cmd_status(args: argparse.Namespace) -> int:
    _use_store(args.store)
    return emit(pipeline.pipeline_status(args.run_id))


def _cmd_history(args: argparse.Namespace) -> int:
    _use_store(args.store)
    return emit(pipeline.pipeline_history(args.pipeline, limit=args.limit))


def _cmd_resume(args: argparse.Namespace) -> int:
    _use_store(args.store)
    run = pipeline.pipeline_resume(args.run_id, args.definition)
    emit(run)
    return 0 if run["status"] == _SUCCEEDED else 1


def _add_pipeline_commands(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("pipeline", help="validate, run and inspect pipelines")
    add_setup_arguments(parser)
    commands = parser.add_subparsers(dest="pipeline_command", required=True)
    store_help = "SQLite file that records runs (default: this process's memory)"

    validate = commands.add_parser("validate", help="check a YAML or JSON definition")
    validate.add_argument(_DEFINITION)
    validate.set_defaults(operation_handler=_cmd_validate)

    run = commands.add_parser("run", help="run a definition")
    run.add_argument(_DEFINITION)
    run.add_argument(
        "--param", action="append", metavar="NAME=VALUE", help="a run parameter; repeatable"
    )
    run.add_argument("--dry-run", action="store_true", help="plan without executing")
    run.add_argument(_STORE, default=None, help=store_help)
    run.set_defaults(operation_handler=_cmd_run)

    status = commands.add_parser("status", help="show one recorded run")
    status.add_argument("run_id")
    status.add_argument(_STORE, default=None, help=store_help)
    status.set_defaults(operation_handler=_cmd_status)

    history = commands.add_parser("history", help="list the latest recorded runs")
    history.add_argument("--pipeline", default=None, help="only runs of this pipeline")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument(_STORE, default=None, help=store_help)
    history.set_defaults(operation_handler=_cmd_history)

    resume = commands.add_parser("resume", help="continue a recorded run")
    resume.add_argument("run_id")
    resume.add_argument(_DEFINITION)
    resume.add_argument(_STORE, default=None, help=store_help)
    resume.set_defaults(operation_handler=_cmd_resume)

    parser.set_defaults(handler=_dispatch)


# ---------------------------------------------------------------------- audit


def _local_time(value: str, option: str) -> str:
    """Return ``value`` with a UTC offset; a time typed without one is local time."""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise ArgparseException(
            f"--{option} takes an ISO 8601 date or time, got {value!r}"
        ) from error
    return (moment if moment.tzinfo is not None else moment.astimezone()).isoformat()


def _filters(args: argparse.Namespace) -> dict[str, Any]:
    filters = {
        name: getattr(args, name) for name in _AUDIT_FILTERS if getattr(args, name) is not None
    }
    for name in _TIME_FILTERS:
        if name in filters:
            filters[name] = _local_time(filters[name], name)
    return filters


def _cmd_search(args: argparse.Namespace) -> int:
    return emit(audit_search(**_filters(args), limit=args.limit, offset=args.offset))


def _cmd_count(args: argparse.Namespace) -> int:
    return emit({"count": audit.audit_count(**_filters(args))})


def _cmd_purge(args: argparse.Namespace) -> int:
    return emit({"purged": audit.audit_purge(args.older_than_days * _SECONDS_PER_DAY)})


def _add_database_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", required=True, help="the SQLite file of the audit trail")


def _add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    for name in _AUDIT_FILTERS:
        parser.add_argument(f"--{name.replace('_', '-')}", dest=name, default=None)


def _dispatch_audit(args: argparse.Namespace) -> int:
    trail = configure_audit(args.db)
    try:
        return int(args.operation_handler(args))
    finally:
        trail.close()


def _add_audit_commands(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("audit", help="search the audit trail")
    commands = parser.add_subparsers(dest="audit_command", required=True)

    search = commands.add_parser("search", help="list matching records, newest first")
    _add_database_argument(search)
    _add_filter_arguments(search)
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--offset", type=int, default=0)
    search.set_defaults(operation_handler=_cmd_search)

    count = commands.add_parser("count", help="count matching records")
    _add_database_argument(count)
    _add_filter_arguments(count)
    count.set_defaults(operation_handler=_cmd_count)

    purge = commands.add_parser("purge", help="delete the records older than a number of days")
    _add_database_argument(purge)
    purge.add_argument("--older-than-days", type=float, required=True)
    purge.set_defaults(operation_handler=_cmd_purge)

    parser.set_defaults(handler=_dispatch_audit)


# ---------------------------------------------------------------------- registration


def _dispatch(args: argparse.Namespace) -> int:
    with command_scope(args):
        return int(args.operation_handler(args))


def add_operation_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``integrity``, ``pipeline`` and ``audit`` subcommands."""
    _add_integrity_commands(subparsers)
    _add_pipeline_commands(subparsers)
    _add_audit_commands(subparsers)
