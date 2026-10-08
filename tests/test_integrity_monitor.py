"""IntegrityMonitor: snapshot, baseline, verify, accept, alerts and continuous mode."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file.core.manifest import write_manifest
from automation_file.events import (
    Event,
    EventBus,
    IntegrityViolation,
    Severity,
    correlation_scope,
    event_bus,
)
from automation_file.exceptions import StoragePermissionException
from automation_file.integrity import (
    AlertPolicy,
    BaselineManager,
    DriftReport,
    IntegrityException,
    IntegrityMonitor,
    Snapshot,
    load_manifest,
)
from automation_file.storage import File, Storage, clear_memory_stores

TREE = "memory://monitor/tree"
BASELINE = "memory://baselines/tree.json"
FILES = {"a.txt": b"alpha", "b.txt": b"bravo", "sub/c.txt": b"charlie"}
WAIT = 10.0


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def tree() -> Storage:
    storage = Storage(TREE)
    for path, data in FILES.items():
        storage.file(path).write(data)
    return storage


@pytest.fixture
def monitor(tree: Storage, bus: EventBus) -> IntegrityMonitor:
    watching = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus)
    watching.create_baseline()
    return watching


def _local_tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    for path, data in FILES.items():
        (root / path).write_bytes(data)
    return root


def _rewrite_in_place(path: Path, data: bytes) -> None:
    """Replace the content of ``path`` and put its modification time back."""
    stamp = path.stat()
    path.write_bytes(data)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))


# ---------------------------------------------------------------------- snapshot and baseline


def test_snapshot_mode_reads_the_tree_and_stores_nothing(tree: Storage) -> None:
    watching = IntegrityMonitor(TREE)
    snapshot = watching.snapshot()
    assert isinstance(snapshot, Snapshot)
    assert snapshot.paths == ("a.txt", "b.txt", "sub/c.txt")
    assert (watching.target, watching.baseline, watching.algorithm) == (TREE, None, "sha256")
    assert watching.has_baseline() is False
    assert [info.path for info in Storage("memory://monitor").list_dir()] == ["tree"]
    assert tree.file("a.txt").read() == b"alpha"
    for call in (watching.create_baseline, watching.verify, watching.accept, watching.watch):
        with pytest.raises(IntegrityException, match="has no baseline"):
            call()


def test_create_baseline_stores_a_schema_2_manifest(monitor: IntegrityMonitor) -> None:
    assert monitor.has_baseline() is True
    document = json.loads(File(BASELINE).read_text())
    assert document["schema_version"] == 2
    assert (document["root"], document["backend"], document["algorithm"]) == (
        TREE,
        "memory",
        "sha256",
    )
    assert [entry["path"] for entry in document["entries"]] == ["a.txt", "b.txt", "sub/c.txt"]
    assert document["entries"][0]["checksum"] == hashlib.sha256(b"alpha").hexdigest()
    assert [info.path for info in Storage("memory://baselines").list_dir()] == ["tree.json"]


def test_a_clean_tree_verifies_ok_and_publishes_nothing(
    monitor: IntegrityMonitor, bus: EventBus
) -> None:
    report = monitor.verify()
    assert isinstance(report, DriftReport)
    assert report.ok is True
    assert report.changes == ()
    assert (report.target, report.baseline, report.backend) == (TREE, BASELINE, "memory")
    assert (report.deep, report.partial, report.checked, report.hashed) == (True, False, 3, 3)
    assert report.notes == ()
    assert monitor.last_report is report
    assert monitor.last_run == report.verified_at
    assert monitor.last_error is None
    assert bus.recent() == []


def test_verify_reports_every_kind_of_change(monitor: IntegrityMonitor, tree: Storage) -> None:
    tree.file("a.txt").write(b"tampered")
    tree.file("b.txt").move_to(tree.file("moved/b.txt"))
    tree.file("sub/c.txt").delete()
    tree.file("new.txt").write(b"novel")
    report = monitor.verify()
    assert [(change.kind.value, change.path) for change in report.changes] == [
        ("modified", "a.txt"),
        ("renamed", "moved/b.txt"),
        ("created", "new.txt"),
        ("deleted", "sub/c.txt"),
    ]
    assert report.changes[1].previous_path == "b.txt"
    assert report.ok is False


def test_the_baseline_can_live_in_another_backend(tmp_path: Path, bus: EventBus) -> None:
    root = _local_tree(tmp_path)
    in_memory = IntegrityMonitor(root, baseline="memory://elsewhere/base/tree.json", bus=bus)
    in_memory.create_baseline()
    assert load_manifest(File("memory://elsewhere/base/tree.json").read()).backend == "local"
    (root / "a.txt").write_bytes(b"tampered")
    assert in_memory.verify().paths("modified") == ["a.txt"]

    storage = Storage(TREE)
    storage.file("a.txt").write(b"alpha")
    on_disk = IntegrityMonitor(TREE, baseline=tmp_path / "state" / "tree.json", bus=bus)
    on_disk.create_baseline()
    assert (tmp_path / "state" / "tree.json").is_file()
    assert sorted(path.name for path in (tmp_path / "state").iterdir()) == ["tree.json"]
    storage.file("a.txt").delete()
    assert on_disk.verify().paths("deleted") == ["a.txt"]


def test_a_failed_save_leaves_the_previous_baseline_and_no_temporary_file(
    monitor: IntegrityMonitor, tree: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = File(BASELINE).read()
    tree.file("new.txt").write(b"novel")

    def _deny(*_args: object, **_options: object) -> None:
        raise StoragePermissionException("access to the baseline was denied")

    monkeypatch.setattr(File, "move_to", _deny)
    with pytest.raises(StoragePermissionException):
        monitor.create_baseline()
    assert File(BASELINE).read() == before
    assert [info.path for info in Storage("memory://baselines").list_dir()] == ["tree.json"]


def test_a_baseline_inside_the_target_is_not_part_of_the_tree(tree: Storage, bus: EventBus) -> None:
    inside = f"{TREE}/.fa/baseline.json"
    watching = IntegrityMonitor(TREE, baseline=inside, bus=bus)
    assert watching.create_baseline().paths == ("a.txt", "b.txt", "sub/c.txt")
    assert tree.file(".fa/baseline.json").is_file()
    assert watching.verify().ok is True
    assert watching.snapshot().paths == ("a.txt", "b.txt", "sub/c.txt")
    tree.file(".fa/.baseline.json.0123abcd.tmp").write(b"half-written")
    tree.file(".fa/other.json").write(b"{}")
    assert watching.verify().paths("created") == [".fa/other.json"]


def test_the_baseline_cannot_be_the_target_itself_or_a_storage_root(tree: Storage) -> None:
    with pytest.raises(IntegrityException, match="same location"):
        IntegrityMonitor(TREE, baseline=TREE)
    with pytest.raises(IntegrityException, match="must be a file"):
        BaselineManager("memory://baselines")


def test_a_missing_or_broken_baseline_is_an_error(tree: Storage, bus: EventBus) -> None:
    watching = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus)
    with pytest.raises(IntegrityException, match=r"no baseline at memory://baselines/tree\.json"):
        watching.verify()
    File(BASELINE).write(b"{not json")
    with pytest.raises(IntegrityException, match="not readable JSON"):
        watching.verify()
    File(BASELINE).write(json.dumps({"schema_version": 9, "entries": []}))
    with pytest.raises(IntegrityException, match="schema version 9"):
        watching.verify()
    Storage("memory://baselines").mkdir("folder.json")
    with pytest.raises(IntegrityException, match="is a directory"):
        IntegrityMonitor(TREE, baseline="memory://baselines/folder.json").verify()
    assert bus.recent() == []


# ---------------------------------------------------------------------- the event


def test_drift_is_published_as_one_integrity_violation(
    monitor: IntegrityMonitor, tree: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").write(b"tampered")
    tree.file("new.txt").write(b"novel")
    received: list[Event] = []
    bus.subscribe(received.append)
    report = monitor.verify()
    (event,) = received
    assert isinstance(event, IntegrityViolation)
    assert event.type == "integrity.violation"
    assert event.source == "integrity"
    assert event.severity is Severity.ERROR
    assert event.subject == f"integrity drift: {TREE} (1 created, 1 modified)"
    assert len(event.correlation_id) == 32
    assert event.correlation_id == report.correlation_id
    assert json.loads(json.dumps(event.to_dict()))["payload"] == {
        "action": "verify",
        "resource": TREE,
        "backend": "memory",
        "status": "drift",
        "baseline": BASELINE,
        "algorithm": "sha256",
        "deep": True,
        "partial": False,
        "counts": {
            "created": 1,
            "modified": 1,
            "deleted": 0,
            "renamed": 0,
            "metadata_changed": 0,
            "permission_changed": 0,
        },
        "total": 2,
        "changes": [
            {"kind": "modified", "path": "a.txt"},
            {"kind": "created", "path": "new.txt"},
        ],
        "truncated": False,
    }


def test_the_event_joins_the_enclosing_correlation_scope(
    monitor: IntegrityMonitor, tree: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").delete()
    with correlation_scope("run-42"):
        report = monitor.verify()
    assert report.correlation_id == "run-42"
    assert [event.correlation_id for event in bus.recent()] == ["run-42"]
    again = monitor.verify()
    assert again.correlation_id != "run-42"
    assert bus.recent(limit=1)[0].correlation_id == again.correlation_id


def test_only_additions_are_a_warning(
    monitor: IntegrityMonitor, tree: Storage, bus: EventBus
) -> None:
    tree.file("new.txt").write(b"novel")
    monitor.verify()
    assert [event.severity for event in bus.recent()] == [Severity.WARNING]


@pytest.mark.parametrize(
    "change",
    ["modified", "deleted", "renamed"],
)
def test_anything_that_alters_the_baseline_content_is_an_error(
    monitor: IntegrityMonitor, tree: Storage, bus: EventBus, change: str
) -> None:
    tree.file("new.txt").write(b"novel")
    if change == "modified":
        tree.file("a.txt").write(b"tampered")
    elif change == "deleted":
        tree.file("a.txt").delete()
    else:
        tree.file("a.txt").move_to(tree.file("z.txt"))
    assert monitor.verify().counts[change] == 1
    assert [event.severity for event in bus.recent()] == [Severity.ERROR]


def test_metadata_and_permission_changes(tmp_path: Path, bus: EventBus) -> None:
    root = _local_tree(tmp_path)
    watching = IntegrityMonitor(root, baseline=tmp_path / "baseline.json", bus=bus)
    watching.create_baseline()
    stamp = (root / "a.txt").stat()
    os.utime(root / "a.txt", ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 5_000_000_000))
    report = watching.verify()
    (touched,) = report.changes
    assert (touched.kind.value, touched.path, touched.fields) == (
        "metadata_changed",
        "a.txt",
        ("modified_at",),
    )
    assert bus.recent(limit=1)[0].severity is Severity.WARNING

    watching.accept(report)
    os.chmod(root / "b.txt", stat.S_IREAD)
    try:
        (locked,) = watching.verify().changes
    finally:
        os.chmod(root / "b.txt", stat.S_IREAD | stat.S_IWRITE)
    assert (locked.kind.value, locked.path, locked.fields) == (
        "permission_changed",
        "b.txt",
        ("mode",),
    )
    assert locked.before is not None and locked.after is not None
    assert locked.before.mode != locked.after.mode
    assert bus.recent(limit=1)[0].severity is Severity.ERROR


def test_the_severity_of_each_kind_is_configurable(tree: Storage, bus: EventBus) -> None:
    policy = AlertPolicy(severities={"created": "critical", "modified": Severity.INFO})
    watching = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus, alerts=policy)
    watching.create_baseline()
    tree.file("a.txt").write(b"tampered")
    watching.verify()
    tree.file("new.txt").write(b"novel")
    watching.verify()
    assert [event.severity for event in bus.recent()] == [Severity.CRITICAL, Severity.INFO]
    with pytest.raises(IntegrityException, match="invalid alert severity"):
        AlertPolicy(severities={"created": "loud"})
    with pytest.raises(IntegrityException, match="invalid alert severity"):
        AlertPolicy(severities={"vanished": "error"})
    with pytest.raises(IntegrityException, match="max_changes"):
        AlertPolicy(max_changes=-1)


def test_the_payload_lists_only_the_first_changes(tree: Storage, bus: EventBus) -> None:
    watching = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus, alerts=AlertPolicy(max_changes=2))
    watching.create_baseline()
    for index in range(5):
        tree.file(f"new{index}.txt").write(f"novel {index}")
    watching.verify()
    payload = bus.recent()[0].payload
    assert [change["path"] for change in payload["changes"]] == ["new0.txt", "new1.txt"]
    assert (payload["total"], payload["truncated"], payload["counts"]["created"]) == (5, True, 5)


def test_events_go_to_the_process_wide_bus_by_default(tree: Storage) -> None:
    received: list[Event] = []
    subscription = event_bus.subscribe(received.append, types=IntegrityViolation)
    try:
        watching = IntegrityMonitor(TREE, baseline=BASELINE)
        watching.create_baseline()
        tree.file("a.txt").write(b"tampered")
        watching.verify()
    finally:
        event_bus.unsubscribe(subscription)
    assert [event.payload["resource"] for event in received] == [TREE]


# ---------------------------------------------------------------------- deep and quick


def test_a_quick_pass_hashes_only_what_looks_different(tmp_path: Path, bus: EventBus) -> None:
    root = _local_tree(tmp_path)
    watching = IntegrityMonitor(root, baseline=tmp_path / "baseline.json", bus=bus)
    watching.create_baseline()
    quick = watching.verify(deep=False)
    assert (quick.ok, quick.deep, quick.checked, quick.hashed) == (True, False, 3, 0)
    assert quick.notes == (
        "quick pass: 0 of 3 files hashed; size, modification time and etag decided the rest",
    )
    assert quick.to_dict()["deep"] is False

    (root / "a.txt").write_bytes(b"tampered with")
    (root / "new.txt").write_bytes(b"novel")
    quick = watching.verify(deep=False)
    assert [(change.kind.value, change.path) for change in quick.changes] == [
        ("modified", "a.txt"),
        ("created", "new.txt"),
    ]
    assert (quick.checked, quick.hashed) == (4, 2)
    assert bus.recent(limit=1)[0].payload["deep"] is False


def test_only_a_deep_pass_sees_a_change_that_keeps_size_and_time(
    tmp_path: Path, bus: EventBus
) -> None:
    root = _local_tree(tmp_path)
    watching = IntegrityMonitor(root, baseline=tmp_path / "baseline.json", bus=bus)
    watching.create_baseline()
    _rewrite_in_place(root / "a.txt", b"ALPHA")
    quick = watching.verify(deep=False)
    assert (quick.ok, quick.hashed) == (True, 0)
    deep = watching.verify()
    assert (deep.deep, deep.hashed, deep.notes) == (True, 3, ())
    assert deep.paths("modified") == ["a.txt"]


def test_a_quick_pass_against_a_legacy_baseline_hashes_everything(
    tmp_path: Path, bus: EventBus
) -> None:
    root = _local_tree(tmp_path)
    write_manifest(root, tmp_path / "manifest.json")
    watching = IntegrityMonitor(root, tmp_path / "manifest.json", bus=bus)
    quick = watching.verify(deep=False)
    assert (quick.ok, quick.checked, quick.hashed) == (True, 3, 3)


# ---------------------------------------------------------------------- accept


def test_accept_stores_exactly_what_the_report_saw(
    monitor: IntegrityMonitor, tree: Storage
) -> None:
    tree.file("a.txt").write(b"approved change")
    report = monitor.verify()
    tree.file("late.txt").write(b"arrived after the report")
    accepted = monitor.accept(report)
    assert accepted is report.snapshot
    assert accepted.paths == ("a.txt", "b.txt", "sub/c.txt")
    after = monitor.verify()
    assert [(change.kind.value, change.path) for change in after.changes] == [
        ("created", "late.txt")
    ]


def test_accept_without_a_report_reads_the_tree_again(
    monitor: IntegrityMonitor, tree: Storage
) -> None:
    tree.file("a.txt").write(b"approved change")
    tree.file("new.txt").write(b"novel")
    assert monitor.accept().paths == ("a.txt", "b.txt", "new.txt", "sub/c.txt")
    assert monitor.verify().ok is True


def test_accept_refuses_a_report_about_another_target(monitor: IntegrityMonitor) -> None:
    with pytest.raises(IntegrityException, match="memory://other/tree, not this monitor's"):
        monitor.accept(DriftReport(target="memory://other/tree"))


def test_accept_keeps_the_algorithm_of_the_baseline(tree: Storage, bus: EventBus) -> None:
    IntegrityMonitor(TREE, baseline=BASELINE, algorithm="sha512", bus=bus).create_baseline()
    plain = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus)
    assert plain.algorithm == "sha256"
    report = plain.verify()
    assert (report.ok, report.algorithm) == (True, "sha512")
    tree.file("a.txt").write(b"approved change")
    assert plain.accept().algorithm == "sha512"
    assert plain.accept(plain.verify()).algorithm == "sha512"
    assert load_manifest(File(BASELINE).read()).algorithm == "sha512"
    assert plain.create_baseline().algorithm == "sha256"


def test_accept_turns_a_legacy_baseline_into_schema_2(tmp_path: Path, bus: EventBus) -> None:
    root = _local_tree(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    write_manifest(root, manifest_path)
    watching = IntegrityMonitor(root, manifest_path, bus=bus)
    (root / "a.txt").write_bytes(b"approved change")
    watching.accept(watching.verify())
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 2
    assert document["entries"][0]["modified_at"] is not None
    assert watching.verify().ok is True


# ---------------------------------------------------------------------- algorithms


def test_a_monitor_refuses_a_weak_algorithm_unless_told_otherwise(tree: Storage) -> None:
    with pytest.raises(IntegrityException, match="not collision-resistant"):
        IntegrityMonitor(TREE, baseline=BASELINE, algorithm="md5")
    with pytest.raises(IntegrityException, match="unsupported integrity algorithm"):
        IntegrityMonitor(TREE, baseline=BASELINE, algorithm="crc32", allow_weak=True)
    allowed = IntegrityMonitor(TREE, baseline=BASELINE, algorithm="md5", allow_weak=True)
    entry = allowed.snapshot().get("a.txt")
    assert entry is not None
    assert entry.checksum == hashlib.md5(b"alpha", usedforsecurity=False).hexdigest()


def test_a_weak_baseline_is_not_verified_without_allow_weak(tree: Storage, bus: EventBus) -> None:
    IntegrityMonitor(
        TREE, baseline=BASELINE, algorithm="md5", allow_weak=True, bus=bus
    ).create_baseline()
    strict = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus)
    with pytest.raises(IntegrityException, match="md5 is refused"):
        strict.verify()
    with pytest.raises(IntegrityException, match="md5 is refused"):
        strict.accept()
    lenient = IntegrityMonitor(TREE, baseline=BASELINE, allow_weak=True, bus=bus)
    assert lenient.verify().algorithm == "md5"


# ---------------------------------------------------------------------- continuous mode


def test_continuous_mode_verifies_on_a_thread(
    monitor: IntegrityMonitor, tree: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").write(b"tampered")
    found = threading.Event()
    bus.subscribe(lambda _event: found.set(), types=IntegrityViolation)
    watching = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus, interval=0.02)
    assert watching.is_running is False
    watching.start()
    try:
        watching.start()
        assert watching.is_running is True
        assert found.wait(WAIT), "continuous mode did not verify"
    finally:
        watching.stop()
    assert watching.is_running is False
    report = watching.last_report
    assert report is not None
    assert report.paths("modified") == ["a.txt"]
    assert watching.last_summary is not None
    assert watching.last_summary["modified"] == ["a.txt"]
    watching.stop()


def test_continuous_mode_survives_a_failing_pass(tree: Storage, bus: EventBus) -> None:
    failed = threading.Event()
    recovered = threading.Event()

    def _route(event: Event) -> None:
        (failed if event.payload["status"] == "error" else recovered).set()

    bus.subscribe(_route, types=IntegrityViolation)
    watching = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus, interval=0.02)
    watching.start()
    try:
        assert failed.wait(WAIT), "the missing baseline was not reported"
        assert watching.last_error is not None
        assert watching.last_error.startswith("IntegrityException: no baseline at ")
        watching.create_baseline()
        tree.file("a.txt").write(b"tampered")
        assert recovered.wait(WAIT), "the monitor did not keep running after a failed pass"
    finally:
        watching.stop()
    assert watching.last_error is None


def test_status_is_json_friendly(monitor: IntegrityMonitor, tree: Storage) -> None:
    idle = monitor.status()
    assert idle == {
        "target": TREE,
        "baseline": BASELINE,
        "algorithm": "sha256",
        "interval": 60.0,
        "running": False,
        "last_run": None,
        "last_error": None,
        "last_report": None,
    }
    tree.file("a.txt").write(b"tampered")
    report = monitor.verify()
    status = json.loads(json.dumps(monitor.status()))
    assert status["last_run"] == report.verified_at.isoformat()
    assert status["last_report"]["counts"]["modified"] == 1
    assert status["last_report"]["ok"] is False
