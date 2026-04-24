"""Tests for the SQLite-backed action audit log."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from automation_file import AuditException, AuditLog


def test_audit_log_creates_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "audit.sqlite"
    log = AuditLog(db_path)
    assert db_path.exists()
    assert log.count() == 0


def test_record_and_recent_roundtrip(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    log.record("FA_copy_file", {"src": "a", "dst": "b"}, result={"ok": True}, duration_ms=12.5)
    rows = log.recent()
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "FA_copy_file"
    assert row["payload"] == {"src": "a", "dst": "b"}
    assert row["result"] == {"ok": True}
    assert row["error"] is None
    assert row["duration_ms"] == pytest.approx(12.5)


def test_record_error_stores_repr(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    err = ValueError("boom")
    log.record("FA_test", {"x": 1}, error=err, duration_ms=0.0)
    row = log.recent()[0]
    assert row["error"] is not None
    assert "ValueError" in row["error"]
    assert "boom" in row["error"]
    assert row["result"] is None


def test_recent_returns_newest_first(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    log.record("first", {"i": 1})
    time.sleep(0.01)
    log.record("second", {"i": 2})
    time.sleep(0.01)
    log.record("third", {"i": 3})
    rows = log.recent()
    assert [r["action"] for r in rows] == ["third", "second", "first"]


def test_recent_respects_limit(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    for index in range(5):
        log.record(f"action-{index}", {"i": index})
    rows = log.recent(limit=2)
    assert len(rows) == 2


def test_recent_zero_limit_returns_empty(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    log.record("x", {})
    assert log.recent(limit=0) == []


def test_count_reflects_inserts(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    assert log.count() == 0
    log.record("a", {})
    log.record("b", {})
    assert log.count() == 2


def test_purge_removes_old_rows(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    log.record("old", {})
    # Backdate the row so it's older than the cutoff.
    import sqlite3

    with sqlite3.connect(log._db_path) as conn:  # pylint: disable=protected-access
        conn.execute("UPDATE audit SET ts = ? WHERE action = 'old'", (time.time() - 3600,))
        conn.commit()
    log.record("fresh", {})
    removed = log.purge(older_than_seconds=60)
    assert removed == 1
    remaining = [row["action"] for row in log.recent()]
    assert remaining == ["fresh"]


def test_purge_rejects_non_positive(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")
    with pytest.raises(AuditException):
        log.purge(0)


def test_record_non_serialisable_payload_falls_back_to_repr(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.sqlite")

    class Custom:
        def __repr__(self) -> str:
            return "<custom>"

    log.record("weird", {"obj": Custom()}, result={"marker": object()})
    row = log.recent()[0]
    assert row["action"] == "weird"
    assert "<custom>" in str(row["payload"])
    assert row["result"] is not None


def test_cannot_open_audit_log_in_missing_root(tmp_path: Path) -> None:
    # Point at a path whose parent cannot be created (a file, not a dir).
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(AuditException):
        AuditLog(blocker / "child" / "audit.sqlite")
