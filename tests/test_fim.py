"""Tests for the file integrity monitor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from automation_file import IntegrityMonitor, write_manifest
from automation_file.exceptions import FileAutomationException
from automation_file.notify import NotificationManager
from automation_file.notify.sinks import NotificationSink


class _Recorder(NotificationSink):
    name = "recorder"

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self.messages.append((subject, body, level))


def _build_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_text("alpha", encoding="utf-8")
    (root / "b.txt").write_text("bravo", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(root, manifest_path)
    return root, manifest_path


def test_check_once_clean_tree(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    monitor = IntegrityMonitor(root, manifest_path)
    summary = monitor.check_once()
    assert summary["ok"] is True
    assert monitor.last_summary is summary


def test_check_once_detects_modified_file_and_notifies(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    manager = NotificationManager(dedup_seconds=0.0)
    recorder = _Recorder()
    manager.register(recorder)
    monitor = IntegrityMonitor(root, manifest_path, manager=manager)
    summary = monitor.check_once()
    assert summary["ok"] is False
    assert "a.txt" in summary["modified"]
    assert recorder.messages, "expected a drift notification"
    subject, body, level = recorder.messages[0]
    assert level == "error"
    assert "integrity drift" in subject
    assert "a.txt" in body


def test_check_once_detects_missing_file(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "b.txt").unlink()
    manager = NotificationManager(dedup_seconds=0.0)
    recorder = _Recorder()
    manager.register(recorder)
    monitor = IntegrityMonitor(root, manifest_path, manager=manager)
    summary = monitor.check_once()
    assert "b.txt" in summary["missing"]
    assert recorder.messages


def test_extras_ignored_by_default(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "new.txt").write_text("novel", encoding="utf-8")
    manager = NotificationManager(dedup_seconds=0.0)
    recorder = _Recorder()
    manager.register(recorder)
    monitor = IntegrityMonitor(root, manifest_path, manager=manager)
    summary = monitor.check_once()
    assert "new.txt" in summary["extra"]
    assert summary["ok"] is True
    assert recorder.messages == []


def test_alert_on_extra_flag(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "new.txt").write_text("novel", encoding="utf-8")
    manager = NotificationManager(dedup_seconds=0.0)
    recorder = _Recorder()
    manager.register(recorder)
    monitor = IntegrityMonitor(root, manifest_path, manager=manager, alert_on_extra=True)
    monitor.check_once()
    assert recorder.messages


def test_on_drift_callback_invoked(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    seen: list[dict[str, Any]] = []
    monitor = IntegrityMonitor(
        root,
        manifest_path,
        manager=NotificationManager(dedup_seconds=0.0),
        on_drift=seen.append,
    )
    monitor.check_once()
    assert len(seen) == 1
    assert "a.txt" in seen[0]["modified"]


def test_missing_manifest_treated_as_drift(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_text("alpha", encoding="utf-8")
    manager = NotificationManager(dedup_seconds=0.0)
    recorder = _Recorder()
    manager.register(recorder)
    monitor = IntegrityMonitor(root, tmp_path / "missing.json", manager=manager)
    summary = monitor.check_once()
    assert summary["ok"] is False
    assert "error" in summary
    assert recorder.messages


def test_positive_interval_required(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    with pytest.raises(FileAutomationException):
        IntegrityMonitor(root, manifest_path, interval=0)


def test_start_and_stop_thread(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    monitor = IntegrityMonitor(root, manifest_path, interval=0.05)
    monitor.start()
    try:
        # Second start is a no-op.
        monitor.start()
    finally:
        monitor.stop(timeout=1.0)
