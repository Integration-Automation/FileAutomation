"""Watch mode: the threads, the path collector, partial verification and a real watch.

Everything but the last case is independent of the operating system delivering
filesystem events: the collector is given watchdog event objects, and partial
verification is called with the paths a watcher would report. The last case
writes to a watched directory for real and is skipped where no event arrives.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from watchdog.events import (
    DirDeletedEvent,
    DirModifiedEvent,
    FileClosedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileOpenedEvent,
)

from automation_file.events import Event, EventBus, IntegrityViolation
from automation_file.exceptions import StorageURIException
from automation_file.integrity import IntegrityException, IntegrityMonitor, WatchHandle
from automation_file.integrity.local_watcher import LocalWatcher, PathCollector
from automation_file.integrity.watcher import Debouncer, IntervalRunner, PollingWatcher

WAIT = 10.0
FILES = {"a.txt": b"alpha", "b.txt": b"bravo", "sub/c.txt": b"charlie", "sub/d.txt": b"delta"}


class _Inbox:
    """Collects what a thread delivers and lets a test wait for the next item."""

    def __init__(self) -> None:
        self.items: list = []
        self._arrived = threading.Semaphore(0)

    def put(self, item: object) -> None:
        self.items.append(item)
        self._arrived.release()

    def wait(self, timeout: float = WAIT) -> bool:
        return self._arrived.acquire(timeout=timeout)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "tree"
    (directory / "sub").mkdir(parents=True)
    for path, data in FILES.items():
        (directory / path).write_bytes(data)
    return directory


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def events(bus: EventBus) -> _Inbox:
    inbox = _Inbox()
    bus.subscribe(inbox.put, types=IntegrityViolation)
    return inbox


@pytest.fixture
def monitor(root: Path, tmp_path: Path, bus: EventBus) -> IntegrityMonitor:
    watching = IntegrityMonitor(root, baseline=tmp_path / "baseline.json", bus=bus)
    watching.create_baseline()
    return watching


@pytest.fixture
def watch(monitor: IntegrityMonitor) -> Iterator[WatchHandle]:
    handle = monitor.watch(debounce=0.01)
    yield handle
    handle.stop()


# ---------------------------------------------------------------------- the threads


def test_the_debouncer_delivers_what_arrives_together_as_one_batch() -> None:
    inbox = _Inbox()
    debouncer = Debouncer(inbox.put, 0.05)
    assert debouncer.is_running is False
    debouncer.start()
    try:
        debouncer.start()
        for path in ("a.txt", "b.txt", "a.txt"):
            debouncer.add(path)
        assert inbox.wait()
        assert inbox.items == [frozenset({"a.txt", "b.txt"})]
        debouncer.add("c.txt")
        assert inbox.wait()
        assert inbox.items[1] == frozenset({"c.txt"})
    finally:
        debouncer.stop()
    assert debouncer.is_running is False


def test_a_busy_tree_cannot_hold_a_batch_back_forever() -> None:
    inbox = _Inbox()
    debouncer = Debouncer(inbox.put, 0.02)
    stop = threading.Event()

    def _keep_changing() -> None:
        while not stop.wait(0.001):
            debouncer.add("busy.log")

    writer = threading.Thread(target=_keep_changing, daemon=True)
    debouncer.start()
    writer.start()
    try:
        assert inbox.wait(), "a batch was never delivered while paths kept arriving"
    finally:
        stop.set()
        writer.join(WAIT)
        debouncer.stop()
    assert inbox.items[0] == frozenset({"busy.log"})


def test_stopping_the_debouncer_drops_what_was_not_delivered() -> None:
    inbox = _Inbox()
    debouncer = Debouncer(inbox.put, 30.0)
    debouncer.start()
    debouncer.add("a.txt")
    debouncer.stop()
    assert debouncer.is_running is False
    assert inbox.items == []
    with pytest.raises(IntegrityException, match="must not be negative"):
        Debouncer(inbox.put, -1.0)


def test_the_interval_runner_ticks_until_stopped_and_can_start_again() -> None:
    ticks = _Inbox()
    runner = IntervalRunner(lambda: ticks.put("tick"), 0.01, name="test-runner")
    assert (runner.interval, runner.is_running) == (0.01, False)
    runner.start()
    runner.start()
    assert ticks.wait() and ticks.wait()
    runner.stop()
    assert runner.is_running is False
    count = len(ticks.items)
    runner.start()
    assert ticks.wait()
    runner.stop()
    assert len(ticks.items) > count
    with pytest.raises(IntegrityException, match="interval must be positive"):
        IntervalRunner(lambda: None, 0, name="never")


def test_the_polling_watcher_is_a_watch_handle() -> None:
    ticks = _Inbox()
    with PollingWatcher(lambda: ticks.put("tick"), 0.01) as handle:
        assert isinstance(handle, WatchHandle)
        handle.start()
        assert (handle.kind, handle.is_running) == ("poll", True)
        assert ticks.wait()
    assert handle.is_running is False


# ---------------------------------------------------------------------- the path collector


def test_the_collector_reports_paths_relative_to_the_root(root: Path) -> None:
    seen: list[str] = []
    collector = PathCollector(root, seen.append)
    collector.dispatch(FileModifiedEvent(str(root / "a.txt")))
    collector.dispatch(FileCreatedEvent(str(root / "sub" / "new.txt")))
    collector.dispatch(FileDeletedEvent(str(root / "sub" / "c.txt")))
    collector.dispatch(DirDeletedEvent(str(root / "sub")))
    collector.dispatch(FileMovedEvent(str(root / "b.txt"), str(root / "sub" / "moved.txt")))
    assert seen == ["a.txt", "sub/new.txt", "sub/c.txt", "sub", "b.txt", "sub/moved.txt"]


def test_the_collector_leaves_out_what_is_not_a_change(root: Path) -> None:
    seen: list[str] = []
    collector = PathCollector(root, seen.append)
    collector.dispatch(DirModifiedEvent(str(root / "sub")))
    collector.dispatch(FileOpenedEvent(str(root / "a.txt")))
    collector.dispatch(FileClosedEvent(str(root / "a.txt")))
    collector.dispatch(FileModifiedEvent(str(root.parent / "elsewhere.txt")))
    assert seen == []
    collector.dispatch(FileMovedEvent(str(root / "a.txt"), str(root.parent / "moved-out.txt")))
    collector.dispatch(FileModifiedEvent(bytes(root / "b.txt")))
    collector.dispatch(DirDeletedEvent(str(root)))
    assert seen == ["a.txt", "b.txt", ""]


def test_the_local_watcher_batches_the_paths_it_is_fed_and_skips_the_ignored(root: Path) -> None:
    batches = _Inbox()
    watcher = LocalWatcher(
        root, batches.put, debounce=0.02, ignore=lambda path: path.endswith(".tmp")
    )
    assert (watcher.kind, watcher.is_running) == ("events", False)
    with watcher:
        watcher.start()
        watcher.start()
        assert watcher.is_running is True
        watcher.feed("scratch.tmp")
        watcher.feed("a.txt")
        watcher.feed("sub/c.txt")
        delivered: set[str] = set()
        while not {"a.txt", "sub/c.txt"} <= delivered:
            assert batches.wait(), "the fed paths were not delivered"
            delivered = set().union(*batches.items)
        assert "scratch.tmp" not in delivered
    assert watcher.is_running is False
    watcher.stop()
    with pytest.raises(IntegrityException, match="is not a directory"):
        LocalWatcher(root / "a.txt", batches.put)


# ---------------------------------------------------------------------- verifying only what changed


def test_only_the_paths_that_changed_are_verified(
    monitor: IntegrityMonitor, root: Path, events: _Inbox
) -> None:
    (root / "a.txt").write_bytes(b"tampered")
    (root / "b.txt").write_bytes(b"also tampered, but nothing reported it")
    report = monitor.verify_paths(["a.txt"])
    assert [(change.kind.value, change.path) for change in report.changes] == [
        ("modified", "a.txt")
    ]
    assert (report.partial, report.deep, report.checked, report.hashed) == (True, True, 1, 1)
    assert report.notes == (
        "partial pass: only the paths that changed were examined (1 current and 1 baseline "
        "files), not the whole tree",
    )
    assert monitor.last_report is report
    (event,) = events.items
    assert isinstance(event, Event)
    assert (event.payload["partial"], event.payload["total"]) == (True, 1)
    assert event.correlation_id == report.correlation_id
    assert monitor.last_summary == {
        "matched": [],
        "missing": [],
        "modified": ["a.txt"],
        "extra": [],
        "ok": False,
    }


def test_a_path_that_did_not_really_change_raises_no_alert(
    monitor: IntegrityMonitor, root: Path, events: _Inbox
) -> None:
    report = monitor.verify_paths(["b.txt", "never-existed.tmp", "sub"])
    assert (report.ok, report.partial, report.checked) == (True, True, 3)
    assert monitor.verify_paths([]).ok is True
    assert events.items == []
    assert monitor.last_summary is not None
    assert monitor.last_summary["matched"] == []
    with pytest.raises(StorageURIException):
        monitor.verify_paths(["../outside.txt"])


def test_a_directory_stands_for_everything_below_it(monitor: IntegrityMonitor, root: Path) -> None:
    (root / "sub" / "c.txt").unlink()
    (root / "sub" / "d.txt").unlink()
    (root / "sub").rmdir()
    gone = monitor.verify_paths(["sub"])
    assert gone.paths("deleted") == ["sub/c.txt", "sub/d.txt"]
    assert (gone.checked, gone.hashed) == (0, 0)

    (root / "fresh").mkdir()
    (root / "fresh" / "one.txt").write_bytes(b"one")
    (root / "fresh" / "two.txt").write_bytes(b"two")
    assert monitor.verify_paths(["fresh/"]).paths("created") == ["fresh/one.txt", "fresh/two.txt"]
    everything = monitor.verify_paths([""])
    assert everything.counts["deleted"] == everything.counts["created"] == 2
    assert everything.checked == 4


def test_a_move_reported_with_both_paths_is_a_rename(monitor: IntegrityMonitor, root: Path) -> None:
    (root / "a.txt").rename(root / "sub" / "moved.txt")
    (change,) = monitor.verify_paths(["a.txt", "sub/moved.txt"]).changes
    assert (change.kind.value, change.path, change.previous_path) == (
        "renamed",
        "sub/moved.txt",
        "a.txt",
    )
    assert monitor.verify_paths(["a.txt"]).paths("deleted") == ["a.txt"]


def test_accepting_a_partial_report_stores_the_whole_tree(
    monitor: IntegrityMonitor, root: Path
) -> None:
    (root / "a.txt").write_bytes(b"approved change")
    (root / "b.txt").unlink()
    report = monitor.verify_paths(["a.txt", "b.txt"])
    assert report.partial is True
    assert monitor.accept(report).paths == ("a.txt", "sub/c.txt", "sub/d.txt")
    assert monitor.verify().ok is True


def test_the_baseline_kept_inside_the_tree_is_not_verified_as_part_of_it(
    root: Path, bus: EventBus, events: _Inbox
) -> None:
    watching = IntegrityMonitor(root, baseline=root / ".baseline.json", bus=bus)
    watching.create_baseline()
    (root / ".baseline.json").write_bytes((root / ".baseline.json").read_bytes() + b" ")
    assert watching.verify_paths([".baseline.json"]).ok is True
    assert watching.verify_paths([""]).ok is True
    assert events.items == []


# ---------------------------------------------------------------------- watching a local directory


def test_watching_needs_a_baseline_and_a_directory(root: Path, tmp_path: Path) -> None:
    with pytest.raises(IntegrityException, match="has no baseline"):
        IntegrityMonitor(root).watch()
    with pytest.raises(IntegrityException, match="is not a directory"):
        IntegrityMonitor(tmp_path / "nowhere", baseline=tmp_path / "b.json").watch()


def test_a_local_target_is_watched_through_events(watch: WatchHandle) -> None:
    assert isinstance(watch, LocalWatcher)
    assert (watch.kind, watch.is_running) == ("events", True)
    watch.stop()
    assert watch.is_running is False


def test_a_failing_pass_does_not_end_the_watch(
    monitor: IntegrityMonitor, watch: WatchHandle, root: Path, tmp_path: Path, events: _Inbox
) -> None:
    assert isinstance(watch, LocalWatcher)
    baseline = (tmp_path / "baseline.json").read_bytes()
    (tmp_path / "baseline.json").unlink()
    watch.feed("a.txt")
    assert events.wait(), "the pass that could not run was not reported"
    assert events.items[0].payload["status"] == "error"
    assert monitor.last_error is not None
    (tmp_path / "restored.json").write_bytes(baseline)
    (tmp_path / "restored.json").replace(tmp_path / "baseline.json")
    (root / "a.txt").write_bytes(b"tampered")
    watch.feed("a.txt")
    assert events.wait(), "the watch did not keep running after a failed pass"
    assert events.items[1].payload["status"] == "drift"
    assert monitor.last_error is None


def test_a_real_change_on_disk_reaches_the_monitor(
    monitor: IntegrityMonitor, watch: WatchHandle, root: Path, events: _Inbox
) -> None:
    for attempt in range(40):
        (root / "a.txt").write_bytes(f"tampered {attempt}".encode())
        if events.wait(0.25):
            break
    else:
        pytest.skip("no filesystem event arrived from watchdog in this environment")
    report = monitor.last_report
    assert report is not None
    assert report.partial is True
    assert report.paths("modified") == ["a.txt"]
