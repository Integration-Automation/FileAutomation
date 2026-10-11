"""The Audit service: point the audit trail at a store and search it.

.. code-block:: python

    from automation_file.app import app_services

    audit = app_services().audit
    audit.configure("/var/lib/automation_file/audit.sqlite")
    audit.search(status="error", resource_prefix="s3://reports/", limit=20)
    audit.count(actor="scheduler")

The trail records nothing until it has a store, so :meth:`AuditService.recent`
returns an empty list instead of raising while audit is not configured: a
dashboard can call it without asking first. Records come back as dictionaries
with their secrets masked.
"""

from __future__ import annotations

import os
from dataclasses import fields
from typing import Any

from automation_file.app.masking import mask_secrets
from automation_file.audit import (
    DEFAULT_LIMIT,
    AuditQuery,
    AuditStore,
    AuditTrail,
    SQLiteAuditStore,
    audit_trail,
)

_RECENT_LIMIT = 50


def _given(filters: dict[str, Any]) -> dict[str, Any]:
    """Drop the filters a form left empty."""
    return {
        name: value
        for name, value in filters.items()
        if value is not None and not (isinstance(value, str) and not value.strip())
    }


class AuditService:
    """Configure, search and count on one :class:`~automation_file.audit.AuditTrail`."""

    def __init__(self, trail: AuditTrail | None = None) -> None:
        self._trail = audit_trail if trail is None else trail

    def filter_names(self) -> tuple[str, ...]:
        """Return the names :meth:`search` and :meth:`count` accept as filters."""
        return tuple(entry.name for entry in fields(AuditQuery))

    def is_configured(self) -> bool:
        """Return whether the trail has a store to record into."""
        return self._trail.store is not None

    def status(self) -> dict[str, Any]:
        """Return whether audit is configured and recording, and where the records go."""
        store = self._trail.store
        described: dict[str, Any] = {
            "configured": store is not None,
            "active": self._trail.active,
            "store": None if store is None else type(store).__name__,
            "db_path": None,
            "schema_version": None,
        }
        if isinstance(store, SQLiteAuditStore):
            described["db_path"] = str(store.path)
            described["schema_version"] = store.schema_version
        return described

    def configure(self, target: AuditStore | str | os.PathLike[str]) -> dict[str, Any]:
        """Record into ``target`` from now on and return :meth:`status`.

        ``target`` is the path of a SQLite database (created when missing) or a
        ready :class:`~automation_file.audit.AuditStore`.
        """
        if isinstance(target, AuditStore):
            self._trail.attach(target)
        else:
            self._trail.attach(SQLiteAuditStore(target), owned=True)
        self._trail.start()
        return self.status()

    def search(self, **filters: Any) -> list[dict[str, Any]]:
        """Return the records that pass ``filters``, newest first.

        Filters: ``since``, ``until``, ``actor``, ``source``, ``pipeline``,
        ``task``, ``action``, ``resource_prefix``, ``backend``, ``status``,
        ``correlation_id``, ``text``, ``limit``, ``offset``. A filter left empty
        does not restrict the search. Raises ``AuditException`` when audit is
        not configured or a filter is not known.
        """
        return [mask_secrets(entry.to_dict()) for entry in self._trail.search(**_given(filters))]

    def count(self, **filters: Any) -> int:
        """Return how many records pass ``filters`` (paging is ignored)."""
        return self._trail.count(**_given(filters))

    def recent(self, limit: int = _RECENT_LIMIT) -> list[dict[str, Any]]:
        """Return the latest records, or nothing while audit is not configured."""
        if not self.is_configured():
            return []
        return self.search(limit=max(min(limit, DEFAULT_LIMIT), 1))
