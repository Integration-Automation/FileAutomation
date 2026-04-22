"""Tests for automation_file.core.file_lock."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from automation_file.core.file_lock import FileLock
from automation_file.exceptions import LockTimeoutException


def test_acquire_and_release(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "a.lock")
    lock.acquire()
    assert lock.is_held is True
    lock.release()
    assert lock.is_held is False


def test_context_manager_releases(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "cm.lock")
    with lock:
        assert lock.is_held is True
    assert lock.is_held is False


def test_double_acquire_same_instance_rejected(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "dup.lock")
    with lock, pytest.raises(LockTimeoutException):
        lock.acquire()


def test_release_is_idempotent(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "idem.lock")
    lock.acquire()
    lock.release()
    lock.release()  # should not raise


def test_cross_process_exclusion(tmp_path: Path) -> None:
    lock_path = tmp_path / "xproc.lock"
    script_path = tmp_path / "probe.py"
    repo_root = Path(__file__).resolve().parent.parent
    script_path.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{repo_root}')\n"
        "from automation_file.core.file_lock import FileLock\n"
        "from automation_file.exceptions import LockTimeoutException\n"
        f"lock = FileLock(r'{lock_path}', timeout=0.2)\n"
        "try:\n"
        "    lock.acquire()\n"
        "    print('acquired')\n"
        "except LockTimeoutException:\n"
        "    print('timeout')\n",
        encoding="utf-8",
    )
    outer = FileLock(lock_path)
    outer.acquire()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert "timeout" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    finally:
        outer.release()


def test_timeout_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / "t.lock"
    holder = FileLock(lock_path)
    holder.acquire()
    try:
        waiter = FileLock(lock_path, timeout=0.1)
        start = time.monotonic()
        with pytest.raises(LockTimeoutException):
            waiter.acquire()
        assert time.monotonic() - start >= 0.05
    finally:
        holder.release()


def test_threads_serialize(tmp_path: Path) -> None:
    lock_path = tmp_path / "threads.lock"
    counter = {"value": 0, "max": 0, "concurrent": 0}
    lock_guard = threading.Lock()

    def worker() -> None:
        with FileLock(lock_path, timeout=5.0):
            with lock_guard:
                counter["concurrent"] += 1
                counter["max"] = max(counter["max"], counter["concurrent"])
            time.sleep(0.02)
            with lock_guard:
                counter["concurrent"] -= 1
                counter["value"] += 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter["value"] == 5
    assert counter["max"] == 1
