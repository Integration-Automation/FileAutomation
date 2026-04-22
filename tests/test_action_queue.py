"""Tests for automation_file.core.action_queue."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from automation_file.core.action_queue import ActionQueue
from automation_file.exceptions import QueueException


def test_enqueue_dequeue_roundtrip(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "q.sqlite")
    q.enqueue(["noop"])
    item = q.dequeue()
    assert item is not None
    assert item.action == ["noop"]
    assert item.attempts == 1


def test_priority_ordering(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "p.sqlite")
    q.enqueue(["low"], priority=0)
    q.enqueue(["high"], priority=10)
    q.enqueue(["mid"], priority=5)
    assert (q.dequeue() or pytest.fail("empty")).action == ["high"]
    assert (q.dequeue() or pytest.fail("empty")).action == ["mid"]
    assert (q.dequeue() or pytest.fail("empty")).action == ["low"]


def test_run_at_respects_future(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "future.sqlite")
    q.enqueue(["later"], run_at=time.time() + 60.0)
    assert q.dequeue() is None


def test_ack_removes_row(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "ack.sqlite")
    q.enqueue(["do"])
    item = q.dequeue()
    assert item is not None
    q.ack(item.id)
    assert q.size() == 0
    assert q.size("inflight") == 0


def test_nack_requeues(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "nr.sqlite")
    q.enqueue(["retry"])
    first = q.dequeue()
    assert first is not None
    q.nack(first.id, reason="transient")
    second = q.dequeue()
    assert second is not None
    assert second.action == ["retry"]
    assert second.attempts == 2


def test_nack_to_dead_letter(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "dl.sqlite")
    q.enqueue(["fatal"])
    item = q.dequeue()
    assert item is not None
    q.nack(item.id, requeue=False, reason="bad input")
    assert q.dequeue() is None
    dead = q.dead_letters()
    assert len(dead) == 1
    assert dead[0].action == ["fatal"]


def test_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "persist.sqlite"
    q1 = ActionQueue(db)
    q1.enqueue(["survive"])
    q2 = ActionQueue(db)
    item = q2.dequeue()
    assert item is not None
    assert item.action == ["survive"]


def test_enqueue_rejects_bad_payload(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "bad.sqlite")
    with pytest.raises(QueueException):
        q.enqueue("not-a-list")  # type: ignore[arg-type]


def test_purge_clears_all(tmp_path: Path) -> None:
    q = ActionQueue(tmp_path / "purge.sqlite")
    for i in range(3):
        q.enqueue([f"a{i}"])
    dequeued = q.dequeue()
    assert dequeued is not None
    q.nack(dequeued.id, requeue=False, reason="x")
    removed = q.purge()
    assert removed == 3
    assert q.size() == 0
    assert q.dead_letters() == []
