"""``FA_audit_*`` actions: the audit trail for JSON action lists.

.. code-block:: json

    [
        ["FA_audit_configure", {"db_path": "/var/lib/automation_file/audit.sqlite"}],
        ["FA_audit_search", {"status": "error", "since": "2026-10-01T00:00:00+00:00", "limit": 50}],
        ["FA_audit_count", {"correlation_id": "4f0c2b6e9d5a4c1f8a7b3e2d1c0f9a8b"}],
        ["FA_audit_purge", {"older_than_seconds": 7776000}]
    ]

The search and count actions take the filters of
:class:`~automation_file.audit.store.AuditStore` by name and act on the
process-wide trail that ``FA_audit_configure`` set up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from automation_file.audit.sqlite_store import SQLiteAuditStore
from automation_file.audit.trail import audit_search, audit_trail, configure_audit

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry


def audit_configure(db_path: str) -> dict[str, Any]:
    """Keep the audit trail in the SQLite database ``db_path`` and start recording.

    Returns ``{"active": ..., "db_path": ..., "schema_version": ...}``.
    """
    trail = configure_audit(db_path)
    store = trail.store
    described: dict[str, Any] = {"active": trail.active}
    if isinstance(store, SQLiteAuditStore):
        described["db_path"] = str(store.path)
        described["schema_version"] = store.schema_version
    return described


def audit_count(**filters: Any) -> int:
    """Return how many audit records pass the filters (the same ones as ``FA_audit_search``)."""
    return audit_trail.count(**filters)


def audit_purge(older_than_seconds: float) -> int:
    """Delete the audit records older than ``older_than_seconds``; return how many."""
    return audit_trail.purge(older_than_seconds)


def register_audit_ops(registry: ActionRegistry) -> None:
    """Wire the ``FA_audit_*`` actions into a registry."""
    registry.register_many(
        {
            "FA_audit_configure": audit_configure,
            "FA_audit_search": audit_search,
            "FA_audit_count": audit_count,
            "FA_audit_purge": audit_purge,
        }
    )
