"""SQLite-backed named lock for multi-process / multi-host coordination.

Unlike :class:`automation_file.core.file_lock.FileLock` which locks a single
file descriptor, :class:`SQLiteLock` persists named leases in a shared SQLite
database. Any process that can open the database can participate. Leases carry
an optional TTL so crashed owners eventually free the slot.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import TracebackType

from automation_file.exceptions import LockTimeoutException

_SCHEMA = """
CREATE TABLE IF NOT EXISTS automation_locks (
    name       TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at  REAL
)
"""
_POLL_INTERVAL = 0.05


class SQLiteLock:
    """Named lease stored in SQLite.

    ``db_path`` is the SQLite file — callers sharing a lock must point at the
    same file. ``name`` is the lock identity. ``ttl`` (seconds) lets a crashed
    owner's lease expire; ``None`` means the lease is held until explicit
    release. ``timeout`` bounds acquisition wait.
    """

    def __init__(
        self,
        db_path: str | os.PathLike[str],
        name: str,
        timeout: float | None = None,
        ttl: float | None = None,
    ) -> None:
        if not name:
            raise ValueError("lock name must be non-empty")
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be > 0 when set")
        self._db_path = Path(db_path)
        self._name = name
        self._timeout = timeout
        self._ttl = ttl
        self._owner = uuid.uuid4().hex
        self._held = False
        self._thread_lock = threading.Lock()
        self._ensure_schema()

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def is_held(self) -> bool:
        return self._held

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(_SCHEMA)

    def acquire(self) -> None:
        """Block until the lease is granted; raise :class:`LockTimeoutException` on timeout."""
        with self._thread_lock:
            if self._held:
                raise LockTimeoutException(f"lock {self._name!r} already held by this instance")
            deadline = None if self._timeout is None else time.monotonic() + self._timeout
            while True:
                if self._try_claim():
                    self._held = True
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    raise LockTimeoutException(
                        f"timed out acquiring lock {self._name!r} after {self._timeout}s"
                    )
                time.sleep(_POLL_INTERVAL)

    def _try_claim(self) -> bool:
        now = time.time()
        expires = now + self._ttl if self._ttl is not None else None
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT owner, expires_at FROM automation_locks WHERE name=?",
                    (self._name,),
                ).fetchone()
                if row is not None:
                    _, row_expires = row
                    if row_expires is None or row_expires > now:
                        conn.execute("ROLLBACK")
                        return False
                conn.execute(
                    "INSERT OR REPLACE INTO automation_locks"
                    " (name, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                    (self._name, self._owner, now, expires),
                )
                conn.execute("COMMIT")
                return True
            except sqlite3.OperationalError:
                return False

    def release(self) -> None:
        """Release the lease; idempotent. Only the owning instance removes the row."""
        with self._thread_lock:
            if not self._held:
                return
            with closing(self._connect()) as conn:
                conn.execute(
                    "DELETE FROM automation_locks WHERE name=? AND owner=?",
                    (self._name, self._owner),
                )
            self._held = False

    def refresh(self) -> None:
        """Extend the lease by ``ttl`` seconds. No-op when ttl is unset."""
        if self._ttl is None:
            return
        with self._thread_lock:
            if not self._held:
                return
            now = time.time()
            with closing(self._connect()) as conn:
                conn.execute(
                    "UPDATE automation_locks SET expires_at=? WHERE name=? AND owner=?",
                    (now + self._ttl, self._name, self._owner),
                )

    def __enter__(self) -> SQLiteLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
