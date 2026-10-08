"""The audit record: who did what, when, against which resource, with what result.

One :class:`AuditRecord` answers the audit questions for one thing that
happened: ``actor`` did ``action`` at ``timestamp`` against ``resource`` using
``backend``, and it ended with ``status`` (and ``error``). ``pipeline``,
``task`` and ``correlation_id`` place it in a run; ``metadata`` keeps the
rest.

Records are frozen and JSON-friendly. :func:`record_from_event` and
:func:`record_from_operation` build them from the two things the audit trail
listens to.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from automation_file.core.audit import AuditException
from automation_file.events.context import current_actor, current_correlation_id
from automation_file.events.model import Severity

if TYPE_CHECKING:
    from automation_file.events.model import Event
    from automation_file.storage.observe import StorageOperation

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
#: The ``source`` of the records made from storage operations.
STORAGE_SOURCE = "storage"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)
_ZULU = "Z"
_UTC_OFFSET = "+00:00"
#: Payload keys of an event that fill the record field of the same name, as text.
_PAYLOAD_TEXT = ("pipeline", "task", "resource", "backend", "error")
_REQUIRED_TEXT = ("id", "actor", "source", "action", "status")
_OPTIONAL_TEXT = (*_PAYLOAD_TEXT, "correlation_id")
_DURATION = "duration_ms"
_STATUS_BY_SEVERITY = {
    Severity.INFO: STATUS_OK,
    Severity.WARNING: STATUS_WARNING,
    Severity.ERROR: STATUS_ERROR,
    Severity.CRITICAL: STATUS_ERROR,
}


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_microseconds(moment: datetime) -> int:
    """Return an aware ``moment`` as whole microseconds since the Unix epoch."""
    return (moment - _EPOCH) // _MICROSECOND


def from_microseconds(value: int) -> datetime:
    """Return the UTC time that is ``value`` microseconds after the Unix epoch."""
    return _EPOCH + timedelta(microseconds=value)


def parse_time(value: object, name: str = "timestamp") -> datetime:
    """Return ``value`` as an aware UTC time.

    Accepts an aware ``datetime``, an ISO 8601 string with an offset (or a
    trailing ``Z``), or a number of seconds since the Unix epoch. A time without
    a time zone is rejected: it would be a guess.
    """
    if isinstance(value, bool):
        raise AuditException(f"{name} must be a time, got {value!r}")
    if isinstance(value, (int, float)):
        try:
            return _EPOCH + timedelta(seconds=value)
        except (OverflowError, ValueError) as err:
            raise AuditException(f"{name} is out of range: {value!r}") from err
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(_ZULU):
            text = text[: -len(_ZULU)] + _UTC_OFFSET
        try:
            value = datetime.fromisoformat(text)
        except ValueError as err:
            raise AuditException(f"{name} is not an ISO 8601 time: {value!r}") from err
    if not isinstance(value, datetime):
        raise AuditException(f"{name} must be a time, got {value!r}")
    if value.utcoffset() is None:
        raise AuditException(f"{name} needs a time zone, got {value.isoformat()!r}")
    return value.astimezone(timezone.utc)


def _check_text(name: str, value: object, *, optional: bool) -> None:
    if isinstance(value, str) or (optional and value is None):
        return
    wanted = "a string or None" if optional else "a string"
    raise AuditException(f"{name} must be {wanted}, got {value!r}")


def _json_safe(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``metadata`` as plain JSON values; what JSON cannot hold becomes its ``repr``."""
    try:
        return dict(json.loads(json.dumps(dict(metadata), default=repr)))
    except (TypeError, ValueError):
        return {str(key): repr(value) for key, value in dict(metadata).items()}


@dataclass(frozen=True, kw_only=True)
class AuditRecord:
    """One audited thing that happened. Fields left out are filled from the current scopes."""

    id: str = field(default_factory=_new_id)
    timestamp: datetime = field(default_factory=_now)
    actor: str = field(default_factory=current_actor)
    source: str = ""
    pipeline: str | None = None
    task: str | None = None
    action: str = ""
    resource: str | None = None
    backend: str | None = None
    status: str = STATUS_OK
    duration_ms: float | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)
    correlation_id: str | None = field(default_factory=current_correlation_id)

    def __post_init__(self) -> None:
        for name in _REQUIRED_TEXT:
            _check_text(name, getattr(self, name), optional=False)
        for name in _OPTIONAL_TEXT:
            _check_text(name, getattr(self, name), optional=True)
        if not self.id:
            raise AuditException("an audit record needs a non-empty id")
        if not isinstance(self.metadata, Mapping):
            raise AuditException(f"metadata must be a mapping, got {self.metadata!r}")
        object.__setattr__(self, "timestamp", parse_time(self.timestamp))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))
        if self.duration_ms is not None:
            object.__setattr__(self, _DURATION, _as_duration(self.duration_ms))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the record, its keys in field order."""
        document = {entry.name: getattr(self, entry.name) for entry in fields(self)}
        document["timestamp"] = self.timestamp.isoformat()
        document["metadata"] = dict(self.metadata)
        return document

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> AuditRecord:
        """Build a record from what :meth:`to_dict` returned."""
        if not isinstance(document, Mapping):
            raise AuditException(f"an audit record is a mapping, got {document!r}")
        known = {entry.name for entry in fields(cls)}
        unknown = sorted(set(document) - known)
        if unknown:
            raise AuditException(f"unknown audit record field(s) {unknown}")
        try:
            return cls(**dict(document))
        except TypeError as err:
            raise AuditException(f"invalid audit record: {err}") from err


def _as_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuditException(f"{_DURATION} must be a number, got {value!r}")
    return float(value)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def record_from_event(event: Event) -> AuditRecord:
    """Return the audit record of ``event``.

    ``action`` is the event type. ``pipeline``, ``task``, ``resource``,
    ``backend``, ``status``, ``duration_ms`` and ``error`` come from the payload
    keys of the same name; the event's subject and severity and every other
    payload key go under ``metadata``. Without a ``status`` in the payload the
    severity decides: ``ok`` for info, ``warning``, and ``error`` for error and
    critical.
    """
    details = dict(event.payload)
    status = details.pop("status", None)
    duration = details.get(_DURATION)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        duration = None  # not a number: it stays under the metadata as it is
    else:
        del details[_DURATION]
    placed: dict[str, Any] = {key: _text(details.pop(key, None)) for key in _PAYLOAD_TEXT}
    return AuditRecord(
        id=event.id,
        timestamp=event.timestamp,
        actor=event.actor,
        correlation_id=event.correlation_id,
        source=event.source,
        action=event.type,
        status=str(status) if status else _STATUS_BY_SEVERITY[event.severity],
        duration_ms=duration,
        metadata={**details, "subject": event.subject, "severity": event.severity.value},
        **placed,
    )


def record_from_operation(operation: StorageOperation) -> AuditRecord:
    """Return the audit record of one storage operation.

    ``source`` is ``"storage"``, ``action`` the operation (``upload``,
    ``download``, ``read``, ``delete``, ``mkdir``, ``copy``, ``move``),
    ``resource`` its URI. The actor and the correlation ID are those of the
    scope the operation ran in.
    """
    metadata: dict[str, Any] = {}
    if operation.source_uri is not None:
        metadata["source_uri"] = operation.source_uri
    if operation.error_type is not None:
        metadata["error_type"] = operation.error_type
    return AuditRecord(
        source=STORAGE_SOURCE,
        action=operation.operation,
        resource=operation.uri,
        backend=operation.backend,
        status=operation.status,
        duration_ms=operation.duration_ms,
        error=operation.error,
        metadata=metadata,
    )
