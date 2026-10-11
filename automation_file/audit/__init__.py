"""Audit schema v2: who did what, when, against which resource, with what result.

An :class:`AuditTrail` listens to the event bus and to the storage observers
and appends one :class:`AuditRecord` per event and per storage operation to an
:class:`AuditStore`. :class:`SQLiteAuditStore` is the store that ships;
:class:`MemoryAuditStore` serves tests; a PostgreSQL or remote store implements
the same five methods.

.. code-block:: python

    from automation_file import audit_search, configure_audit

    configure_audit("audit.sqlite")
    ...                                   # events and storage operations are recorded
    audit_search(status="error", resource_prefix="s3://reports/", limit=20)

The v1 :class:`~automation_file.core.audit.AuditLog` stays as it is;
:meth:`SQLiteAuditStore.import_v1` copies its rows.
"""

from __future__ import annotations

from automation_file.audit.actions import (
    audit_configure,
    audit_count,
    audit_purge,
    register_audit_ops,
)
from automation_file.audit.record import (
    AuditRecord,
    record_from_event,
    record_from_operation,
)
from automation_file.audit.sqlite_store import SCHEMA_VERSION, SQLiteAuditStore
from automation_file.audit.store import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    AuditQuery,
    AuditStore,
    MemoryAuditStore,
)
from automation_file.audit.trail import (
    AuditTrail,
    audit_search,
    audit_trail,
    configure_audit,
)
from automation_file.core.audit import AuditException

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "SCHEMA_VERSION",
    "AuditException",
    "AuditQuery",
    "AuditRecord",
    "AuditStore",
    "AuditTrail",
    "MemoryAuditStore",
    "SQLiteAuditStore",
    "audit_configure",
    "audit_count",
    "audit_purge",
    "audit_search",
    "audit_trail",
    "configure_audit",
    "record_from_event",
    "record_from_operation",
    "register_audit_ops",
]
