"""Tests for the filesystem watcher trigger manager.

These tests avoid asserting on actual filesystem events — watchdog's
dispatcher thread is inherently racey across platforms. Instead they cover
validation, registry wiring, lifecycle, and dict representation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import FileAutomationException
from automation_file.trigger.manager import (
    FileWatcher,
    TriggerException,
    TriggerManager,
    _parse_events,
    register_trigger_ops,
)


def test_parse_events_defaults_when_none() -> None:
    assert _parse_events(None) == frozenset({"created", "modified"})


def test_parse_events_accepts_string() -> None:
    assert _parse_events("deleted") == frozenset({"deleted"})


def test_parse_events_normalises_case_and_whitespace() -> None:
    assert _parse_events([" Created ", "MOVED"]) == frozenset({"created", "moved"})


def test_parse_events_rejects_unknown() -> None:
    with pytest.raises(TriggerException):
        _parse_events(["created", "exploded"])


def test_file_watcher_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(TriggerException):
        FileWatcher("missing", str(tmp_path / "nope"), [["FA_create_file", {}]])


def test_trigger_manager_start_stop_lifecycle(tmp_path: Path) -> None:
    manager = TriggerManager()
    snapshot = manager.start(
        name="t1",
        path=str(tmp_path),
        action_list=[["FA_watch_list"]],
        events=["created"],
        recursive=False,
    )
    try:
        assert snapshot["name"] == "t1"
        assert snapshot["running"] is True
        assert snapshot["events"] == ["created"]
        assert "t1" in manager
        listing = manager.list()
        assert len(listing) == 1 and listing[0]["name"] == "t1"
    finally:
        manager.stop("t1")
    assert "t1" not in manager
    assert manager.list() == []


def test_trigger_manager_rejects_duplicate(tmp_path: Path) -> None:
    manager = TriggerManager()
    manager.start("dup", str(tmp_path), [["FA_watch_list"]])
    try:
        with pytest.raises(TriggerException):
            manager.start("dup", str(tmp_path), [["FA_watch_list"]])
    finally:
        manager.stop_all()


def test_trigger_manager_stop_unknown_raises() -> None:
    manager = TriggerManager()
    with pytest.raises(TriggerException):
        manager.stop("never-registered")


def test_trigger_manager_stop_all_clears_everything(tmp_path: Path) -> None:
    manager = TriggerManager()
    manager.start("a", str(tmp_path), [["FA_watch_list"]])
    manager.start("b", str(tmp_path), [["FA_watch_list"]])
    snapshots = manager.stop_all()
    assert len(snapshots) == 2
    assert manager.list() == []


def test_trigger_exception_inherits_from_file_automation() -> None:
    assert issubclass(TriggerException, FileAutomationException)


def test_register_trigger_ops_populates_registry() -> None:
    from automation_file.core.action_registry import ActionRegistry

    registry = ActionRegistry()
    register_trigger_ops(registry)
    for name in (
        "FA_watch_start",
        "FA_watch_stop",
        "FA_watch_stop_all",
        "FA_watch_list",
    ):
        assert name in registry


def test_default_registry_contains_trigger_ops() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_watch_start" in registry
    assert "FA_watch_list" in registry
