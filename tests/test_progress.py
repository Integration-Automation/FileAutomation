"""Tests for transfer progress + cancellation primitives."""

from __future__ import annotations

import threading

import pytest

from automation_file.core.progress import (
    CancellationToken,
    CancelledException,
    ProgressRegistry,
    ProgressReporter,
    register_progress_ops,
)
from automation_file.exceptions import FileAutomationException


def test_cancellation_token_flag_roundtrip() -> None:
    token = CancellationToken()
    assert not token.is_cancelled
    token.cancel()
    assert token.is_cancelled


def test_cancellation_token_raise_if_cancelled() -> None:
    token = CancellationToken()
    token.raise_if_cancelled()  # no-op
    token.cancel()
    with pytest.raises(CancelledException):
        token.raise_if_cancelled()


def test_cancelled_exception_inherits_from_file_automation() -> None:
    assert issubclass(CancelledException, FileAutomationException)


def test_progress_reporter_tracks_bytes_and_status() -> None:
    reporter = ProgressReporter(name="test", total=100)
    reporter.update(30)
    reporter.update(0)
    reporter.update(-5)
    reporter.update(20)
    snapshot = reporter.snapshot()
    assert snapshot["transferred"] == 50
    assert snapshot["status"] == "running"
    assert not reporter.is_finished
    reporter.finish(status="done")
    assert reporter.is_finished
    assert reporter.snapshot()["status"] == "done"


def test_progress_reporter_thread_safety() -> None:
    reporter = ProgressReporter(name="race", total=10_000)

    def worker() -> None:
        for _ in range(1000):
            reporter.update(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert reporter.snapshot()["transferred"] == 10_000


def test_progress_registry_create_lookup_cancel() -> None:
    registry = ProgressRegistry()
    reporter, token = registry.create("job-1", total=500)
    assert "job-1" in registry
    fetched = registry.lookup("job-1")
    assert fetched is not None
    assert fetched[0] is reporter
    assert fetched[1] is token
    assert registry.cancel("job-1") is True
    assert token.is_cancelled
    assert registry.cancel("missing") is False


def test_progress_registry_list_returns_snapshots() -> None:
    registry = ProgressRegistry()
    registry.create("a", total=100)
    registry.create("b")
    listing = registry.list()
    assert {entry["name"] for entry in listing} == {"a", "b"}
    assert all(entry["status"] == "running" for entry in listing)


def test_progress_registry_clear_finished() -> None:
    registry = ProgressRegistry()
    reporter_a, _ = registry.create("done")
    registry.create("still-running")
    reporter_a.finish(status="done")
    dropped = registry.clear_finished()
    assert dropped == 1
    names = [entry["name"] for entry in registry.list()]
    assert names == ["still-running"]


def test_progress_registry_forget() -> None:
    registry = ProgressRegistry()
    registry.create("forget-me")
    assert registry.forget("forget-me") is True
    assert "forget-me" not in registry
    assert registry.forget("never-there") is False


def test_register_progress_ops_populates_registry() -> None:
    from automation_file.core.action_registry import ActionRegistry

    action_registry = ActionRegistry()
    register_progress_ops(action_registry)
    for name in ("FA_progress_list", "FA_progress_cancel", "FA_progress_clear"):
        assert name in action_registry


def test_default_registry_contains_progress_ops() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_progress_list" in registry
    assert "FA_progress_cancel" in registry
    assert "FA_progress_clear" in registry
