"""Where audit records are kept: the store interface, its filters, an in-memory store.

:class:`AuditStore` is the interface every store implements -- the SQLite store
of this package today, a PostgreSQL or remote store later. A store appends
records and never changes one; it answers searches newest first.

Filters are passed by name to ``search`` and ``count``:

``since`` / ``until``
    The time range, ``since`` included and ``until`` excluded. An aware
    ``datetime``, an ISO 8601 string with an offset, or seconds since the epoch.
``actor``, ``source``, ``pipeline``, ``task``, ``action``, ``backend``, ``status``,
``correlation_id``
    Exact matches.
``resource_prefix``
    Records whose resource starts with the text.
``text``
    Records that contain the text in the action, resource, error, actor,
    source, pipeline, task, backend or the JSON of the metadata.
``limit`` / ``offset``
    Paging; ``limit`` defaults to :data:`DEFAULT_LIMIT` and may not exceed
    :data:`MAX_LIMIT`. ``count`` ignores both.

``resource_prefix`` and ``text`` take the text literally (``%`` and ``_`` are
ordinary characters) and ignore the case of ASCII letters. A filter left out,
or given as ``None``, does not restrict the search; an unknown filter name is
an error rather than a search that silently returns everything.
"""

from __future__ import annotations

import json
import string
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any, TypeVar

from automation_file.audit.record import AuditRecord, parse_time
from automation_file.core.audit import AuditException

DEFAULT_LIMIT = 100
MAX_LIMIT = 10_000
#: Filters compared for equality with the record field of the same name.
EXACT_FILTERS = (
    "actor",
    "source",
    "pipeline",
    "task",
    "action",
    "backend",
    "status",
    "correlation_id",
)
#: Record fields the ``text`` filter looks into, next to the metadata.
TEXT_FIELDS = ("action", "resource", "error", "actor", "source", "pipeline", "task", "backend")
LIKE_ESCAPE = "\\"

_TIME_FILTERS = ("since", "until")
_TEXT_FILTERS = (*EXACT_FILTERS, "resource_prefix", "text")
#: The paging filters and the highest value each may take (``None``: no ceiling).
_PAGE_FILTERS: dict[str, int | None] = {"limit": MAX_LIMIT, "offset": None}
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_StoreT = TypeVar("_StoreT", bound="AuditStore")


