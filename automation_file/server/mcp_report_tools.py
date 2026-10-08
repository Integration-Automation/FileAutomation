"""The semantic reporting tools: ``integrity_status`` and ``audit_search``.

Both read what the process already knows and change nothing: the named
integrity monitors with their last result, and the audit trail. Neither is
bound to the policy's roots, because neither touches a storage location; a
deployment whose client must not see them leaves them out of the policy's
``tools``.
"""

from __future__ import annotations

from typing import Any

from automation_file.audit.trail import audit_trail
from automation_file.integrity.actions import integrity_status as monitor_statuses
from automation_file.integrity.errors import IntegrityException
from automation_file.server.mcp_policy import NOT_CONFIGURED, NOT_FOUND, MCPToolException
from automation_file.server.mcp_tool_model import (
    SemanticTool,
    ToolSession,
    arguments_schema,
    text,
    whole,
)

INTEGRITY_STATUS = "integrity_status"
AUDIT_SEARCH = "audit_search"
_DEFAULT_AUDIT_LIMIT = 50
_PAGING = ("limit", "offset")
_EXACT_FILTERS = {
    "actor": "Who did it: a user, 'scheduler', or the 'mcp' actor of this server's own calls.",
    "source": "The component that reported: storage, pipeline, mcp, integrity, scheduler, notify.",
    "pipeline": "The pipeline name.",
    "task": "The task ID inside a pipeline.",
    "action": "What happened: a storage operation (upload, download, read, delete, mkdir, "
    "copy, move) or an event type (pipeline.failed, task.failed, mcp.tool.completed).",
    "backend": "The storage scheme: s3, sftp, local, ...",
    "status": "The result: ok, warning, error, refused, or the word the emitter chose.",
    "correlation_id": "Everything one call or one pipeline run did: the correlation_id of a "
    "tool result, or the run_id of a pipeline run.",
}


def _trimmed(status: dict[str, Any], limit: int) -> dict[str, Any]:
    """Cut the change list of a monitor's last report down to ``limit`` entries."""
    report = status.get("last_report")
    if not report or len(report["changes"]) <= limit:
        return status
    shortened = {**report, "changes": report["changes"][:limit], "changes_truncated": True}
    return {**status, "last_report": shortened}


def integrity_status(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Report the named integrity monitors: running or not, the last run and its report."""
    limit = session.policy.max_results
    try:
        statuses = monitor_statuses(args.get("name"))
    except IntegrityException as error:
        raise MCPToolException(f"integrity_status: {error}", NOT_FOUND) from error
    monitors = [_trimmed(status, limit) for status in statuses]
    return {"monitors": monitors, "count": len(monitors)}


def audit_search(session: ToolSession, args: dict[str, Any]) -> dict[str, Any]:
    """Search the audit trail, newest first, with the number of records capped."""
    if audit_trail.store is None:
        raise MCPToolException(
            "this server keeps no audit trail: whoever operates it has to call "
            "configure_audit(<database path>) before it starts serving",
            NOT_CONFIGURED,
        )
    limit = session.policy.clamp_results(args.get("limit", _DEFAULT_AUDIT_LIMIT))
    offset = args["offset"]
    filters = {name: value for name, value in args.items() if name not in _PAGING}
    records = audit_trail.search(**filters, limit=limit, offset=offset)
    total = audit_trail.count(**filters)
    return {
        "records": [record.to_dict() for record in records],
        "count": len(records),
        "total": total,
        "limit": limit,
        "offset": offset,
        "truncated": offset + len(records) < total,
    }


TOOLS: tuple[SemanticTool, ...] = (
    SemanticTool(
        INTEGRITY_STATUS,
        "Report the integrity monitors of this server: what each one watches, whether it "
        "is running, when it last ran and what it found (the changed files by kind). "
        "Read-only; it starts no verification.",
        arguments_schema({"name": text("Only this monitor. Default: every monitor.", minLength=1)}),
        integrity_status,
    ),
    SemanticTool(
        AUDIT_SEARCH,
        "Search the audit trail: who did what, when, against which resource, with what "
        "result. Records come newest first and their number is capped: page with offset "
        "while 'truncated' is true. Pass the correlation_id of a tool result to see what "
        "that call did. Fails when the server keeps no audit trail.",
        arguments_schema(
            {
                **{
                    name: text(description, minLength=1)
                    for name, description in _EXACT_FILTERS.items()
                },
                "resource_prefix": text(
                    "Records whose resource (a storage URI) starts with this text.", minLength=1
                ),
                "text": text(
                    "Records that contain this text in any field or in their metadata.",
                    minLength=1,
                ),
                "since": text(
                    "Earliest time, included: ISO 8601 with an offset, 2026-10-08T00:00:00+00:00.",
                    minLength=1,
                ),
                "until": text("Latest time, excluded: ISO 8601 with an offset.", minLength=1),
                "limit": whole(
                    f"How many records. Default {_DEFAULT_AUDIT_LIMIT}; the server caps it."
                ),
                "offset": whole("How many records to skip. Default 0.", minimum=0, default=0),
            }
        ),
        audit_search,
    ),
)
