"""The SQLite audit store.

:class:`SQLiteAuditStore` keeps the records of audit schema v2 in one table,
with a second table that states the schema version and indexes on the
timestamp, the correlation ID, the resource and the action. One connection is
shared by every thread behind a lock, in WAL mode so another process can read
while this one writes.

Every value reaches SQLite as a bound parameter. The text of a statement is
only ever assembled from the constant fragments of this module, which depend
on *which* filters are set and never on what they contain, and the ``LIKE``
wildcards in a ``resource_prefix`` or ``text`` filter are escaped.

:meth:`SQLiteAuditStore.import_v1` copies the rows of a v1
:class:`~automation_file.core.audit.AuditLog` database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from automation_file.audit.record import (
    STATUS_ERROR,
    STATUS_OK,
    AuditRecord,
    from_microseconds,
    parse_time,
    to_microseconds,
)
from automation_file.audit.store import (
    EXACT_FILTERS,
    LIKE_ESCAPE,
    TEXT_FIELDS,
    AuditQuery,
    AuditStore,
    check_record,
    escape_like,
    metadata_json,
    purge_cutoff,
)
from automation_file.core.audit import AuditException
from automation_file.logging_config import file_automation_logger

SCHEMA_VERSION = 2
#: The ``source`` of the records copied from a v1 audit log.
V1_SOURCE = "audit.v1"

_TIMEOUT_SECONDS = 5.0
_IMPORT_BATCH = 1000
_V1_ACTOR = "unknown"
_ID_LENGTH = 32
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_schema_version (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_records (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    ts_us INTEGER NOT NULL,
    actor TEXT NOT NULL,
    source TEXT NOT NULL,
    pipeline TEXT,
    task TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    backend TEXT,
    status TEXT NOT NULL,
    duration_ms REAL,
    error TEXT,
    metadata TEXT NOT NULL,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_records_ts ON audit_records (ts_us DESC, seq DESC);
CREATE INDEX IF NOT EXISTS idx_audit_records_correlation ON audit_records (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_records_resource ON audit_records (resource);
CREATE INDEX IF NOT EXISTS idx_audit_records_action ON audit_records (action);
"""
_COLUMNS = (
    "id, ts_us, actor, source, pipeline, task, action, resource, backend, status, "
    "duration_ms, error, metadata, correlation_id"
)
_PLACEHOLDERS = "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
# The two fragments are constants of this module; every value goes in as a parameter.
_INSERT = f"INSERT INTO audit_records ({_COLUMNS}) VALUES ({_PLACEHOLDERS})"  # nosec B608
_INSERT_NEW = f"INSERT OR IGNORE INTO audit_records ({_COLUMNS}) VALUES ({_PLACEHOLDERS})"
_SELECT = f"SELECT {_COLUMNS} FROM audit_records"  # nosec B608
_COUNT = "SELECT COUNT(*) FROM audit_records"
_NEWEST_FIRST = " ORDER BY ts_us DESC, seq DESC LIMIT ? OFFSET ?"
_PURGE = "DELETE FROM audit_records WHERE ts_us < ?"
_SINCE = "ts_us >= ?"
_UNTIL = "ts_us < ?"
_LIKE = f" LIKE ? ESCAPE '{LIKE_ESCAPE}'"
_EXACT = {name: f"{name} = ?" for name in EXACT_FILTERS}
_RESOURCE_PREFIX = f"resource{_LIKE}"
_TEXT_COLUMNS = (*TEXT_FIELDS, "metadata")
_TEXT = "(" + " OR ".join(f"{column}{_LIKE}" for column in _TEXT_COLUMNS) + ")"
_VERSION = "SELECT MAX(version) FROM audit_schema_version"
_V1_ROWS = "SELECT id, ts, action, payload, result, error, duration_ms FROM audit ORDER BY id"


def _where(query: AuditQuery) -> tuple[str, list[Any]]:
    """Return the ``WHERE`` clause of ``query`` and the values bound to its placeholders."""
    clauses: list[str] = []
    values: list[Any] = []
    if query.since is not None:
        clauses.append(_SINCE)
        values.append(to_microseconds(query.since))
    if query.until is not None:
        clauses.append(_UNTIL)
        values.append(to_microseconds(query.until))
    for name in EXACT_FILTERS:
        wanted = getattr(query, name)
        if wanted is not None:
            clauses.append(_EXACT[name])
            values.append(wanted)
    if query.resource_prefix:
        clauses.append(_RESOURCE_PREFIX)
        values.append(escape_like(query.resource_prefix) + "%")
    if query.text:
        clauses.append(_TEXT)
        values.extend([f"%{escape_like(query.text)}%"] * len(_TEXT_COLUMNS))
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), values


def _row(record: AuditRecord) -> tuple[Any, ...]:
    return (
        record.id,
        to_microseconds(record.timestamp),
        record.actor,
        record.source,
        record.pipeline,
        record.task,
        record.action,
        record.resource,
        record.backend,
        record.status,
        record.duration_ms,
        record.error,
        metadata_json(record),
        record.correlation_id,
    )


