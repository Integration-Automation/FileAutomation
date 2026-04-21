"""SQLite-backed audit log for executed actions.

``AuditLog(db_path)`` opens (or creates) a single-table SQLite database and
appends one row per action execution. Rows carry the timestamp, action name,
a JSON-encoded snapshot of the payload, the result / error repr, and the
duration in milliseconds.

Writes use a short-lived connection per call (``check_same_thread=False``
semantics) so the log is safe to share between background worker threads
and the scheduler. Readers call :meth:`AuditLog.recent` to pull the most
recent N rows.

The module deliberately avoids buffering / background queues: every row is
persisted synchronously with an ``INSERT`` inside a ``with connect(..)`` so
a crash at most loses the currently-executing action.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    action TEXT NOT NULL,
    payload TEXT NOT NULL,
    result TEXT,
    error TEXT,
    duration_ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts DESC);
"""


class AuditException(FileAutomationException):
    """Raised when the audit log cannot be opened or written."""


class AuditLog:
    """Synchronous SQLite audit log."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except (OSError, sqlite3.DatabaseError) as err:
            raise AuditException(f"cannot open audit log {self._db_path}: {err}") from err

    def record(
        self,
        action: str,
        payload: Any,
        *,
        result: Any = None,
        error: BaseException | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        """Append a single audit row. Never raises — failures are logged only."""
        row = (
            time.time(),
            action,
            _safe_json(payload),
            _safe_json(result) if result is not None else None,
            repr(error) if error is not None else None,
            float(duration_ms),
        )
        try:
            with self._lock, closing(self._connect()) as conn:
                conn.execute(
                    "INSERT INTO audit (ts, action, payload, result, error, duration_ms)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    row,
                )
                conn.commit()
        except sqlite3.DatabaseError as err:
            file_automation_logger.error("audit.record failed: %r", err)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the newest ``limit`` rows, newest first."""
        if limit <= 0:
            return []
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "SELECT id, ts, action, payload, result, error, duration_ms"
                " FROM audit ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "ts": row[1],
                "action": row[2],
                "payload": json.loads(row[3]) if row[3] else None,
                "result": json.loads(row[4]) if row[4] else None,
                "error": row[5],
                "duration_ms": row[6],
            }
            for row in rows
        ]

    def count(self) -> int:
        with closing(self._connect()) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM audit")
            (total,) = cursor.fetchone()
        return int(total)

    def purge(self, older_than_seconds: float) -> int:
        """Delete rows older than ``older_than_seconds`` and return the row count."""
        if older_than_seconds <= 0:
            raise AuditException("older_than_seconds must be positive")
        cutoff = time.time() - older_than_seconds
        with self._lock, closing(self._connect()) as conn:
            cursor = conn.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
            conn.commit()
            return int(cursor.rowcount)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=5.0)


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, default=repr, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(repr(value), ensure_ascii=False)