def escape_like(text: str) -> str:
    """Return ``text`` with the SQL ``LIKE`` wildcards escaped by :data:`LIKE_ESCAPE`."""
    return (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def metadata_json(record: AuditRecord) -> str:
    """Return the metadata of ``record`` as the JSON text a store keeps and searches."""
    return json.dumps(dict(record.metadata), ensure_ascii=False, sort_keys=True)


def _fold(text: str) -> str:
    """Lower the ASCII letters only, the way SQL ``LIKE`` compares."""
    return text.translate(_ASCII_LOWER)


def _page_number(value: object, name: str, maximum: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuditException(f"{name} must be an integer, 0 or more, got {value!r}")
    if maximum is not None and value > maximum:
        raise AuditException(f"{name} may not exceed {maximum}, got {value}")
    return value


@dataclass(frozen=True)
class AuditQuery:
    """The validated filters of one search."""

    since: datetime | None = None
    until: datetime | None = None
    actor: str | None = None
    source: str | None = None
    pipeline: str | None = None
    task: str | None = None
    action: str | None = None
    resource_prefix: str | None = None
    backend: str | None = None
    status: str | None = None
    correlation_id: str | None = None
    text: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_filters(cls, filters: Mapping[str, Any]) -> AuditQuery:
        """Validate the keyword filters of ``search`` / ``count`` into a query."""
        known = {entry.name for entry in fields(cls)}
        unknown = sorted(set(filters) - known)
        if unknown:
            raise AuditException(f"unknown audit filter(s) {unknown}; known: {sorted(known)}")
        given = {name: value for name, value in filters.items() if value is not None}
        for name in _TIME_FILTERS:
            if name in given:
                given[name] = parse_time(given[name], name)
        for name in _TEXT_FILTERS:
            if name in given and not isinstance(given[name], str):
                raise AuditException(f"{name} must be a string, got {given[name]!r}")
        for name, maximum in _PAGE_FILTERS.items():
            if name in given:
                given[name] = _page_number(given[name], name, maximum)
        return cls(**given)

    def matches(self, record: AuditRecord) -> bool:
        """Return whether ``record`` passes every filter but the paging."""
        if self.since is not None and record.timestamp < self.since:
            return False
        if self.until is not None and record.timestamp >= self.until:
            return False
        for name in EXACT_FILTERS:
            wanted = getattr(self, name)
            if wanted is not None and getattr(record, name) != wanted:
                return False
        return self._matches_resource(record) and self._matches_text(record)

    def _matches_resource(self, record: AuditRecord) -> bool:
        if not self.resource_prefix:
            return True
        return _fold(record.resource or "").startswith(_fold(self.resource_prefix))

    def _matches_text(self, record: AuditRecord) -> bool:
        if not self.text:
            return True
        needle = _fold(self.text)
        haystacks = [getattr(record, name) or "" for name in TEXT_FIELDS]
        haystacks.append(metadata_json(record))
        return any(needle in _fold(haystack) for haystack in haystacks)


class AuditStore(ABC):
    """The interface of a place that keeps audit records.

    A store is append-only, safe to share between threads, and answers
    ``search`` newest first. Every failure is an
    :class:`~automation_file.AuditException`. Implement the five methods and
    parse the filters with :meth:`AuditQuery.from_filters` to plug a new store
    into :class:`~automation_file.audit.trail.AuditTrail`.
    """

    @abstractmethod
    def append(self, record: AuditRecord) -> None:
        """Keep ``record``. A record whose ``id`` is already kept is an error."""

    @abstractmethod
    def search(self, **filters: Any) -> list[AuditRecord]:
        """Return the records that pass ``filters``, newest first."""

    @abstractmethod
    def count(self, **filters: Any) -> int:
        """Return how many records pass ``filters`` (``limit`` and ``offset`` are ignored)."""

    @abstractmethod
    def purge(self, older_than_seconds: float) -> int:
        """Delete the records older than ``older_than_seconds``; return how many."""

    @abstractmethod
    def close(self) -> None:
        """Release what the store holds open. Closing twice is harmless."""

    def __enter__(self: _StoreT) -> _StoreT:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def purge_cutoff(older_than_seconds: float) -> datetime:
    """Return the time before which ``purge(older_than_seconds)`` deletes."""
    if isinstance(older_than_seconds, bool) or not isinstance(older_than_seconds, (int, float)):
        raise AuditException(f"older_than_seconds must be a number, got {older_than_seconds!r}")
    if not older_than_seconds > 0:
        raise AuditException("older_than_seconds must be positive")
    try:
        return datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    except (OverflowError, ValueError) as err:
        raise AuditException(f"older_than_seconds is out of range: {older_than_seconds!r}") from err


class MemoryAuditStore(AuditStore):
    """An audit store that lives in the process; for tests and short-lived tools."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[AuditRecord] = []
        self._ids: set[str] = set()
        self._closed = False

    def append(self, record: AuditRecord) -> None:
        check_record(record)
        with self._lock:
            self._check_open()
            if record.id in self._ids:
                raise AuditException(f"audit record {record.id} is already stored")
            self._ids.add(record.id)
            self._records.append(record)

    def search(self, **filters: Any) -> list[AuditRecord]:
        query = AuditQuery.from_filters(filters)
        matched = self._matching(query)
        return matched[query.offset : query.offset + query.limit]

    def count(self, **filters: Any) -> int:
        return len(self._matching(AuditQuery.from_filters(filters)))

    def purge(self, older_than_seconds: float) -> int:
        cutoff = purge_cutoff(older_than_seconds)
        with self._lock:
            self._check_open()
            kept = [record for record in self._records if record.timestamp >= cutoff]
            removed = len(self._records) - len(kept)
            self._records = kept
            self._ids = {record.id for record in kept}
        return removed

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _matching(self, query: AuditQuery) -> list[AuditRecord]:
        """Return the matching records, newest first; the later of two equal times first."""
        with self._lock:
            self._check_open()
            numbered = list(enumerate(self._records))
        matched = [entry for entry in numbered if query.matches(entry[1])]
        matched.sort(key=lambda entry: (entry[1].timestamp, entry[0]), reverse=True)
        return [record for _, record in matched]

    def _check_open(self) -> None:
        if self._closed:
            raise AuditException("the audit store is closed")


def check_record(record: object) -> None:
    if not isinstance(record, AuditRecord):
        raise AuditException(f"expected AuditRecord, got {type(record).__name__}")
