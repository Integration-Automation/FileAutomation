"""Audit schema v2: the record, the stores, the trail, the v1 import and the actions."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=too-many-function-args  # the call is expected to be refused
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import dataclasses
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from automation_file.audit import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SCHEMA_VERSION,
    AuditException,
    AuditQuery,
    AuditRecord,
    AuditStore,
    AuditTrail,
    MemoryAuditStore,
    SQLiteAuditStore,
    audit_search,
    audit_trail,
    configure_audit,
    record_from_event,
    record_from_operation,
    register_audit_ops,
)
from automation_file.core.action_executor import ActionExecutor
from automation_file.core.action_registry import ActionRegistry
from automation_file.core.audit import AuditLog
from automation_file.events import (
    Event,
    EventBus,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    Severity,
    StorageError,
    StorageErrorBridge,
    TaskCompleted,
    TaskFailed,
    TaskStarted,
    actor_scope,
    correlation_scope,
    current_actor,
    event_bus,
)
from automation_file.exceptions import StorageNotFoundException, StoragePermissionException
from automation_file.storage import MemoryStorage, observe
from automation_file.storage.observe import StorageOperation

_T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
_FIELDS = (
    "id timestamp actor source pipeline task action resource backend status duration_ms error "
    "metadata correlation_id"
)
#: The text fields of a record, and the filters that find a record by one of them.
_TEXT_FIELDS = "action source actor resource backend status pipeline task error correlation_id"
_TEXT_FILTERS = (
    "actor source pipeline task action backend status correlation_id resource_prefix text"
)
_RUN_1 = {"correlation_id": "run-1", "actor": "scheduler"}


def _at(minutes: float) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _record(minutes: float = 0.0, **fields: Any) -> AuditRecord:
    fields.setdefault("action", "upload")
    fields.setdefault("source", "storage")
    fields.setdefault("actor", "ops")
    return AuditRecord(timestamp=_at(minutes), **fields)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[AuditStore]:
    built: AuditStore
    if request.param == "memory":
        built = MemoryAuditStore()
    else:
        built = SQLiteAuditStore(tmp_path / "audit.sqlite")
    yield built
    built.close()


@pytest.fixture
def sqlite_store(tmp_path: Path) -> Iterator[SQLiteAuditStore]:
    built = SQLiteAuditStore(tmp_path / "audit.sqlite")
    yield built
    built.close()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def trail(bus: EventBus) -> Iterator[AuditTrail]:
    built = AuditTrail(MemoryAuditStore(), bus=bus)
    built.start()
    yield built
    built.close()


def _stored(trail: AuditTrail) -> list[AuditRecord]:
    """Return what the trail recorded, oldest first."""
    return list(reversed(trail.search(limit=MAX_LIMIT)))


# ---------------------------------------------------------------------- the record


def test_a_record_fills_in_its_identity() -> None:
    first, second = AuditRecord(action="upload"), AuditRecord(action="upload")
    assert first.id != second.id
    assert len(first.id) == 32
    assert first.timestamp.utcoffset() == timedelta(0)
    assert first.actor == current_actor()
    assert first.correlation_id is None
    assert first.status == "ok"
    assert dict(first.metadata) == {}
    with actor_scope("scheduler"), correlation_scope("run-1"):
        scoped = AuditRecord(action="upload")
    assert (scoped.actor, scoped.correlation_id) == ("scheduler", "run-1")


def test_a_record_is_frozen_and_keyword_only() -> None:
    record = _record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.status = "error"
    with pytest.raises(TypeError):
        AuditRecord("upload")
    assert isinstance(hash(record), int)


def test_a_record_turns_into_json_and_back() -> None:
    record = AuditRecord(
        action="upload",
        source="storage",
        resource="s3://reports/q1.csv",
        backend="s3",
        status="error",
        pipeline="daily",
        task="load",
        duration_ms=12.5,
        error="StoragePermissionException: denied",
        metadata={"attempt": 2, "tags": ("a", "b")},
        actor="ops",
        correlation_id="run-1",
        timestamp=_at(0),
    )
    document = json.loads(json.dumps(record.to_dict()))
    assert list(document) == _FIELDS.split()
    assert document["timestamp"] == "2026-10-01T12:00:00+00:00"
    assert document["metadata"] == {"attempt": 2, "tags": ["a", "b"]}
    assert AuditRecord.from_dict(document) == record


def test_a_timestamp_is_always_aware_utc() -> None:
    taipei = timezone(timedelta(hours=8))
    record = AuditRecord(action="x", timestamp=datetime(2026, 10, 1, 20, 0, tzinfo=taipei))
    assert record.timestamp == _at(0)
    assert record.timestamp.utcoffset() == timedelta(0)
    assert AuditRecord(action="x", timestamp="2026-10-01T12:00:00Z").timestamp == _at(0)
    with pytest.raises(AuditException, match="time zone"):
        AuditRecord(action="x", timestamp=datetime(2026, 10, 1, 12, 0))
    with pytest.raises(AuditException):
        AuditRecord(action="x", timestamp="yesterday")


def test_metadata_that_json_cannot_hold_is_kept_as_text() -> None:
    record = AuditRecord(action="x", metadata={"when": _at(0), "path": Path("a/b"), 7: "seven"})
    assert record.metadata["when"] == repr(_at(0))
    assert record.metadata["7"] == "seven"
    json.dumps(record.to_dict())


@pytest.mark.parametrize(
    "fields",
    [
        {"action": 5},
        {"status": None},
        {"resource": 5},
        {"id": ""},
        {"metadata": ["not", "a", "mapping"]},
        {"duration_ms": "fast"},
        {"duration_ms": True},
    ],
)
def test_a_record_rejects_fields_of_the_wrong_kind(fields: dict) -> None:
    with pytest.raises(AuditException):
        AuditRecord(**fields)


def test_from_dict_rejects_what_is_not_a_record() -> None:
    with pytest.raises(AuditException, match="colour"):
        AuditRecord.from_dict({"action": "x", "colour": "red"})
    with pytest.raises(AuditException):
        AuditRecord.from_dict(["action"])


# ---------------------------------------------------------------------- the store contract


def test_a_store_returns_what_it_was_given(store: AuditStore) -> None:
    record = _record(
        resource="s3://reports/q1.csv",
        backend="s3",
        status="error",
        pipeline="daily",
        task="load",
        duration_ms=0.125,
        error="X: y",
        metadata={"attempt": 2, "nested": {"名稱": "報表"}},
        correlation_id="run-1",
    )
    store.append(record)
    assert store.search() == [record]
    assert store.count() == 1


def test_search_is_newest_first(store: AuditStore) -> None:
    records = [_record(minutes, action=f"a{minutes}") for minutes in (2, 0, 3, 1)]
    for record in records:
        store.append(record)
    assert [record.action for record in store.search()] == ["a3", "a2", "a1", "a0"]


def test_equal_timestamps_keep_the_later_append_first(store: AuditStore) -> None:
    for name in ("first", "second", "third"):
        store.append(_record(action=name))
    assert [record.action for record in store.search()] == ["third", "second", "first"]


def _populate(store: AuditStore) -> None:
    """Store five records, one per minute; ``_record`` makes each an upload by ops unless told.

    Minutes 0 to 2 belong to run-1 of the scheduler: the start of the daily pipeline, an upload
    to the reports bucket, and an upload to the archive bucket that was denied. Minute 3 is a
    local delete of run-2, minute 4 the failed load task of the weekly pipeline (run-3).
    """
    denied = {"status": "error", "error": "StoragePermissionException: Access Denied"}
    timeout = {"status": "error", "error": "TimeoutError: no answer"}
    cleanup = {"correlation_id": "run-2", "metadata": {"reason": "Cleanup after publish"}}
    weekly = {"source": "pipeline", "pipeline": "weekly", "task": "load", "correlation_id": "run-3"}
    reports, archive = "s3://reports/2026/q1.csv", "s3://archive/2026/q1.csv"
    rows: list[dict[str, Any]] = [
        {"action": "pipeline.started", "source": "pipeline", "pipeline": "daily", **_RUN_1},
        {"resource": reports, "backend": "s3", "pipeline": "daily", "task": "publish", **_RUN_1},
        {"resource": archive, "backend": "s3", **denied, **_RUN_1},
        {"action": "delete", "resource": "local:///tmp/q1.csv", "backend": "local", **cleanup},
        {"action": "task.failed", **weekly, **timeout},
    ]
    for minutes, fields in enumerate(rows):
        store.append(_record(minutes, **fields))


@pytest.mark.parametrize(
    "filters,minutes",
    [
        ({}, [4, 3, 2, 1, 0]),
        ({"since": _at(2)}, [4, 3, 2]),
        ({"until": _at(2)}, [1, 0]),
        ({"since": _at(1), "until": _at(4)}, [3, 2, 1]),
        ({"since": "2026-10-01T12:03:00+00:00"}, [4, 3]),
        ({"since": "2026-10-01T20:03:00+08:00"}, [4, 3]),
        ({"until": _at(1).timestamp()}, [0]),
        ({"actor": "scheduler"}, [2, 1, 0]),
        ({"actor": "ops"}, [4, 3]),
        ({"source": "pipeline"}, [4, 0]),
        ({"pipeline": "daily"}, [1, 0]),
        ({"task": "load"}, [4]),
        ({"action": "upload"}, [2, 1]),
        ({"resource_prefix": "s3://reports/"}, [1]),
        ({"resource_prefix": "s3://"}, [2, 1]),
        ({"resource_prefix": "S3://REPORTS"}, [1]),
        ({"backend": "local"}, [3]),
        ({"status": "error"}, [4, 2]),
        ({"correlation_id": "run-1"}, [2, 1, 0]),
        ({"text": "denied"}, [2]),
        ({"text": "q1.csv"}, [3, 2, 1]),
        ({"text": "cleanup after"}, [3]),
        ({"text": "weekly"}, [4]),
        ({"text": "scheduler"}, [2, 1, 0]),
        ({"limit": 2}, [4, 3]),
        ({"limit": 2, "offset": 2}, [2, 1]),
        ({"offset": 4}, [0]),
        ({"limit": 0}, []),
        ({"status": "error", "backend": "s3", "correlation_id": "run-1"}, [2]),
        ({"action": "upload", "status": "ok", "text": "reports", "since": _at(1)}, [1]),
        ({"actor": None, "status": None, "limit": None}, [4, 3, 2, 1, 0]),
        ({"pipeline": "monthly"}, []),
    ],
)
def test_every_filter(store: AuditStore, filters: dict[str, Any], minutes: list[int]) -> None:
    _populate(store)
    found = store.search(**filters)
    assert [record.timestamp for record in found] == [_at(minute) for minute in minutes]
    unpaged = {key: value for key, value in filters.items() if key not in ("limit", "offset")}
    assert store.count(**filters) == len(store.search(**unpaged))


def test_count_ignores_the_paging(store: AuditStore) -> None:
    _populate(store)
    assert store.count(limit=1, offset=3) == 5
    assert store.count(status="error", limit=1) == 2


@pytest.mark.parametrize(
    "filters",
    [
        {"colour": "red"},
        {"resource": "s3://reports/q1.csv"},
        {"limit": -1},
        {"limit": MAX_LIMIT + 1},
        {"limit": "ten"},
        {"limit": True},
        {"offset": -1},
        {"offset": 1.5},
        {"actor": 5},
        {"text": ["a"]},
        {"since": "last week"},
        {"since": datetime(2026, 10, 1, 12, 0)},
        {"until": "2026-10-01T12:00:00"},
        {"since": True},
    ],
)
def test_a_bad_filter_is_an_error_not_an_empty_answer(
    store: AuditStore, filters: dict[str, Any]
) -> None:
    _populate(store)
    with pytest.raises(AuditException):
        store.search(**filters)
    with pytest.raises(AuditException):
        store.count(**filters)


def test_the_default_limit(store: AuditStore) -> None:
    for index in range(DEFAULT_LIMIT + 5):
        store.append(_record(index))
    assert len(store.search()) == DEFAULT_LIMIT
    assert len(store.search(limit=DEFAULT_LIMIT + 5)) == DEFAULT_LIMIT + 5
    assert AuditQuery.from_filters({}).limit == DEFAULT_LIMIT


_INJECTIONS = [
    "x' OR '1'='1",
    "x'; DROP TABLE audit_records; --",
    'x" OR ""="',
    "x') UNION SELECT * FROM audit_schema_version --",
    "1; DELETE FROM audit_records",
    "\\' OR 1=1 --",
]


@pytest.mark.parametrize("attack", _INJECTIONS)
def test_sql_in_a_filter_is_literal_text(store: AuditStore, attack: str) -> None:
    _populate(store)
    for name in ("actor", "source", "pipeline", "task", "action", "backend", "status", "text"):
        assert store.search(**{name: attack}) == []
        assert store.count(**{name: attack}) == 0
    assert store.search(correlation_id=attack) == []
    assert store.search(resource_prefix=attack) == []
    assert store.count() == 5


@pytest.mark.parametrize("attack", _INJECTIONS)
def test_sql_in_a_record_is_stored_and_found_as_text(store: AuditStore, attack: str) -> None:
    _populate(store)
    everywhere = dict.fromkeys(_TEXT_FIELDS.split(), attack)
    record = _record(10, metadata={"note": attack}, **everywhere)
    store.append(record)
    assert store.count() == 6
    for name in _TEXT_FILTERS.split():
        assert store.search(**{name: attack}) == [record]


def test_like_wildcards_in_a_filter_are_literal(store: AuditStore) -> None:
    percent = _record(0, resource="local:///data/100%_done.txt", error="50% of the files")
    letter = _record(1, resource="local:///data/100x_done.txt", error="500 of the files")
    under = _record(2, resource="local:///data/100xxdone.txt", error="a_b")
    slash = _record(3, resource="local:///data/C:\\temp\\x.txt", error="axb")
    for record in (percent, letter, under, slash):
        store.append(record)
    assert store.search(resource_prefix="local:///data/100%") == [percent]
    assert store.search(resource_prefix="local:///data/100%_") == [percent]
    assert store.search(resource_prefix="local:///data/100x_") == [letter]
    assert store.search(resource_prefix="%") == []
    assert store.search(resource_prefix="_") == []
    assert store.search(text="50%") == [percent]
    assert store.search(text="0% of") == [percent]
    assert store.search(text="a_b") == [under]
    assert store.search(text="%") == [percent]
    assert store.search(text="C:\\temp\\") == [slash]
    assert store.search(resource_prefix="local:///data/C:\\") == [slash]
    assert store.count(text="\\") == 1


def test_text_search_ignores_ascii_case_only(store: AuditStore) -> None:
    store.append(_record(0, error="Access DENIED for Ärger"))
    assert store.count(text="access denied") == 1
    assert store.count(text="Ärger") == 1
    assert store.count(text="ärger") == 0


def test_text_search_looks_into_the_metadata(store: AuditStore) -> None:
    store.append(_record(0, metadata={"job": "nightly-報表", "attempt": 3}))
    assert store.count(text="nightly-報表") == 1
    assert store.count(text='"attempt": 3') == 1
    assert store.count(text="weekly") == 0


def test_an_id_is_stored_once(store: AuditStore) -> None:
    record = _record()
    store.append(record)
    with pytest.raises(AuditException, match="already stored"):
        store.append(record)
    with pytest.raises(AuditException):
        store.append({"action": "not a record"})
    assert store.count() == 1


def test_purge_removes_what_is_older(store: AuditStore) -> None:
    now = datetime.now(timezone.utc)
    old = AuditRecord(action="old", timestamp=now - timedelta(days=2))
    recent = AuditRecord(action="recent", timestamp=now - timedelta(minutes=1))
    store.append(old)
    store.append(recent)
    assert store.purge(older_than_seconds=3600) == 1
    assert store.search() == [recent]
    assert store.purge(older_than_seconds=3600) == 0
    for bad in (0, -5, "soon", True, float("nan")):
        with pytest.raises(AuditException):
            store.purge(bad)
    store.append(old)
    assert store.count() == 2


def test_a_closed_store_refuses_work(store: AuditStore) -> None:
    store.append(_record())
    store.close()
    store.close()
    with pytest.raises(AuditException):
        store.append(_record(1))
    with pytest.raises(AuditException):
        store.search()
    with pytest.raises(AuditException):
        store.count()
    with pytest.raises(AuditException):
        store.purge(60)


def test_a_store_is_a_context_manager(tmp_path: Path) -> None:
    with SQLiteAuditStore(tmp_path / "audit.sqlite") as opened:
        opened.append(_record())
    with pytest.raises(AuditException):
        opened.count()


# ---------------------------------------------------------------------- the SQLite store


def _names(path: Path, kind: str) -> set[str]:
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,)).fetchall()
    return {row[0] for row in rows}


def test_the_database_states_its_schema_version(sqlite_store: SQLiteAuditStore) -> None:
    assert SCHEMA_VERSION == 2
    assert sqlite_store.schema_version == 2
    assert {"audit_records", "audit_schema_version"} <= _names(sqlite_store.path, "table")
    with closing(sqlite3.connect(sqlite_store.path)) as conn:
        assert conn.execute("SELECT version FROM audit_schema_version").fetchall() == [(2,)]


def test_the_database_has_its_indexes(sqlite_store: SQLiteAuditStore) -> None:
    with closing(sqlite3.connect(sqlite_store.path)) as conn:
        indexed = {
            conn.execute(f"PRAGMA index_info({name})").fetchall()[0][2]  # nosec B608  # nosemgrep  # the name comes from sqlite_master
            for name in _names(sqlite_store.path, "index")
            if name.startswith("idx_audit_records_")
        }
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM audit_records WHERE correlation_id = ?", ("run",)
        ).fetchall()
    assert indexed == {"ts_us", "correlation_id", "resource", "action"}
    assert "idx_audit_records_correlation" in plan[0][3]


def test_the_database_outlives_the_store(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "audit.sqlite"
    record = _record(metadata={"kept": True}, correlation_id="run-1")
    with SQLiteAuditStore(path) as first:
        first.append(record)
    with SQLiteAuditStore(path) as second:
        assert second.search() == [record]
        assert second.schema_version == 2
        with closing(sqlite3.connect(path)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM audit_schema_version").fetchone() == (1,)


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "audit.sqlite"
    SQLiteAuditStore(path).close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE audit_schema_version SET version = 99")
        conn.commit()
    with pytest.raises(AuditException, match="schema version 99"):
        SQLiteAuditStore(path)


def test_a_path_that_cannot_be_a_database_is_refused(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(AuditException):
        SQLiteAuditStore(blocker / "child" / "audit.sqlite")
    garbage = tmp_path / "garbage.sqlite"
    garbage.write_bytes(b"this is not a sqlite database, not even close" * 40)
    with pytest.raises(AuditException):
        SQLiteAuditStore(garbage)


def test_many_threads_share_one_store(sqlite_store: SQLiteAuditStore) -> None:
    threads, per_thread = 8, 40
    failures: list[Exception] = []
    barrier = threading.Barrier(threads)

    def work(worker: int) -> None:
        try:
            barrier.wait(timeout=10)
            for index in range(per_thread):
                sqlite_store.append(
                    _record(index, action=f"w{worker}", correlation_id=f"run-{worker}")
                )
                if index % 10 == 0:
                    sqlite_store.search(correlation_id=f"run-{worker}", limit=5)
                    sqlite_store.count(action=f"w{worker}")
        except Exception as error:  # pylint: disable=broad-except  # asserted on below
            failures.append(error)

    workers = [threading.Thread(target=work, args=(number,)) for number in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    assert failures == []
    assert sqlite_store.count() == threads * per_thread
    for number in range(threads):
        assert sqlite_store.count(correlation_id=f"run-{number}") == per_thread
    ids = {record.id for record in sqlite_store.search(limit=MAX_LIMIT)}
    assert len(ids) == threads * per_thread


def test_two_stores_can_share_one_database(tmp_path: Path) -> None:
    path = tmp_path / "audit.sqlite"
    with SQLiteAuditStore(path) as writer, SQLiteAuditStore(path) as reader:
        writer.append(_record(0, action="one"))
        assert reader.count() == 1
        reader.append(_record(1, action="two"))
        assert [record.action for record in writer.search()] == ["two", "one"]


# ---------------------------------------------------------------------- v1 import


def test_import_v1_copies_the_rows_of_an_audit_log(
    sqlite_store: SQLiteAuditStore, tmp_path: Path
) -> None:
    v1_path = tmp_path / "v1.sqlite"
    log = AuditLog(v1_path)
    log.record("FA_copy_file", {"src": "a", "dst": "b"}, result={"ok": True}, duration_ms=12.5)
    log.record("FA_delete", {"path": "x' OR '1'='1"}, error=ValueError("boom"), duration_ms=1.0)
    v1_times = {row["action"]: row["ts"] for row in log.recent()}
    assert sqlite_store.import_v1(v1_path) == 2
    failed, copied = sqlite_store.search(source="audit.v1")
    assert copied.action == "FA_copy_file"
    assert copied.status == "ok"
    assert copied.error is None
    assert copied.duration_ms == pytest.approx(12.5)
    assert copied.metadata["payload"] == {"src": "a", "dst": "b"}
    assert copied.metadata["result"] == {"ok": True}
    assert copied.correlation_id is None
    assert copied.actor == "unknown"
    assert abs(copied.timestamp.timestamp() - v1_times["FA_copy_file"]) < 0.001
    assert failed.action == "FA_delete"
    assert failed.status == "error"
    assert failed.error is not None
    assert "boom" in failed.error
    assert failed.metadata["payload"] == {"path": "x' OR '1'='1"}
    assert failed.metadata["result"] is None


def test_import_v1_twice_adds_nothing(sqlite_store: SQLiteAuditStore, tmp_path: Path) -> None:
    v1_path = tmp_path / "v1.sqlite"
    log = AuditLog(v1_path)
    log.record("first", {})
    assert sqlite_store.import_v1(v1_path) == 1
    assert sqlite_store.import_v1(v1_path) == 0
    log.record("second", {})
    assert sqlite_store.import_v1(v1_path) == 1
    assert sqlite_store.count(source="audit.v1") == 2
    assert log.count() == 2


def test_import_v1_refuses_what_is_not_a_v1_log(
    sqlite_store: SQLiteAuditStore, tmp_path: Path
) -> None:
    with pytest.raises(AuditException, match="not found"):
        sqlite_store.import_v1(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()
    with pytest.raises(AuditException, match="cannot import"):
        sqlite_store.import_v1(empty)
    assert sqlite_store.count() == 0


# ---------------------------------------------------------------------- event and operation records


def test_an_event_becomes_a_record() -> None:
    target = {"pipeline": "daily", "task": "load", "resource": "s3://reports/q1.csv"}
    outcome = {"backend": "s3", "status": "failed", "error": "TimeoutError: no answer"}
    rest = {"run_id": "run-7", "attempt": 2, "action": "FA_storage_copy"}
    payload = {**target, **outcome, **rest, "duration_ms": 1500}
    with actor_scope("scheduler"), correlation_scope("run-7"):
        event = TaskFailed(source="pipeline", subject="load failed", payload=payload)
    record = record_from_event(event)
    assert (record.id, record.timestamp) == (event.id, event.timestamp)
    assert (record.actor, record.correlation_id) == ("scheduler", "run-7")
    assert (record.source, record.action) == ("pipeline", "task.failed")
    for name, value in {**target, **outcome}.items():
        assert getattr(record, name) == value
    assert record.duration_ms == pytest.approx(1500.0)
    assert isinstance(record.duration_ms, float)
    assert record.metadata == {**rest, "subject": "load failed", "severity": "error"}


@pytest.mark.parametrize(
    "severity,status",
    [
        (Severity.INFO, "ok"),
        (Severity.WARNING, "warning"),
        (Severity.ERROR, "error"),
        (Severity.CRITICAL, "error"),
    ],
)
def test_an_event_without_a_status_takes_it_from_its_severity(
    severity: Severity, status: str
) -> None:
    record = record_from_event(Event(source="system", severity=severity))
    assert record.status == status
    assert record.action == "event"
    assert record.pipeline is None
    assert record.duration_ms is None


def test_a_duration_that_is_not_a_number_stays_in_the_metadata() -> None:
    record = record_from_event(PipelineCompleted(payload={"duration_ms": "fast", "task": 7}))
    assert record.duration_ms is None
    assert record.metadata["duration_ms"] == "fast"
    assert record.task == "7"


def test_a_storage_operation_becomes_a_record() -> None:
    operation = StorageOperation(
        operation="copy",
        uri="local:///backup/q1.csv",
        backend="local",
        status="error",
        duration_ms=3.5,
        source_uri="s3://reports/q1.csv",
        error="StoragePermissionException: denied",
        error_type="StoragePermissionException",
    )
    with actor_scope("mcp"), correlation_scope("run-3"):
        record = record_from_operation(operation)
    assert record.source == "storage"
    assert record.action == "copy"
    assert record.resource == "local:///backup/q1.csv"
    assert record.backend == "local"
    assert record.status == "error"
    assert record.duration_ms == pytest.approx(3.5)
    assert record.error == "StoragePermissionException: denied"
    assert record.metadata == {
        "source_uri": "s3://reports/q1.csv",
        "error_type": "StoragePermissionException",
    }
    assert (record.actor, record.correlation_id) == ("mcp", "run-3")


# ---------------------------------------------------------------------- the trail


@pytest.fixture(params=["bridge first", "trail first"])
def bridged(request: pytest.FixtureRequest, bus: EventBus) -> Iterator[None]:
    """Publish failed storage operations on the private bus, as the process-wide bridge does.

    The bridge listens before the trail in one run and after it in the other: which of the
    two hears about a failed operation first must not matter.
    """
    bridge = StorageErrorBridge(bus)
    if request.param == "trail first":
        request.getfixturevalue("trail")
    observe.add_listener(bridge)
    yield
    observe.remove_listener(bridge)


def _deny(*_args: object) -> None:
    raise StoragePermissionException("memory://audit/out/report.csv: denied")


@pytest.mark.usefixtures("bridged")
def test_a_pipeline_run_is_recorded_once_under_one_correlation_id(
    trail: AuditTrail, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = MemoryStorage("audit")
    published: list[Event] = []
    bus.subscribe(published.append)
    with actor_scope("scheduler"), correlation_scope() as run_id:
        bus.publish(PipelineStarted(source="pipeline", payload={"pipeline": "daily"}))
        bus.publish(
            TaskStarted(source="pipeline", payload={"pipeline": "daily", "task": "extract"})
        )
        storage.write_bytes("in/raw.csv", b"a,b\n")
        storage.read_bytes("in/raw.csv")
        bus.publish(
            TaskCompleted(
                source="pipeline",
                payload={"pipeline": "daily", "task": "extract", "duration_ms": 4.0},
            )
        )
        bus.publish(TaskStarted(source="pipeline", payload={"pipeline": "daily", "task": "load"}))
        monkeypatch.setattr(storage, "_upload", _deny)
        with pytest.raises(StoragePermissionException):
            storage.write_bytes("out/report.csv", b"x")
        bus.publish(
            TaskFailed(
                source="pipeline",
                payload={
                    "pipeline": "daily",
                    "task": "load",
                    "error": "StoragePermissionException: denied",
                },
            )
        )
        bus.publish(PipelineFailed(source="pipeline", payload={"pipeline": "daily"}))
    records = _stored(trail)
    assert [(record.source, record.action, record.status) for record in records] == [
        ("pipeline", "pipeline.started", "ok"),
        ("pipeline", "task.started", "ok"),
        ("storage", "upload", "ok"),
        ("storage", "read", "ok"),
        ("pipeline", "task.completed", "ok"),
        ("pipeline", "task.started", "ok"),
        ("storage", "upload", "error"),
        ("pipeline", "task.failed", "error"),
        ("pipeline", "pipeline.failed", "error"),
    ]
    assert {record.correlation_id for record in records} == {run_id}
    assert {record.actor for record in records} == {"scheduler"}
    assert [event.type for event in published].count("storage.error") == 1
    assert trail.count(action="storage.error") == 0
    failed = trail.search(resource_prefix="memory://audit/out/")
    assert len(failed) == 1
    assert failed[0].backend == "memory"
    assert failed[0].error is not None
    assert failed[0].error.startswith("StoragePermissionException: ")
    assert failed[0].metadata["error_type"] == "StoragePermissionException"
    assert trail.count(pipeline="daily", task="load") == 2
    assert trail.count(correlation_id=run_id) == len(records) == 9


@pytest.mark.usefixtures("bridged")
def test_a_caller_mistake_in_storage_is_recorded_once(trail: AuditTrail) -> None:
    storage = MemoryStorage("audit")
    with pytest.raises(StorageNotFoundException):
        storage.read_bytes("nope.txt")
    records = _stored(trail)
    assert [(record.action, record.status) for record in records] == [("read", "error")]
    assert records[0].correlation_id is None


def test_a_storage_error_from_elsewhere_is_recorded(trail: AuditTrail, bus: EventBus) -> None:
    bus.publish(StorageError(source="replication", subject="replica is behind"))
    assert [(record.source, record.action) for record in _stored(trail)] == [
        ("replication", "storage.error")
    ]


def test_a_copy_between_backends_is_one_record(trail: AuditTrail) -> None:
    source = MemoryStorage("audit-source")
    target = MemoryStorage("audit-target")
    source.write_bytes("a.txt", b"x")
    target.copy_from(source, "a.txt", "copy.txt")
    records = _stored(trail)
    assert [record.action for record in records] == ["upload", "copy"]
    assert records[1].resource == "memory://audit-target/copy.txt"
    assert records[1].metadata == {"source_uri": "memory://audit-source/a.txt"}


def test_the_trail_listens_only_between_start_and_stop(bus: EventBus) -> None:
    store = MemoryAuditStore()
    trail = AuditTrail(store, bus=bus)
    storage = MemoryStorage("audit")
    assert trail.active is False
    bus.publish(PipelineStarted())
    storage.write_bytes("before.txt", b"x")
    trail.start()
    trail.start()
    assert trail.active is True
    bus.publish(PipelineStarted())
    storage.write_bytes("during.txt", b"x")
    trail.stop()
    trail.stop()
    assert trail.active is False
    bus.publish(PipelineStarted())
    storage.write_bytes("after.txt", b"x")
    assert [record.action for record in store.search()] == ["upload", "pipeline.started"]
    assert store.search()[0].resource == "memory://audit/during.txt"


def test_a_trail_without_a_store_cannot_start(bus: EventBus) -> None:
    trail = AuditTrail(bus=bus)
    assert trail.store is None
    with pytest.raises(AuditException, match="no store"):
        trail.start()
    assert trail.record("manual") is None
    with pytest.raises(AuditException, match="not configured"):
        trail.search()
    with pytest.raises(AuditException):
        trail.attach("audit.sqlite")


def test_record_appends_one_by_hand(trail: AuditTrail) -> None:
    with actor_scope("alice"), correlation_scope("run-5"):
        written = trail.record(
            "approve",
            resource="s3://reports/q1.csv",
            backend="s3",
            source="review",
            metadata={"ticket": "OPS-12"},
        )
    assert written is not None
    assert trail.search() == [written]
    assert (written.actor, written.correlation_id) == ("alice", "run-5")
    assert (written.action, written.source, written.status) == ("approve", "review", "ok")
    outside = trail.record("approve", actor="bob", correlation_id="run-6")
    assert outside is not None
    assert (outside.actor, outside.correlation_id) == ("bob", "run-6")
    with pytest.raises(AuditException, match="colour"):
        trail.record("approve", colour="red")
    assert trail.count() == 2


class _FailingStore(MemoryAuditStore):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def append(self, record: AuditRecord) -> None:
        self.attempts += 1
        raise OSError("the audit disk is gone")


def test_a_store_that_cannot_write_does_not_break_what_is_audited(bus: EventBus) -> None:
    store = _FailingStore()
    trail = AuditTrail(store, bus=bus)
    received: list[Event] = []
    bus.subscribe(received.append)
    trail.start()
    try:
        assert bus.publish(PipelineStarted()) == 2
        storage = MemoryStorage("audit")
        info = storage.write_bytes("a.txt", b"hello")
        assert info.size == 5
        assert storage.read_bytes("a.txt") == b"hello"
        assert trail.record("manual") is None
    finally:
        trail.close()
    assert len(received) == 1
    assert store.attempts == 4
    assert store.search() == []


def test_a_record_that_cannot_be_built_is_dropped(trail: AuditTrail, bus: EventBus) -> None:
    assert bus.publish(PipelineStarted(subject="not a mapping", payload=5)) == 1
    bus.publish(PipelineStarted())
    assert [record.action for record in _stored(trail)] == ["pipeline.started"]


def test_close_closes_only_a_store_the_trail_owns(tmp_path: Path, bus: EventBus) -> None:
    mine = MemoryAuditStore()
    trail = AuditTrail(mine, bus=bus)
    trail.close()
    assert trail.store is None
    mine.append(_record())
    owned = SQLiteAuditStore(tmp_path / "owned.sqlite")
    trail.attach(owned, owned=True)
    trail.attach(mine)
    with pytest.raises(AuditException):
        owned.count()
    assert mine.count() == 1


# ---------------------------------------------------------------------- the process-wide trail


@pytest.fixture
def process_wide() -> Iterator[None]:
    """The process-wide audit trail, left without a store as it started."""
    assert audit_trail.store is None
    yield
    audit_trail.close()


def test_the_process_wide_trail_is_inactive_until_configured() -> None:
    assert audit_trail.active is False
    assert audit_trail.store is None
    assert audit_trail.bus is event_bus
    with pytest.raises(AuditException, match="not configured"):
        audit_search()


@pytest.mark.usefixtures("process_wide")
def test_configure_audit_with_a_path(tmp_path: Path) -> None:
    path = tmp_path / "audit.sqlite"
    assert configure_audit(path) is audit_trail
    assert audit_trail.active is True
    assert isinstance(audit_trail.store, SQLiteAuditStore)
    with correlation_scope("configured-run"):
        event_bus.publish(PipelineStarted(source="pipeline", subject="configured"))
        MemoryStorage("audit-configured").write_bytes("a.txt", b"x")
    found = audit_search(correlation_id="configured-run")
    assert [entry["action"] for entry in found] == ["upload", "pipeline.started"]
    assert found[1]["metadata"]["subject"] == "configured"
    json.dumps(found)
    first = audit_trail.store
    configure_audit(tmp_path / "second.sqlite")
    with pytest.raises(AuditException):
        first.count()
    assert audit_search(correlation_id="configured-run") == []


@pytest.mark.usefixtures("process_wide")
def test_configure_audit_with_a_store() -> None:
    store = MemoryAuditStore()
    configure_audit(store)
    assert audit_trail.store is store
    event_bus.publish(PipelineStarted(source="pipeline", subject="into my store"))
    audit_trail.close()
    assert store.count(text="into my store") == 1
    assert audit_trail.active is False


@pytest.mark.usefixtures("process_wide")
def test_the_audit_actions(tmp_path: Path) -> None:
    registry = ActionRegistry()
    register_audit_ops(registry)
    for name in ("FA_audit_configure", "FA_audit_search", "FA_audit_count", "FA_audit_purge"):
        assert name in registry
    executor = ActionExecutor(registry)
    path = tmp_path / "actions.sqlite"
    (configured,) = executor.execute_action(
        [["FA_audit_configure", {"db_path": str(path)}]]
    ).values()
    assert configured == {"active": True, "db_path": str(path), "schema_version": 2}
    with correlation_scope("action-run"):
        event_bus.publish(TaskFailed(source="pipeline", subject="load failed"))
        event_bus.publish(PipelineStarted(source="pipeline", subject="started"))
    found, counted, purged, bad = executor.execute_action(
        [
            ["FA_audit_search", {"correlation_id": "action-run", "status": "error"}],
            ["FA_audit_count", {"correlation_id": "action-run"}],
            ["FA_audit_purge", {"older_than_seconds": 3600}],
            ["FA_audit_search", {"colour": "red"}],
        ]
    ).values()
    assert [entry["action"] for entry in found] == ["task.failed"]
    assert counted == 2
    assert purged == 0
    assert "unknown audit filter" in bad
