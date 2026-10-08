"""Where runs are recorded: every task transition as it happens, and the history afterwards.

A :class:`RunStore` is what makes checkpoint and resume, idempotency keys and the
execution history work. :class:`MemoryRunStore` keeps runs for the life of the
process and is the default; :class:`SQLiteRunStore` keeps them in a file, so a run
can be resumed and an idempotency key honoured after a restart.

Both keep the JSON form of a run (:meth:`PipelineRun.to_dict`): what comes back
from a store is a copy, and a result JSON cannot hold comes back as its ``repr``.
Parameters and results are stored as given, so keep secrets out of them.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from automation_file.pipeline.errors import PipelineException
from automation_file.pipeline.model import PipelineRun, TaskRun, TaskStatus

_SCHEMA_VERSION = "1"
_VERSION_KEY = "schema_version"
_DEFAULT_MEMORY_RUNS = 1000
_BUSY_SECONDS = 5.0
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    pipeline TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    params TEXT NOT NULL,
    error TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs (pipeline, started_at);
CREATE TABLE IF NOT EXISTS pipeline_tasks (
    run_id TEXT NOT NULL,
    task TEXT NOT NULL,
    position INTEGER NOT NULL,
    status TEXT NOT NULL,
    level INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    result TEXT NOT NULL,
    result_is_repr INTEGER NOT NULL,
    error TEXT,
    reason TEXT,
    idempotency_key TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (run_id, task)
);
CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_key ON pipeline_tasks (task, idempotency_key);
"""
_SELECT_VERSION = "SELECT value FROM pipeline_meta WHERE key = ?"
_INSERT_VERSION = "INSERT INTO pipeline_meta (key, value) VALUES (?, ?)"
_UPSERT_RUN = (
    "INSERT INTO pipeline_runs"
    " (run_id, pipeline, status, dry_run, params, error, started_at, finished_at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    " ON CONFLICT (run_id) DO UPDATE SET pipeline = excluded.pipeline,"
    " status = excluded.status, dry_run = excluded.dry_run, params = excluded.params,"
    " error = excluded.error, started_at = excluded.started_at,"
    " finished_at = excluded.finished_at"
)
_RUN_EXISTS = "SELECT 1 FROM pipeline_runs WHERE run_id = ?"
_DELETE_TASKS = "DELETE FROM pipeline_tasks WHERE run_id = ?"
_UPSERT_TASK = (
    "INSERT INTO pipeline_tasks"
    " (run_id, position, task, status, level, attempts, result, result_is_repr, error,"
    " reason, idempotency_key, started_at, finished_at)"
    " VALUES (?, (SELECT COALESCE(MAX(position), -1) + 1 FROM pipeline_tasks WHERE run_id = ?),"
    " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    " ON CONFLICT (run_id, task) DO UPDATE SET status = excluded.status,"
    " level = excluded.level, attempts = excluded.attempts, result = excluded.result,"
    " result_is_repr = excluded.result_is_repr, error = excluded.error,"
    " reason = excluded.reason, idempotency_key = excluded.idempotency_key,"
    " started_at = excluded.started_at, finished_at = excluded.finished_at"
)
_SELECT_RUN = (
    "SELECT run_id, pipeline, status, dry_run, params, error, started_at, finished_at"
    " FROM pipeline_runs WHERE run_id = ?"
)
_SELECT_RUNS = (
    "SELECT run_id, pipeline, status, dry_run, params, error, started_at, finished_at"
    " FROM pipeline_runs WHERE (? IS NULL OR pipeline = ?)"
    " ORDER BY started_at DESC, rowid DESC LIMIT ?"
)
_SELECT_TASKS = (
    "SELECT task, status, level, attempts, result, result_is_repr, error, reason,"
    " idempotency_key, started_at, finished_at"
    " FROM pipeline_tasks WHERE run_id = ? ORDER BY position"
)
_SELECT_IDEMPOTENT = (
    "SELECT t.task, t.status, t.level, t.attempts, t.result, t.result_is_repr, t.error,"
    " t.reason, t.idempotency_key, t.started_at, t.finished_at"
    " FROM pipeline_tasks AS t JOIN pipeline_runs AS r ON r.run_id = t.run_id"
    " WHERE r.pipeline = ? AND t.task = ? AND t.idempotency_key = ? AND t.status = ?"
    " ORDER BY t.finished_at DESC LIMIT 1"
)


