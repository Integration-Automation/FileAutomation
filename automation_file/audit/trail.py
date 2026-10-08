"""The audit trail: turn what happens into audit records.

An :class:`AuditTrail` listens to the event bus and to the storage observers
and appends one :class:`~automation_file.audit.record.AuditRecord` per event
and per storage operation to its store. Nothing writes an audit row itself:
components publish events, the storage layer reports its operations, and the
trail records both.

A failed storage operation is reported twice by the layers below -- as the
operation and as the ``storage.error`` event the storage bridge publishes for
it. The trail keeps the operation and skips that event, so it is recorded once.

Auditing never breaks what it audits: a record that cannot be built or written
is logged and dropped.

The process-wide :data:`audit_trail` has no store and records nothing until
:func:`configure_audit` gives it one.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from automation_file.audit.record import (
    STORAGE_SOURCE,
    AuditRecord,
    record_from_event,
    record_from_operation,
)
from automation_file.audit.sqlite_store import SQLiteAuditStore
from automation_file.audit.store import AuditStore
from automation_file.core.audit import AuditException
from automation_file.events import Event, EventBus, StorageError, Subscription, event_bus
from automation_file.logging_config import file_automation_logger
from automation_file.storage import observe
from automation_file.storage.observe import StorageOperation

_SubjectT = TypeVar("_SubjectT")
_BRIDGE_MARK = "error_type"


def _is_reported_operation(event: Event) -> bool:
    """Return whether ``event`` is the storage bridge's report of a failed operation."""
    return (
        event.type == StorageError.type
        and event.source == STORAGE_SOURCE
        and _BRIDGE_MARK in event.payload
    )


class AuditTrail:
    """Record events and storage operations into an :class:`AuditStore`."""

    def __init__(self, store: AuditStore | None = None, bus: EventBus | None = None) -> None:
        self._store = store
        self._owns_store = False
        self._bus = bus if bus is not None else event_bus
        self._lock = threading.RLock()
        self._subscription: Subscription | None = None

    @property
    def store(self) -> AuditStore | None:
        return self._store

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def active(self) -> bool:
        """Whether the trail is listening (between ``start`` and ``stop``)."""
        with self._lock:
            return self._subscription is not None

    def attach(self, store: AuditStore, *, owned: bool = False) -> None:
        """Record into ``store`` from now on.

        An ``owned`` store is closed by the trail when it is replaced or the
        trail is closed; a store the caller built stays the caller's to close.
        """
        if not isinstance(store, AuditStore):
            raise AuditException(f"expected AuditStore, got {type(store).__name__}")
        with self._lock:
            previous, was_owned = self._store, self._owns_store
            self._store, self._owns_store = store, owned
        if was_owned and previous is not None and previous is not store:
            previous.close()

    def start(self) -> None:
        """Listen to the bus and to the storage observers. Starting twice changes nothing."""
        with self._lock:
            if self._subscription is not None:
                return
            if self._store is None:
                raise AuditException("the audit trail has no store; attach one first")
            self._subscription = self._bus.subscribe(self._on_event)
            observe.add_listener(self._on_operation)
        file_automation_logger.info("audit trail: started")

    def stop(self) -> None:
        """Stop listening. Stopping an inactive trail changes nothing."""
        with self._lock:
            subscription, self._subscription = self._subscription, None
            if subscription is None:
                return
            self._bus.unsubscribe(subscription)
            observe.remove_listener(self._on_operation)
        file_automation_logger.info("audit trail: stopped")

    def close(self) -> None:
        """Stop listening and let go of the store, closing it when the trail owns it."""
        self.stop()
        with self._lock:
            store, owned = self._store, self._owns_store
            self._store, self._owns_store = None, False
        if owned and store is not None:
            store.close()

    def record(self, action: str, **details: Any) -> AuditRecord | None:
        """Append one record by hand and return it.

        ``details`` are the other :class:`AuditRecord` fields (``resource``,
        ``backend``, ``status``, ``source``, ``pipeline``, ``task``,
        ``duration_ms``, ``error``, ``metadata`` ...). The actor and the
        correlation ID default to those of the current scopes. A field that
        does not exist is the caller's mistake and raises; a failure to write
        is logged and gives ``None``, as does a trail without a store.
        """
        try:
            entry = AuditRecord(action=action, **details)
        except TypeError as err:
            raise AuditException(f"invalid audit record: {err}") from err
        return entry if self._append(entry) else None

    def search(self, **filters: Any) -> list[AuditRecord]:
        """Return the records of the store that pass ``filters``, newest first."""
        return self._require_store().search(**filters)

    def count(self, **filters: Any) -> int:
        """Return how many records of the store pass ``filters``."""
        return self._require_store().count(**filters)

    def purge(self, older_than_seconds: float) -> int:
        """Delete the records older than ``older_than_seconds``; return how many."""
        return self._require_store().purge(older_than_seconds)

    def _require_store(self) -> AuditStore:
        store = self._store
        if store is None:
            raise AuditException("audit is not configured; call configure_audit first")
        return store

    def _on_event(self, event: Event) -> None:
        if _is_reported_operation(event):
            return
        self._capture(record_from_event, event)

    def _on_operation(self, operation: StorageOperation) -> None:
        self._capture(record_from_operation, operation)

    def _capture(self, build: Callable[[_SubjectT], AuditRecord], subject: _SubjectT) -> None:
        try:
            entry = build(subject)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary: auditing must never fail the code that is audited.
            file_automation_logger.error("audit trail: cannot build a record: %r", error)
            return
        self._append(entry)

    def _append(self, entry: AuditRecord) -> bool:
        store = self._store
        if store is None:
            return False
        try:
            # A store built on the storage layer must not audit its own writes.
            with observe.suppressed():
                store.append(entry)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary: auditing must never fail the code that is audited.
            file_automation_logger.error(
                "audit trail: cannot write the record of %r: %r", entry.action, error
            )
            return False
        return True


audit_trail: AuditTrail = AuditTrail()


def configure_audit(target: AuditStore | str | os.PathLike[str]) -> AuditTrail:
    """Point the process-wide :data:`audit_trail` at ``target`` and start it.

    ``target`` is the path of a SQLite database (created when missing) or a
    ready :class:`AuditStore`. Calling it again switches the store; a store the
    trail opened from a path is closed when it is replaced.
    """
    if isinstance(target, AuditStore):
        audit_trail.attach(target)
    else:
        audit_trail.attach(SQLiteAuditStore(target), owned=True)
    audit_trail.start()
    return audit_trail


def audit_search(**filters: Any) -> list[dict[str, Any]]:
    """Search the process-wide audit trail; each record comes back as its ``to_dict()``.

    Filters: ``since``, ``until``, ``actor``, ``source``, ``pipeline``, ``task``,
    ``action``, ``resource_prefix``, ``backend``, ``status``, ``correlation_id``,
    ``text``, ``limit``, ``offset``. Newest first.
    """
    return [entry.to_dict() for entry in audit_trail.search(**filters)]
