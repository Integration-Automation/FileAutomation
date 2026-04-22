"""Tests for automation_file.core.sqlite_lock."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from automation_file.core.sqlite_lock import SQLiteLock
from automation_file.exceptions import LockTimeoutException


def test_acquire_release_lifecycle(tmp_path: Path) -> None:
    lock = SQLiteLock(tmp_path / "db.sqlite", "job-1")
    lock.acquire()
    assert lock.is_held is True
    lock.release()
    assert lock.is_held is False


def test_context_manager(tmp_path: Path) -> None:
    db = tmp_path / "ctx.sqlite"
    with SQLiteLock(db, "ctx") as lock:
        assert lock.is_held is True
    # after exit, a second acquirer can claim it
    second = SQLiteLock(db, "ctx", timeout=0.5)
    second.acquire()
    second.release()


def test_two_instances_exclusion(tmp_path: Path) -> None:
    db = tmp_path / "mut.sqlite"
    a = SQLiteLock(db, "shared")
    b = SQLiteLock(db, "shared", timeout=0.1)
    a.acquire()
    try:
        with pytest.raises(LockTimeoutException):
            b.acquire()
    finally:
        a.release()


def test_different_names_are_independent(tmp_path: Path) -> None:
    db = tmp_path / "ind.sqlite"
    a = SQLiteLock(db, "alpha")
    b = SQLiteLock(db, "beta")
    a.acquire()
    b.acquire()
    assert a.is_held and b.is_held
    a.release()
    b.release()


def test_ttl_lets_stale_owner_be_stolen(tmp_path: Path) -> None:
    db = tmp_path / "ttl.sqlite"
    first = SQLiteLock(db, "lease", ttl=0.1)
    first.acquire()
    time.sleep(0.2)  # lease expires without release
    second = SQLiteLock(db, "lease", timeout=0.5, ttl=0.5)
    second.acquire()
    assert second.is_held
    second.release()


def test_release_does_not_affect_other_owner(tmp_path: Path) -> None:
    db = tmp_path / "owner.sqlite"
    a = SQLiteLock(db, "same")
    b = SQLiteLock(db, "same", timeout=0.2)
    a.acquire()
    # b never acquired — release should be a no-op, must not free a's row
    b.release()
    with pytest.raises(LockTimeoutException):
        b.acquire()
    a.release()


def test_refresh_extends_lease(tmp_path: Path) -> None:
    db = tmp_path / "refresh.sqlite"
    holder = SQLiteLock(db, "keep", ttl=0.15)
    holder.acquire()
    try:
        for _ in range(3):
            time.sleep(0.05)
            holder.refresh()
        contender = SQLiteLock(db, "keep", timeout=0.05)
        with pytest.raises(LockTimeoutException):
            contender.acquire()
    finally:
        holder.release()


def test_empty_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SQLiteLock(tmp_path / "x.sqlite", "")


def test_invalid_ttl_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SQLiteLock(tmp_path / "x.sqlite", "n", ttl=0)
