"""Remediation: off by default, quarantine, restore with checksum verification."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from automation_file.events import Event, EventBus, IntegrityViolation, Severity
from automation_file.exceptions import StoragePermissionException
from automation_file.integrity import (
    IntegrityException,
    IntegrityMonitor,
    IntegrityRemediated,
    RemediationPolicy,
    RemediationStep,
    Remediator,
    Target,
)
from automation_file.storage import File, Storage, clear_memory_stores

TREE = "memory://prod/tree"
BASELINE = "memory://state/tree.json"
QUARANTINE = "memory://quarantine/tree"
MIRROR = "memory://mirror/tree"
FILES = {"a.txt": b"alpha", "b.txt": b"bravo", "sub/c.txt": b"charlie"}


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
    IntegrityMonitor(TREE, baseline=BASELINE, bus=EventBus()).create_baseline()
    return storage


@pytest.fixture
def mirror(tree: Storage) -> Storage:
    copy = Storage(MIRROR)
    tree.copy_to(copy)
    return copy


def _monitor(bus: EventBus, **policy: Any) -> IntegrityMonitor:
    return IntegrityMonitor(
        TREE, baseline=BASELINE, bus=bus, remediation=RemediationPolicy(**policy)
    )


def _files(uri: str) -> dict[str, bytes]:
    storage = Storage(uri)
    if not storage.exists():
        return {}
    return {
        info.path: storage.file(info.path).read()
        for info in storage.list_dir(recursive=True)
        if not info.is_dir
    }


def _quarantined() -> dict[str, bytes]:
    """Return the quarantined files without the timestamp directory they are under."""
    return {path.split("/", 1)[1]: data for path, data in _files(QUARANTINE).items()}


# ---------------------------------------------------------------------- off by default


def test_a_monitor_without_a_policy_changes_nothing(tree: Storage, bus: EventBus) -> None:
    tree.file("a.txt").write(b"tampered")
    tree.file("b.txt").delete()
    tree.file("new.txt").write(b"novel")
    expected = _files(TREE)
    report = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus).verify()
    assert report.remediation == ()
    assert _files(TREE) == expected
    assert [event.type for event in bus.recent()] == ["integrity.violation"]
    assert "remediation" not in bus.recent()[0].payload


def test_a_policy_does_nothing_until_an_action_is_chosen(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    policy = RemediationPolicy(quarantine=QUARANTINE, restore_from=MIRROR)
    assert policy.active is False
    assert (policy.on_created, policy.on_modified, policy.on_deleted) == ("none", "none", "none")
    tree.file("a.txt").write(b"tampered")
    tree.file("b.txt").delete()
    tree.file("new.txt").write(b"novel")
    expected = _files(TREE)
    report = IntegrityMonitor(TREE, baseline=BASELINE, bus=bus, remediation=policy).verify()
    assert report.remediation == ()
    assert _files(TREE) == expected
    assert _files(QUARANTINE) == {}


@pytest.mark.parametrize(
    "options,message",
    [
        ({"on_created": "delete"}, "on_created must be one of none, quarantine"),
        ({"on_created": "restore", "restore_from": MIRROR}, "on_created must be one of"),
        ({"on_modified": "purge"}, "on_modified must be one of none, quarantine, restore"),
        ({"on_deleted": "quarantine", "quarantine": QUARANTINE}, "on_deleted must be one of"),
        ({"on_created": "quarantine"}, "needs a quarantine= storage URI"),
        ({"on_modified": "restore"}, "needs a restore_from= storage URI"),
        ({"on_deleted": "restore", "quarantine": QUARANTINE}, "needs a restore_from="),
    ],
)
def test_a_policy_that_cannot_work_is_refused(options: dict[str, str], message: str) -> None:
    with pytest.raises(IntegrityException, match=message):
        RemediationPolicy(**options)


def test_the_quarantine_and_the_mirror_must_lie_outside_the_target(tree: Storage) -> None:
    inside = RemediationPolicy(quarantine=f"{TREE}/.quarantine", on_created="quarantine")
    with pytest.raises(IntegrityException, match="lies inside the monitored target"):
        IntegrityMonitor(TREE, baseline=BASELINE, remediation=inside)
    itself = RemediationPolicy(restore_from=TREE, on_deleted="restore")
    with pytest.raises(IntegrityException, match=r"restore_from .* lies inside"):
        IntegrityMonitor(TREE, baseline=BASELINE, remediation=itself)
    with pytest.raises(IntegrityException, match="must be a RemediationPolicy"):
        Remediator({"on_created": "quarantine"}, Target(TREE))  # type: ignore[arg-type]
    sibling = RemediationPolicy(quarantine="memory://prod/tree-quarantine", on_created="quarantine")
    assert IntegrityMonitor(TREE, baseline=BASELINE, remediation=sibling).target == TREE


# ---------------------------------------------------------------------- quarantine


def test_a_created_file_is_moved_to_a_timestamped_quarantine(tree: Storage, bus: EventBus) -> None:
    tree.file("drop/new.txt").write(b"novel")
    received: list[Event] = []
    bus.subscribe(received.append)
    report = _monitor(bus, quarantine=QUARANTINE, on_created="quarantine").verify()

    assert tree.file("drop/new.txt").exists() is False
    (stored,) = _files(QUARANTINE).items()
    stamp, _, path = stored[0].partition("/")
    assert (path, stored[1]) == ("drop/new.txt", b"novel")
    assert len(stamp) == len("20261008T101530123456Z") and stamp.endswith("Z")
    assert stamp[:8].isdigit() and stamp[8] == "T"

    (step,) = report.remediation
    assert step == RemediationStep(
        action="quarantine",
        path="drop/new.txt",
        kind="created",
        ok=True,
        source=f"{TREE}/drop/new.txt",
        destination=f"{QUARANTINE}/{stamp}/drop/new.txt",
        error=None,
    )
    assert report.paths("created") == ["drop/new.txt"]
    assert report.to_dict()["remediation"][0]["ok"] is True

    violation, remediated = received
    assert isinstance(violation, IntegrityViolation)
    assert violation.payload["remediation"] == {"ok": 1, "failed": 0}
    assert isinstance(remediated, IntegrityRemediated)
    assert remediated.type == "integrity.remediated"
    assert (remediated.source, remediated.severity) == ("integrity", Severity.INFO)
    assert remediated.subject == f"integrity quarantine done: {TREE}/drop/new.txt"
    assert remediated.correlation_id == violation.correlation_id == report.correlation_id
    assert dict(remediated.payload) == {
        "action": "quarantine",
        "resource": f"{TREE}/drop/new.txt",
        "backend": "memory",
        "status": "ok",
        "path": "drop/new.txt",
        "kind": "created",
        "source": f"{TREE}/drop/new.txt",
        "destination": f"{QUARANTINE}/{stamp}/drop/new.txt",
        "error": None,
    }
    assert _monitor(bus, quarantine=QUARANTINE, on_created="quarantine").verify().ok is True


def test_a_modified_file_can_be_quarantined(tree: Storage, bus: EventBus) -> None:
    tree.file("a.txt").write(b"tampered")
    report = _monitor(bus, quarantine=QUARANTINE, on_modified="quarantine").verify()
    assert [(step.action, step.path, step.kind, step.ok) for step in report.remediation] == [
        ("quarantine", "a.txt", "modified", True)
    ]
    assert _quarantined() == {"a.txt": b"tampered"}
    assert tree.file("a.txt").exists() is False


def test_a_failed_quarantine_is_reported_and_leaves_the_file(
    tree: Storage, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.file("new.txt").write(b"novel")

    def _deny(*_args: object, **_options: object) -> None:
        raise StoragePermissionException("access to the quarantine was denied")

    monkeypatch.setattr(File, "move_to", _deny)
    report = _monitor(bus, quarantine=QUARANTINE, on_created="quarantine").verify()
    (step,) = report.remediation
    assert (step.ok, step.error) == (
        False,
        "StoragePermissionException: access to the quarantine was denied",
    )
    assert tree.file("new.txt").read() == b"novel"
    remediated = bus.recent(types=IntegrityRemediated)[0]
    assert (remediated.severity, remediated.payload["status"]) == (Severity.ERROR, "failed")
    assert bus.recent(types=IntegrityViolation)[0].payload["remediation"] == {"ok": 0, "failed": 1}


# ---------------------------------------------------------------------- restore


def test_a_deleted_file_is_restored_and_checked_against_the_baseline(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    tree.file("sub/c.txt").delete()
    monitor = _monitor(bus, restore_from=MIRROR, on_deleted="restore")
    report = monitor.verify()
    (step,) = report.remediation
    assert step == RemediationStep(
        action="restore",
        path="sub/c.txt",
        kind="deleted",
        ok=True,
        source=f"{MIRROR}/sub/c.txt",
        destination=f"{TREE}/sub/c.txt",
        error=None,
    )
    assert tree.file("sub/c.txt").read() == b"charlie"
    assert report.ok is False
    after = monitor.verify()
    assert after.counts["deleted"] == after.counts["modified"] == 0
    assert after.remediation == ()


def test_a_modified_file_is_set_aside_before_it_is_restored(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").write(b"tampered")
    report = _monitor(
        bus, quarantine=QUARANTINE, restore_from=MIRROR, on_modified="restore"
    ).verify()
    assert [(step.action, step.kind, step.ok) for step in report.remediation] == [
        ("quarantine", "modified", True),
        ("restore", "modified", True),
    ]
    assert tree.file("a.txt").read() == b"alpha"
    assert _quarantined() == {"a.txt": b"tampered"}
    assert [
        event.payload["action"] for event in reversed(bus.recent(types=IntegrityRemediated))
    ] == [
        "quarantine",
        "restore",
    ]


def test_without_a_quarantine_a_restore_overwrites_the_modified_file(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").write(b"tampered")
    report = _monitor(bus, restore_from=MIRROR, on_modified="restore").verify()
    assert [(step.action, step.ok) for step in report.remediation] == [("restore", True)]
    assert tree.file("a.txt").read() == b"alpha"


def test_a_restore_fails_when_the_mirror_has_no_copy(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    mirror.file("b.txt").delete()
    tree.file("b.txt").delete()
    report = _monitor(bus, restore_from=MIRROR, on_deleted="restore").verify()
    (step,) = report.remediation
    assert (step.action, step.path, step.ok) == ("restore", "b.txt", False)
    assert step.error == f"the mirror {MIRROR} has no copy of it"
    assert tree.file("b.txt").exists() is False
    remediated = bus.recent(types=IntegrityRemediated)[0]
    assert remediated.severity is Severity.ERROR
    assert remediated.subject == f"integrity restore failed: {TREE}/b.txt"
    assert (remediated.payload["status"], remediated.payload["error"]) == ("failed", step.error)
    assert report.to_dict()["remediation"][0]["error"] == step.error


def test_a_mirror_copy_that_differs_from_the_baseline_is_never_copied(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    mirror.file("a.txt").write(b"a stale or tampered mirror")
    tree.file("a.txt").write(b"tampered")
    report = _monitor(
        bus, quarantine=QUARANTINE, restore_from=MIRROR, on_modified="restore"
    ).verify()
    (step,) = report.remediation
    assert (step.action, step.ok) == ("restore", False)
    assert step.error == (
        "the mirror's copy does not match the baseline checksum; nothing was copied"
    )
    assert tree.file("a.txt").read() == b"tampered"
    assert _files(QUARANTINE) == {}


def test_a_restore_that_arrives_damaged_is_reported_as_failed(
    tree: Storage, mirror: Storage, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.file("b.txt").delete()

    def _corrupting_copy(_self: File, target: File, **_options: object) -> File:
        target.write(b"damaged in transit")
        return target

    monkeypatch.setattr(File, "copy_to", _corrupting_copy)
    report = _monitor(bus, restore_from=MIRROR, on_deleted="restore").verify()
    (step,) = report.remediation
    assert (step.ok, step.error) == (
        False,
        "the restored file does not match the baseline checksum",
    )


def test_a_restore_whose_copy_fails_is_reported_as_failed(
    tree: Storage, mirror: Storage, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.file("b.txt").delete()

    def _deny(*_args: object, **_options: object) -> None:
        raise StoragePermissionException("access to the target was denied")

    monkeypatch.setattr(File, "copy_to", _deny)
    report = _monitor(bus, restore_from=MIRROR, on_deleted="restore").verify()
    (step,) = report.remediation
    assert (step.ok, step.error) == (
        False,
        "StoragePermissionException: access to the target was denied",
    )
    assert tree.file("b.txt").exists() is False


def test_a_modified_file_that_cannot_be_set_aside_is_not_overwritten(
    tree: Storage, mirror: Storage, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.file("a.txt").write(b"tampered")

    def _deny(*_args: object, **_options: object) -> None:
        raise StoragePermissionException("access to the quarantine was denied")

    monkeypatch.setattr(File, "move_to", _deny)
    report = _monitor(
        bus, quarantine=QUARANTINE, restore_from=MIRROR, on_modified="restore"
    ).verify()
    quarantine, restore = report.remediation
    assert (quarantine.action, quarantine.ok) == ("quarantine", False)
    assert (restore.action, restore.ok) == ("restore", False)
    assert restore.error == "the modified file could not be quarantined, so it was left in place"
    assert tree.file("a.txt").read() == b"tampered"


def test_a_rename_is_remediated_as_its_two_halves(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").move_to(tree.file("renamed.txt"))
    report = _monitor(
        bus,
        quarantine=QUARANTINE,
        restore_from=MIRROR,
        on_created="quarantine",
        on_deleted="restore",
    ).verify()
    assert report.counts["renamed"] == 1
    assert [(step.action, step.path, step.kind, step.ok) for step in report.remediation] == [
        ("restore", "a.txt", "renamed", True),
        ("quarantine", "renamed.txt", "renamed", True),
    ]
    assert _files(TREE) == FILES
    assert _quarantined() == {"renamed.txt": b"alpha"}


def test_metadata_and_permission_changes_are_never_remediated(
    tree: Storage, mirror: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").write(b"alpha")
    report = _monitor(
        bus,
        quarantine=QUARANTINE,
        restore_from=MIRROR,
        on_created="quarantine",
        on_modified="restore",
        on_deleted="restore",
    ).verify()
    assert report.counts["metadata_changed"] == 1
    assert report.remediation == ()


def test_accept_reads_the_tree_again_after_a_verification_that_remediated(
    tree: Storage, bus: EventBus
) -> None:
    tree.file("a.txt").write(b"approved change")
    tree.file("new.txt").write(b"novel")
    monitor = _monitor(bus, quarantine=QUARANTINE, on_created="quarantine")
    report = monitor.verify()
    assert report.snapshot is not None and "new.txt" in report.snapshot
    accepted = monitor.accept(report)
    assert accepted.paths == ("a.txt", "b.txt", "sub/c.txt")
    assert monitor.verify().ok is True
