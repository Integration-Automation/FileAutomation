"""The first monitor's behaviour, kept by ``automation_file.integrity.IntegrityMonitor``.

The first half repeats the cases of ``tests/test_fim.py`` against the new class:
the legacy call ``IntegrityMonitor(root, manifest_path, ...)`` on a manifest
written by ``write_manifest``. The rest covers what the summary does with the
change kinds the first monitor did not know.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import automation_file
from automation_file.core import fim
from automation_file.core.manifest import ManifestException, verify_manifest, write_manifest
from automation_file.events import EventBus, IntegrityViolation
from automation_file.exceptions import FileAutomationException
from automation_file.integrity import IntegrityException, IntegrityMonitor
from automation_file.integrity.legacy import LegacyHooks, format_body
from automation_file.notify import NotificationManager, notification_manager
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


def _recording_manager() -> tuple[NotificationManager, _Recorder]:
    manager = NotificationManager(dedup_seconds=0.0)
    recorder = _Recorder()
    manager.register(recorder)
    return manager, recorder


# ---------------------------------------------------------------------- the cases of test_fim.py


def test_check_once_clean_tree(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    monitor = IntegrityMonitor(root, manifest_path)
    summary = monitor.check_once()
    assert summary["ok"] is True
    assert monitor.last_summary is summary


def test_check_once_detects_modified_file_and_notifies(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    manager, recorder = _recording_manager()
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
    manager, recorder = _recording_manager()
    monitor = IntegrityMonitor(root, manifest_path, manager=manager)
    summary = monitor.check_once()
    assert "b.txt" in summary["missing"]
    assert recorder.messages


def test_extras_ignored_by_default(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "new.txt").write_text("novel", encoding="utf-8")
    manager, recorder = _recording_manager()
    monitor = IntegrityMonitor(root, manifest_path, manager=manager)
    summary = monitor.check_once()
    assert "new.txt" in summary["extra"]
    assert summary["ok"] is True
    assert not recorder.messages


def test_alert_on_extra_flag(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "new.txt").write_text("novel", encoding="utf-8")
    manager, recorder = _recording_manager()
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
    manager, recorder = _recording_manager()
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


# ---------------------------------------------------------------------- beyond test_fim.py


def test_the_legacy_import_path_is_the_new_class() -> None:
    assert fim.IntegrityMonitor is IntegrityMonitor
    assert automation_file.IntegrityMonitor is IntegrityMonitor


def test_the_legacy_keyword_names_still_work(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    manager, recorder = _recording_manager()
    seen: list[dict[str, Any]] = []
    monitor = IntegrityMonitor(
        root=str(root),
        manifest_path=str(manifest_path),
        interval=60.0,
        manager=manager,
        on_drift=seen.append,
    )
    assert monitor.check_once()["modified"] == ["a.txt"]
    assert len(seen) == len(recorder.messages) == 1
    with pytest.raises(IntegrityException, match="target= or its older name root="):
        IntegrityMonitor(root, root=root)
    with pytest.raises(IntegrityException, match="baseline= or its older name manifest_path="):
        IntegrityMonitor(root, manifest_path, manifest_path=manifest_path)
    with pytest.raises(IntegrityException, match="needs a target"):
        IntegrityMonitor(manifest_path=manifest_path)


def test_the_summary_keeps_the_legacy_shape(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    (root / "new.txt").write_text("novel", encoding="utf-8")
    summary = IntegrityMonitor(root, manifest_path, bus=EventBus()).check_once()
    assert summary == {
        "matched": ["b.txt"],
        "missing": [],
        "modified": ["a.txt"],
        "extra": ["new.txt"],
        "ok": False,
    }


def test_a_rename_is_missing_plus_extra_in_the_summary(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").rename(root / "renamed.txt")
    monitor = IntegrityMonitor(root, manifest_path, bus=EventBus())
    summary = monitor.check_once()
    assert (summary["missing"], summary["extra"], summary["ok"]) == (
        ["a.txt"],
        ["renamed.txt"],
        False,
    )
    report = monitor.last_report
    assert report is not None
    assert report.counts["renamed"] == 1


def test_without_a_manager_the_process_wide_one_is_notified(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    recorder = _Recorder()
    notification_manager.register(recorder)
    try:
        bus = EventBus()
        summary = IntegrityMonitor(root, manifest_path, bus=bus).check_once()
    finally:
        notification_manager.unregister(recorder.name)
    assert summary["ok"] is False
    assert [level for _, _, level in recorder.messages] == ["error"]
    assert [event.type for event in bus.recent()] == ["integrity.violation"]


def test_notify_false_sends_no_notification(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    passed, own = _recording_manager()
    shared = _Recorder()
    notification_manager.register(shared)
    seen: list[dict[str, Any]] = []
    try:
        bus = EventBus()
        IntegrityMonitor(
            root, manifest_path, manager=passed, notify=False, on_drift=seen.append, bus=bus
        ).check_once()
    finally:
        notification_manager.unregister(shared.name)
    assert own.messages == []
    assert shared.messages == []
    assert len(seen) == 1
    assert [event.type for event in bus.recent()] == ["integrity.violation"]


def test_an_unknown_keyword_is_a_type_error(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'intervall'"):
        IntegrityMonitor(tmp_path, intervall=5.0)  # type: ignore[call-arg]


def test_verify_manifest_names_the_new_reader_for_a_baseline(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    IntegrityMonitor(root, manifest_path, bus=EventBus()).accept()
    with pytest.raises(ManifestException, match="FA_integrity_verify"):
        verify_manifest(root, manifest_path)


def test_a_failed_pass_is_an_event_and_stays_in_the_status(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    bus = EventBus()
    monitor = IntegrityMonitor(root, tmp_path / "missing.json", bus=bus)
    summary = monitor.check_once()
    assert summary["matched"] == summary["missing"] == summary["modified"] == summary["extra"] == []
    assert "IntegrityException" in summary["error"]
    (event,) = bus.recent()
    assert isinstance(event, IntegrityViolation)
    assert event.payload["status"] == "error"
    assert event.payload["error"].startswith("IntegrityException: no baseline at ")
    assert monitor.last_error == event.payload["error"]
    assert monitor.last_report is None


def test_a_missing_target_is_an_error_not_a_tree_of_deleted_files(tmp_path: Path) -> None:
    _, manifest_path = _build_tree(tmp_path)
    monitor = IntegrityMonitor(tmp_path / "gone", manifest_path, bus=EventBus())
    with pytest.raises(IntegrityException, match="does not exist"):
        monitor.verify()
    assert "does not exist" in monitor.check_once()["error"]


def test_an_on_drift_failure_does_not_stop_the_notification(tmp_path: Path) -> None:
    root, manifest_path = _build_tree(tmp_path)
    (root / "a.txt").write_text("tampered", encoding="utf-8")
    manager, recorder = _recording_manager()

    def broken(_summary: dict[str, Any]) -> None:
        raise RuntimeError("callback bug")

    monitor = IntegrityMonitor(
        root, manifest_path, manager=manager, on_drift=broken, bus=EventBus()
    )
    assert monitor.check_once()["modified"] == ["a.txt"]
    assert len(recorder.messages) == 1


def test_the_notification_body_lists_the_first_paths() -> None:
    summary = {
        "missing": [f"m{index}.txt" for index in range(7)],
        "modified": ["changed.txt"],
        "extra": [],
        "error": "IntegrityException('boom')",
    }
    assert format_body(summary).splitlines() == [
        "error: IntegrityException('boom')",
        "missing: m0.txt, m1.txt, m2.txt, m3.txt, m4.txt (+2 more)",
        "modified: changed.txt",
    ]
    assert format_body({"missing": [], "modified": [], "extra": []}) == "no drift detected"


_DRIFT = {"matched": [], "missing": ["a.txt"], "modified": [], "extra": [], "ok": False}


@pytest.fixture
def shared_recorder() -> Any:
    recorder = _Recorder()
    notification_manager.register(recorder)
    yield recorder
    notification_manager.unregister(recorder.name)


def _router(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    monkeypatch.setattr(
        "automation_file.notify.router.notification_router", SimpleNamespace(active=active)
    )


def test_an_active_router_delivers_in_place_of_the_shared_manager(
    monkeypatch: pytest.MonkeyPatch, shared_recorder: _Recorder
) -> None:
    _router(monkeypatch, active=True)
    LegacyHooks("drift: an active router").handle(dict(_DRIFT))
    assert shared_recorder.messages == []


def test_an_idle_router_leaves_the_shared_manager_notified(
    monkeypatch: pytest.MonkeyPatch, shared_recorder: _Recorder
) -> None:
    _router(monkeypatch, active=False)
    LegacyHooks("drift: an idle router").handle(dict(_DRIFT))
    assert [subject for subject, _, _ in shared_recorder.messages] == ["drift: an idle router"]


def test_a_private_bus_is_not_routed_so_the_shared_manager_is_notified(
    monkeypatch: pytest.MonkeyPatch, shared_recorder: _Recorder
) -> None:
    _router(monkeypatch, active=True)
    LegacyHooks("drift: a private bus", on_shared_bus=False).handle(dict(_DRIFT))
    assert [subject for subject, _, _ in shared_recorder.messages] == ["drift: a private bus"]


def test_a_manager_that_was_passed_is_notified_whatever_the_router_does(
    monkeypatch: pytest.MonkeyPatch, shared_recorder: _Recorder
) -> None:
    _router(monkeypatch, active=True)
    manager, recorder = _recording_manager()
    LegacyHooks("drift: an own manager", manager=manager).handle(dict(_DRIFT))
    assert [subject for subject, _, _ in recorder.messages] == ["drift: an own manager"]
    assert shared_recorder.messages == []
