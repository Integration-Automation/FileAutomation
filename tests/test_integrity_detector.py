"""The change detector and the drift report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from automation_file.integrity import (
    Change,
    ChangeKind,
    DriftReport,
    IntegrityException,
    RemediationStep,
    Snapshot,
    SnapshotEntry,
    detect_changes,
)

ROOT = "memory://detect/tree"
MOMENT = datetime(2026, 10, 8, 10, 15, 30, tzinfo=timezone.utc)
LATER = MOMENT + timedelta(hours=1)


def _entry(path: str, checksum: str = "aa", size: int | None = 5, **fields: Any) -> SnapshotEntry:
    return SnapshotEntry(path=path, checksum=checksum, size=size, **fields)


def _snapshot(*entries: SnapshotEntry, algorithm: str = "sha256") -> Snapshot:
    return Snapshot(root=ROOT, algorithm=algorithm, entries=entries)


def _kinds(changes: list[Change]) -> list[tuple[str, str]]:
    return [(change.kind.value, change.path) for change in changes]


def test_identical_snapshots_have_no_changes() -> None:
    entries = (_entry("a.txt", modified_at=MOMENT, mode=0o644), _entry("b.txt", "bb"))
    assert detect_changes(_snapshot(*entries), _snapshot(*entries)) == []
    assert detect_changes(_snapshot(), _snapshot()) == []


def test_created() -> None:
    new = _entry("new.txt", "nn")
    (change,) = detect_changes(_snapshot(_entry("a.txt")), _snapshot(_entry("a.txt"), new))
    assert (change.kind, change.path) == (ChangeKind.CREATED, "new.txt")
    assert (change.before, change.after, change.previous_path, change.note) == (
        None,
        new,
        None,
        "",
    )


def test_deleted() -> None:
    gone = _entry("gone.txt", "gg")
    (change,) = detect_changes(_snapshot(_entry("a.txt"), gone), _snapshot(_entry("a.txt")))
    assert (change.kind, change.path) == (ChangeKind.DELETED, "gone.txt")
    assert (change.before, change.after) == (gone, None)


def test_modified_when_the_checksum_differs() -> None:
    before = _entry("a.txt", "aa", modified_at=MOMENT)
    after = _entry("a.txt", "zz", size=9, modified_at=LATER)
    (change,) = detect_changes(_snapshot(before), _snapshot(after))
    assert (change.kind, change.path) == (ChangeKind.MODIFIED, "a.txt")
    assert (change.before, change.after) == (before, after)
    assert change.fields == ()


def test_a_size_that_differs_is_modified_even_with_the_same_checksum() -> None:
    changes = detect_changes(_snapshot(_entry("a.txt", size=5)), _snapshot(_entry("a.txt", size=6)))
    assert _kinds(changes) == [("modified", "a.txt")]
    unknown = detect_changes(
        _snapshot(_entry("a.txt", size=None)), _snapshot(_entry("a.txt", size=6))
    )
    assert unknown == []


def test_renamed_when_one_deleted_and_one_created_file_share_the_content() -> None:
    old, new = _entry("old/name.txt", "rr", size=7), _entry("new/name.txt", "rr", size=7)
    (change,) = detect_changes(
        _snapshot(old, _entry("keep.txt")), _snapshot(new, _entry("keep.txt"))
    )
    assert change.kind is ChangeKind.RENAMED
    assert (change.path, change.previous_path) == ("new/name.txt", "old/name.txt")
    assert (change.before, change.after, change.note) == (old, new, "")


def test_the_same_checksum_with_another_size_is_not_a_rename() -> None:
    changes = detect_changes(
        _snapshot(_entry("old.txt", "rr", size=7)), _snapshot(_entry("new.txt", "rr", size=8))
    )
    assert _kinds(changes) == [("created", "new.txt"), ("deleted", "old.txt")]
    assert [change.note for change in changes] == ["", ""]


def test_an_ambiguous_rename_falls_back_to_created_and_deleted_and_says_so() -> None:
    baseline = _snapshot(
        _entry("one.txt", "dddddddddddddddddd"), _entry("two.txt", "dddddddddddddddddd")
    )
    current = _snapshot(_entry("three.txt", "dddddddddddddddddd"))
    changes = detect_changes(baseline, current)
    assert _kinds(changes) == [
        ("deleted", "one.txt"),
        ("created", "three.txt"),
        ("deleted", "two.txt"),
    ]
    notes = {change.note for change in changes}
    assert notes == {
        "ambiguous rename: 2 deleted and 1 created files share the checksum dddddddddddd...; "
        "reported separately"
    }


def test_one_deleted_file_and_two_copies_of_it_is_ambiguous_too() -> None:
    changes = detect_changes(
        _snapshot(_entry("orig.txt", "cc")),
        _snapshot(_entry("copy1.txt", "cc"), _entry("copy2.txt", "cc")),
    )
    assert _kinds(changes) == [
        ("created", "copy1.txt"),
        ("created", "copy2.txt"),
        ("deleted", "orig.txt"),
    ]
    assert all(
        change.note.startswith("ambiguous rename: 1 deleted and 2 created") for change in changes
    )


def test_entries_without_a_checksum_are_never_paired() -> None:
    changes = detect_changes(
        _snapshot(_entry("old.txt", "", size=None)), _snapshot(_entry("new.txt", "", size=None))
    )
    assert _kinds(changes) == [("created", "new.txt"), ("deleted", "old.txt")]
    assert [change.note for change in changes] == ["", ""]


def test_metadata_changed_when_only_other_metadata_differs() -> None:
    before = _entry("a.txt", modified_at=MOMENT, content_type="text/plain", version="v1", etag="e1")
    after = _entry("a.txt", modified_at=LATER, content_type="text/plain", version="v2", etag="e1")
    (change,) = detect_changes(_snapshot(before), _snapshot(after))
    assert change.kind is ChangeKind.METADATA_CHANGED
    assert change.fields == ("modified_at", "version")
    assert (change.before, change.after) == (before, after)


def test_metadata_one_side_did_not_record_is_not_compared() -> None:
    before = _entry("a.txt")
    after = _entry("a.txt", modified_at=LATER, content_type="text/plain", version="v2", etag="e9")
    assert detect_changes(_snapshot(before), _snapshot(after)) == []
    assert detect_changes(_snapshot(after), _snapshot(before)) == []


def test_permission_changed_when_the_mode_differs() -> None:
    before, after = _entry("run.sh", mode=0o644), _entry("run.sh", mode=0o755)
    (change,) = detect_changes(_snapshot(before), _snapshot(after))
    assert change.kind is ChangeKind.PERMISSION_CHANGED
    assert change.fields == ("mode",)
    assert detect_changes(_snapshot(_entry("run.sh")), _snapshot(after)) == []


def test_a_file_can_be_modified_and_have_its_permissions_changed() -> None:
    changes = detect_changes(
        _snapshot(_entry("run.sh", "aa", mode=0o644, modified_at=MOMENT)),
        _snapshot(_entry("run.sh", "bb", mode=0o4755, modified_at=LATER)),
    )
    assert _kinds(changes) == [("modified", "run.sh"), ("permission_changed", "run.sh")]


def test_changes_are_sorted_by_path() -> None:
    baseline = _snapshot(_entry("b.txt", "bb"), _entry("d.txt", "dd"), _entry("m.txt", "mm"))
    current = _snapshot(_entry("a.txt", "new"), _entry("b.txt", "changed"), _entry("m.txt", "mm"))
    assert _kinds(detect_changes(baseline, current)) == [
        ("created", "a.txt"),
        ("modified", "b.txt"),
        ("deleted", "d.txt"),
    ]


def test_snapshots_of_two_algorithms_cannot_be_compared() -> None:
    with pytest.raises(IntegrityException, match="sha256 snapshot with a sha512 one"):
        detect_changes(_snapshot(), _snapshot(algorithm="sha512"))


def test_the_kinds() -> None:
    assert [kind.value for kind in ChangeKind] == [
        "created",
        "modified",
        "deleted",
        "renamed",
        "metadata_changed",
        "permission_changed",
    ]


# ---------------------------------------------------------------------- report


def _report() -> DriftReport:
    baseline = _snapshot(
        _entry("a.txt", "aa"),
        _entry("gone.txt", "gg"),
        _entry("old.txt", "rr"),
        _entry("meta.txt", "mm", modified_at=MOMENT),
    )
    current = _snapshot(
        _entry("a.txt", "zz"),
        _entry("new.txt", "nn"),
        _entry("renamed.txt", "rr"),
        _entry("meta.txt", "mm", modified_at=LATER),
    )
    return DriftReport(
        target=ROOT,
        baseline="memory://detect/baseline.json",
        backend="memory",
        changes=tuple(detect_changes(baseline, current)),
        checked=4,
        hashed=4,
        verified_at=MOMENT,
        correlation_id="run-1",
        snapshot=current,
    )


def test_a_report_counts_every_kind() -> None:
    report = _report()
    assert report.ok is False
    assert report.counts == {
        "created": 1,
        "modified": 1,
        "deleted": 1,
        "renamed": 1,
        "metadata_changed": 1,
        "permission_changed": 0,
    }
    assert report.paths("modified") == ["a.txt"]
    assert report.paths(ChangeKind.RENAMED) == ["renamed.txt"]
    assert report.paths("permission_changed") == []


def test_a_clean_report_is_ok() -> None:
    report = DriftReport(target=ROOT)
    assert report.ok is True
    assert set(report.counts.values()) == {0}
    assert (report.deep, report.partial, report.notes, report.remediation) == (True, False, (), ())
    assert report.verified_at.utcoffset() == timedelta(0)


def test_a_report_is_json_friendly() -> None:
    step = RemediationStep(
        action="restore", path="gone.txt", kind="deleted", ok=False, error="no copy"
    )
    report = DriftReport(
        target=ROOT,
        changes=_report().changes,
        deep=False,
        notes=("quick pass",),
        remediation=(step,),
        verified_at=MOMENT,
    )
    document = json.loads(json.dumps(report.to_dict()))
    assert list(document) == [
        "target",
        "baseline",
        "backend",
        "algorithm",
        "ok",
        "deep",
        "partial",
        "checked",
        "hashed",
        "counts",
        "changes",
        "notes",
        "remediation",
        "verified_at",
        "correlation_id",
    ]
    assert (document["ok"], document["deep"], document["notes"]) == (False, False, ["quick pass"])
    assert document["verified_at"] == "2026-10-08T10:15:30+00:00"
    assert document["remediation"] == [
        {
            "action": "restore",
            "path": "gone.txt",
            "kind": "deleted",
            "ok": False,
            "source": "",
            "destination": "",
            "error": "no copy",
        }
    ]
    renamed = next(change for change in document["changes"] if change["kind"] == "renamed")
    assert (renamed["path"], renamed["previous_path"]) == ("renamed.txt", "old.txt")
    assert renamed["before"]["path"] == "old.txt"
    assert renamed["after"]["checksum"] == "rr"
    created = next(change for change in document["changes"] if change["kind"] == "created")
    assert (created["before"], created["previous_path"], created["fields"]) == (None, None, [])


def test_the_brief_form_of_a_change_leaves_out_what_is_empty() -> None:
    changes = {change.kind: change for change in _report().changes}
    assert changes[ChangeKind.MODIFIED].brief() == {"kind": "modified", "path": "a.txt"}
    assert changes[ChangeKind.RENAMED].brief() == {
        "kind": "renamed",
        "path": "renamed.txt",
        "previous_path": "old.txt",
    }
    assert changes[ChangeKind.METADATA_CHANGED].brief() == {
        "kind": "metadata_changed",
        "path": "meta.txt",
        "fields": ["modified_at"],
    }
    noted = Change(ChangeKind.CREATED, "x.txt", note="ambiguous rename")
    assert noted.brief() == {"kind": "created", "path": "x.txt", "note": "ambiguous rename"}
