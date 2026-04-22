"""Persistent SQLite-backed queue of action payloads.

Producers call :meth:`ActionQueue.enqueue` to durably store a JSON action list;
consumers pull with :meth:`dequeue` (marking the row ``inflight``) and finalise
with :meth:`ack` or :meth:`nack`. The queue survives process restarts — all
state lives in the SQLite file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from automation_file.exceptions import QueueException
from automation_file.logging_config import file_automation_logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    run_at      REAL NOT NULL,
    enqueued_at REAL NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'ready',
    last_error  TEXT
);
CREATE INDEX IF NOT EXISTS idx_queue_ready
    ON action_queue (status, run_at, priority DESC, id);
"""

_STATUS_READY = "ready"
_STATUS_INFLIGHT = "inflight"
_STATUS_DEAD = "dead"


@dataclass(frozen=True)
class QueueItem:
    """A claimed queue row returned by :meth:`ActionQueue.dequeue`."""

    id: int
    action: list[Any] | dict[str, Any]
    attempts: int
    enqueued_at: float


class ActionQueue:
    """Durable FIFO / priority queue for JSON action payloads."""

    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)

    def enqueue(
        self,
        action: list[Any] | dict[str, Any],
        priority: int = 0,
        run_at: float | None = None,
    ) -> int:
        """Persist ``action`` for later dispatch. Returns the row id."""
        if not isinstance(action, list | dict):
            raise QueueException("action must be a list or dict")
        payload = json.dumps(action, ensure_ascii=False)
        now = time.time()
        due = run_at if run_at is not None else now
        with self._lock, closing(self._connect()) as conn:
            cur = conn.execute(
                "INSERT INTO action_queue"
                " (action, priority, run_at, enqueued_at) VALUES (?, ?, ?, ?)",
                (payload, priority, due, now),
            )
            row_id = cur.lastrowid
            if row_id is None:
                raise QueueException("failed to allocate queue row id")
            return row_id

    def dequeue(self) -> QueueItem | None:
        """Claim the next ready row; returns ``None`` if the queue is empty."""
        now = time.time()
        with self._lock, closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT id, action, attempts, enqueued_at FROM action_queue"
                    " WHERE status=? AND run_at<=?"
                    " ORDER BY priority DESC, id ASC LIMIT 1",
                    (_STATUS_READY, now),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return None
                row_id, payload, attempts, enqueued_at = row
                conn.execute(
                    "UPDATE action_queue SET status=?, attempts=attempts+1 WHERE id=?",
                    (_STATUS_INFLIGHT, row_id),
                )
                conn.execute("COMMIT")
            except sqlite3.OperationalError as error:
                raise QueueException(f"dequeue failed: {error}") from error
            try:
                action = json.loads(payload)
            except json.JSONDecodeError as error:
                raise QueueException(f"corrupt queue row {row_id}: {error}") from error
            return QueueItem(
                id=int(row_id),
                action=action,
                attempts=int(attempts) + 1,
                enqueued_at=float(enqueued_at),
            )

    def ack(self, item_id: int) -> None:
        """Finalise a claimed row as processed."""
        with self._lock, closing(self._connect()) as conn:
            conn.execute("DELETE FROM action_queue WHERE id=?", (item_id,))

    def nack(
        self,
        item_id: int,
        *,
        requeue: bool = True,
        reason: str = "",
        delay: float = 0.0,
    ) -> None:
        """Return a claimed row to the queue (``requeue=True``) or mark as dead."""
        next_status = _STATUS_READY if requeue else _STATUS_DEAD
        run_at = time.time() + max(delay, 0.0)
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE action_queue SET status=?, last_error=?, run_at=? WHERE id=?",
                (next_status, reason or None, run_at, item_id),
            )

    def size(self, status: str = _STATUS_READY) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM action_queue WHERE status=?",
                (status,),
            ).fetchone()
            return int(row[0]) if row else 0

    def purge(self) -> int:
        """Delete every row (ready / inflight / dead). Returns rows deleted."""
        with self._lock, closing(self._connect()) as conn:
            cur = conn.execute("DELETE FROM action_queue")
            return int(cur.rowcount or 0)

    def dead_letters(self) -> list[QueueItem]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, action, attempts, enqueued_at FROM action_queue WHERE status=?",
                (_STATUS_DEAD,),
            ).fetchall()
        items: list[QueueItem] = []
        for row_id, payload, attempts, enqueued_at in rows:
            try:
                action = json.loads(payload)
            except json.JSONDecodeError:
                file_automation_logger.warning("queue: skipping unparseable dead row %s", row_id)
                continue
            items.append(
                QueueItem(
                    id=int(row_id),
                    action=action,
                    attempts=int(attempts),
                    enqueued_at=float(enqueued_at),
                )
            )
        return items