class RunStore(ABC):
    """The contract of a run store. Every method is safe to call from several threads."""

    @abstractmethod
    def save_run(self, run: PipelineRun) -> None:
        """Record ``run`` with all of its tasks, replacing what was stored under its ID."""

    @abstractmethod
    def save_task(self, run_id: str, task: TaskRun) -> None:
        """Record one task of a stored run; an unknown ``run_id`` raises ``PipelineException``."""

    @abstractmethod
    def get_run(self, run_id: str) -> PipelineRun | None:
        """Return the stored run, or ``None`` when there is none with that ID."""

    @abstractmethod
    def list_runs(self, pipeline: str | None = None, limit: int = 50) -> list[PipelineRun]:
        """Return up to ``limit`` runs, newest first, of one pipeline or of all."""

    @abstractmethod
    def find_idempotent(self, pipeline: str, task: str, key: str) -> TaskRun | None:
        """Return the latest succeeded execution of ``task`` in ``pipeline`` under ``key``."""


class MemoryRunStore(RunStore):
    """Runs kept in memory, for the life of the process.

    At most ``max_runs`` are kept; the oldest are dropped first, and with them the
    idempotency keys they held.
    """

    def __init__(self, max_runs: int = _DEFAULT_MEMORY_RUNS) -> None:
        if max_runs < 1:
            raise ValueError("max_runs must be >= 1")
        self._max_runs = max_runs
        self._lock = threading.Lock()
        self._runs: dict[str, dict[str, Any]] = {}

    def save_run(self, run: PipelineRun) -> None:
        record = run.to_dict()
        with self._lock:
            self._runs[run.run_id] = record
            while len(self._runs) > self._max_runs:
                del self._runs[next(iter(self._runs))]

    def save_task(self, run_id: str, task: TaskRun) -> None:
        record = task.to_dict()
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise PipelineException(f"unknown run {run_id!r}")
            run["tasks"][task.task] = record

    def get_run(self, run_id: str) -> PipelineRun | None:
        with self._lock:
            record = copy.deepcopy(self._runs.get(run_id))
        return None if record is None else PipelineRun.from_dict(record)

    def list_runs(self, pipeline: str | None = None, limit: int = 50) -> list[PipelineRun]:
        with self._lock:
            chosen = [
                record
                for record in reversed(self._runs.values())
                if pipeline is None or record["pipeline"] == pipeline
            ]
            chosen.sort(key=lambda record: record["started_at"] or "", reverse=True)
            records = copy.deepcopy(chosen[: max(limit, 0)])
        return [PipelineRun.from_dict(record) for record in records]

    def find_idempotent(self, pipeline: str, task: str, key: str) -> TaskRun | None:
        latest: dict[str, Any] | None = None
        with self._lock:
            for run in self._runs.values():
                record = run["tasks"].get(task) if run["pipeline"] == pipeline else None
                if record is None or not _is_execution(record, key):
                    continue
                if latest is None or _finished(record) >= _finished(latest):
                    latest = record
            found = copy.deepcopy(latest)
        return None if found is None else TaskRun.from_dict(found)


def _is_execution(record: dict[str, Any], key: str) -> bool:
    return record["status"] == TaskStatus.SUCCEEDED.value and record["idempotency_key"] == key


def _finished(record: dict[str, Any]) -> str:
    return record["finished_at"] or ""