def _record(row: Sequence[Any]) -> AuditRecord:
    return AuditRecord(
        id=row[0],
        timestamp=from_microseconds(row[1]),
        actor=row[2],
        source=row[3],
        pipeline=row[4],
        task=row[5],
        action=row[6],
        resource=row[7],
        backend=row[8],
        status=row[9],
        duration_ms=row[10],
        error=row[11],
        metadata=json.loads(row[12]),
        correlation_id=row[13],
    )


def _decoded(text: str | None) -> Any:
    """Return the value a v1 row kept as JSON text, or the text itself when it is not JSON."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _v1_record(row: Sequence[Any]) -> AuditRecord:
    row_id, moment, action, payload, result, error, duration_ms = row
    # A digest of the row is its ID, so importing the same log twice adds nothing.
    digest = hashlib.sha256(f"{row_id}|{moment!r}|{action}|{payload}".encode()).hexdigest()
    return AuditRecord(
        id=digest[:_ID_LENGTH],
        timestamp=parse_time(float(moment)),
        actor=_V1_ACTOR,
        correlation_id=None,
        source=V1_SOURCE,
        action=str(action),
        status=STATUS_ERROR if error else STATUS_OK,
        duration_ms=float(duration_ms or 0.0),
        error=error,
        metadata={"v1_id": row_id, "payload": _decoded(payload), "result": _decoded(result)},
    )


class SQLiteAuditStore(AuditStore):
    """Audit records in a SQLite database at ``path``; created when missing."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._closed = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self._path, timeout=_TIMEOUT_SECONDS, check_same_thread=False
            )
        except (OSError, sqlite3.Error) as err:
            raise AuditException(f"cannot open audit store {self._path}: {err}") from err
        try:
            self._prepare()
        except (AuditException, sqlite3.Error) as err:
            self._conn.close()
            raise AuditException(f"cannot open audit store {self._path}: {err}") from err

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> int:
        """The schema version the database states."""
        return int(self._fetch(_VERSION, ())[0][0])

    def append(self, record: AuditRecord) -> None:
        check_record(record)
        try:
            with self._lock, self._conn:
                # nosemgrep  # a constant statement with bound parameters
                self._conn.execute(_INSERT, _row(record))
        except sqlite3.IntegrityError as err:
            raise AuditException(f"audit record {record.id} is already stored") from err
        except sqlite3.Error as err:
            raise AuditException(f"cannot write audit record {record.id}: {err}") from err

    def search(self, **filters: Any) -> list[AuditRecord]:
        query = AuditQuery.from_filters(filters)
        if query.limit == 0:
            return []
        where, values = _where(query)
        rows = self._fetch(_SELECT + where + _NEWEST_FIRST, [*values, query.limit, query.offset])
        return [_record(row) for row in rows]

    def count(self, **filters: Any) -> int:
        where, values = _where(AuditQuery.from_filters(filters))
        return int(self._fetch(_COUNT + where, values)[0][0])

    def purge(self, older_than_seconds: float) -> int:
        cutoff = to_microseconds(purge_cutoff(older_than_seconds))
        try:
            with self._lock, self._conn:
                return int(self._conn.execute(_PURGE, (cutoff,)).rowcount)
        except sqlite3.Error as err:
            raise AuditException(f"cannot purge the audit store: {err}") from err

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()

    def import_v1(self, db_path: str | os.PathLike[str]) -> int:
        """Copy the rows of the v1 ``AuditLog`` database at ``db_path``.

        Each row becomes a record with the source ``audit.v1``; its payload and
        result go under ``metadata``. Returns how many rows were new: importing
        the same log again adds nothing. The v1 database is only read.
        """
        source = Path(db_path)
        if not source.is_file():
            raise AuditException(f"v1 audit log not found: {source}")
        try:
            with closing(sqlite3.connect(source, timeout=_TIMEOUT_SECONDS)) as old:
                imported = self._copy(_v1_batches(old))
        except (sqlite3.Error, TypeError, ValueError) as err:
            raise AuditException(f"cannot import the v1 audit log {source}: {err}") from err
        file_automation_logger.info("audit: imported %d v1 row(s) from %s", imported, source)
        return imported

    def _copy(self, batches: Iterator[list[tuple[Any, ...]]]) -> int:
        with self._lock, self._conn:
            before = self._conn.total_changes
            for batch in batches:
                self._conn.executemany(_INSERT_NEW, batch)
            return self._conn.total_changes - before

    def _fetch(self, statement: str, values: Sequence[Any]) -> list[Any]:
        # ``statement`` is one of this module's constants, with the WHERE clause that
        # _where() joined from constants; ``values`` are bound, never interpolated.
        try:
            with self._lock:
                return self._conn.execute(statement, values).fetchall()
        except sqlite3.Error as err:
            raise AuditException(f"cannot read the audit store: {err}") from err

    def _prepare(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        found = self._conn.execute(_VERSION).fetchone()[0]
        if found is None:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO audit_schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
                )
        elif found != SCHEMA_VERSION:
            raise AuditException(
                f"audit schema version {found} is not supported (this version reads "
                f"{SCHEMA_VERSION})"
            )


def _v1_batches(old: sqlite3.Connection) -> Iterator[list[tuple[Any, ...]]]:
    cursor = old.execute(_V1_ROWS)
    while True:
        rows = cursor.fetchmany(_IMPORT_BATCH)
        if not rows:
            return
        yield [_row(_v1_record(row)) for row in rows]