class SQLiteRunStore(RunStore):
    """Runs kept in a SQLite file, so they outlive the process.

    Every call opens a short-lived connection under one lock, uses parameterised
    statements only, and commits before it returns: a crash loses at most the
    transition that was being written. The file carries a schema version; a file
    written by an unknown version is refused.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PipelineException(f"run store {self._path}: {error}") from error
        with self._session() as connection:
            connection.executescript(_SCHEMA)
            row = connection.execute(_SELECT_VERSION, (_VERSION_KEY,)).fetchone()
            if row is None:
                connection.execute(_INSERT_VERSION, (_VERSION_KEY, _SCHEMA_VERSION))
            elif row[0] != _SCHEMA_VERSION:
                raise PipelineException(
                    f"run store {self._path}: schema version {row[0]} is not supported"
                    f" (expected {_SCHEMA_VERSION})"
                )

    @property
    def path(self) -> Path:
        """The SQLite file."""
        return self._path

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        try:
            with (
                self._lock,
                closing(sqlite3.connect(self._path, timeout=_BUSY_SECONDS)) as connection,
                connection,
            ):
                yield connection
        except sqlite3.Error as error:
            raise PipelineException(f"run store {self._path}: {error}") from error

    def save_run(self, run: PipelineRun) -> None:
        record = run.to_dict()
        with self._session() as connection:
            connection.execute(_UPSERT_RUN, _run_row(record))
            connection.execute(_DELETE_TASKS, (run.run_id,))
            for task in record["tasks"].values():
                connection.execute(_UPSERT_TASK, _task_row(run.run_id, task))

    def save_task(self, run_id: str, task: TaskRun) -> None:
        row = _task_row(run_id, task.to_dict())
        with self._session() as connection:
            if connection.execute(_RUN_EXISTS, (run_id,)).fetchone() is None:
                raise PipelineException(f"unknown run {run_id!r}")
            connection.execute(_UPSERT_TASK, row)

    def get_run(self, run_id: str) -> PipelineRun | None:
        with self._session() as connection:
            row = connection.execute(_SELECT_RUN, (run_id,)).fetchone()
            return None if row is None else _load_run(connection, row)

    def list_runs(self, pipeline: str | None = None, limit: int = 50) -> list[PipelineRun]:
        with self._session() as connection:
            rows = connection.execute(_SELECT_RUNS, (pipeline, pipeline, max(limit, 0))).fetchall()
            return [_load_run(connection, row) for row in rows]

    def find_idempotent(self, pipeline: str, task: str, key: str) -> TaskRun | None:
        with self._session() as connection:
            row = connection.execute(
                _SELECT_IDEMPOTENT, (pipeline, task, key, TaskStatus.SUCCEEDED.value)
            ).fetchone()
        return None if row is None else TaskRun.from_dict(_task_record(row))


def _run_row(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["run_id"],
        record["pipeline"],
        record["status"],
        int(record["dry_run"]),
        json.dumps(record["params"]),
        record["error"],
        record["started_at"],
        record["finished_at"],
    )


def _task_row(run_id: str, record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run_id,
        run_id,
        record["task"],
        record["status"],
        record["level"],
        record["attempts"],
        json.dumps(record["result"]),
        int(record["result_is_repr"]),
        record["error"],
        record["reason"],
        record["idempotency_key"],
        record["started_at"],
        record["finished_at"],
    )


def _task_record(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "task": row[0],
        "status": row[1],
        "level": row[2],
        "attempts": row[3],
        "result": json.loads(row[4]),
        "result_is_repr": bool(row[5]),
        "error": row[6],
        "reason": row[7],
        "idempotency_key": row[8],
        "started_at": row[9],
        "finished_at": row[10],
    }


def _load_run(connection: sqlite3.Connection, row: tuple[Any, ...]) -> PipelineRun:
    tasks = connection.execute(_SELECT_TASKS, (row[0],)).fetchall()
    return PipelineRun.from_dict(
        {
            "run_id": row[0],
            "pipeline": row[1],
            "status": row[2],
            "dry_run": bool(row[3]),
            "params": json.loads(row[4]),
            "error": row[5],
            "started_at": row[6],
            "finished_at": row[7],
            "tasks": {task[0]: _task_record(task) for task in tasks},
        }
    )


_default: dict[str, RunStore] = {"store": MemoryRunStore()}


def default_run_store() -> RunStore:
    """Return the store used when ``run``, ``resume`` and the actions are given none."""
    return _default["store"]


def set_default_run_store(store: RunStore) -> RunStore:
    """Make ``store`` the default one and return the store it replaces."""
    if not isinstance(store, RunStore):
        raise PipelineException(f"not a RunStore: {store!r}")
    previous = _default["store"]
    _default["store"] = store
    return previous
