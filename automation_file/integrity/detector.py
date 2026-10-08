"""Change Detector: what differs between two snapshots of one tree.

Six kinds of change are told apart:

``created``
    A path the baseline does not have.
``modified``
    The checksum (or the recorded size) differs.
``deleted``
    A path of the baseline that is gone.
``renamed``
    One deleted and one created file with the same checksum and size. When
    several deleted or several created files share that content the pairing is
    ambiguous: they are reported as ``deleted`` and ``created`` with a note
    that says so.
``metadata_changed``
    Same checksum, but the modification time, content type, version or etag
    differs. A field one side did not record is not compared.
``permission_changed``
    The permission bits differ. It is reported next to ``modified`` when both
    happened.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.snapshot import Snapshot, SnapshotEntry

_METADATA_FIELDS = ("modified_at", "content_type", "version", "etag")
_DIGEST_PREVIEW = 12
_ContentKey = tuple[str, int | None, str]


class ChangeKind(str, Enum):
    """The kinds of drift the detector reports."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    METADATA_CHANGED = "metadata_changed"
    PERMISSION_CHANGED = "permission_changed"


_KIND_ORDER = tuple(ChangeKind)


@dataclass(frozen=True)
class Change:
    """One difference. ``before`` is the baseline's entry, ``after`` the current one.

    ``previous_path`` is set for a rename, ``fields`` names the metadata that
    differs, and ``note`` carries a remark such as an ambiguous rename.
    """

    kind: ChangeKind
    path: str
    previous_path: str | None = None
    before: SnapshotEntry | None = None
    after: SnapshotEntry | None = None
    fields: tuple[str, ...] = ()
    note: str = ""

    def brief(self) -> dict[str, Any]:
        """Return the change without its two entries, for an event payload or a log line."""
        summary: dict[str, Any] = {"kind": self.kind.value, "path": self.path}
        if self.previous_path is not None:
            summary["previous_path"] = self.previous_path
        if self.fields:
            summary["fields"] = list(self.fields)
        if self.note:
            summary["note"] = self.note
        return summary

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the change with both entries."""
        return {
            "kind": self.kind.value,
            "path": self.path,
            "previous_path": self.previous_path,
            "fields": list(self.fields),
            "note": self.note,
            "before": self.before.to_dict() if self.before else None,
            "after": self.after.to_dict() if self.after else None,
        }


def _content_differs(before: SnapshotEntry, after: SnapshotEntry) -> bool:
    if before.checksum != after.checksum:
        return True
    return before.size is not None and after.size is not None and before.size != after.size


def _metadata_differences(before: SnapshotEntry, after: SnapshotEntry) -> tuple[str, ...]:
    differing: list[str] = []
    for name in _METADATA_FIELDS:
        old, new = getattr(before, name), getattr(after, name)
        if old is not None and new is not None and old != new:
            differing.append(name)
    return tuple(differing)


def _compare(before: SnapshotEntry, after: SnapshotEntry) -> list[Change]:
    """Return what changed in a file that both snapshots hold."""
    changes: list[Change] = []
    if _content_differs(before, after):
        changes.append(Change(ChangeKind.MODIFIED, after.path, before=before, after=after))
    else:
        fields = _metadata_differences(before, after)
        if fields:
            changes.append(
                Change(
                    ChangeKind.METADATA_CHANGED,
                    after.path,
                    before=before,
                    after=after,
                    fields=fields,
                )
            )
    if before.mode is not None and after.mode is not None and before.mode != after.mode:
        changes.append(
            Change(
                ChangeKind.PERMISSION_CHANGED,
                after.path,
                before=before,
                after=after,
                fields=("mode",),
            )
        )
    return changes


def _content_key(entry: SnapshotEntry) -> _ContentKey:
    # An entry without a checksum can be paired with nothing, so its key is its own.
    return entry.checksum, entry.size, "" if entry.checksum else entry.path


def _by_content(entries: Iterable[SnapshotEntry]) -> dict[_ContentKey, list[SnapshotEntry]]:
    grouped: dict[_ContentKey, list[SnapshotEntry]] = {}
    for entry in entries:
        grouped.setdefault(_content_key(entry), []).append(entry)
    return grouped


def _pair(gone: list[SnapshotEntry], new: list[SnapshotEntry]) -> list[Change]:
    """Turn files of one content that left and arrived into a rename, or into its two halves."""
    if len(gone) == 1 and len(new) == 1:
        return [
            Change(
                ChangeKind.RENAMED,
                new[0].path,
                previous_path=gone[0].path,
                before=gone[0],
                after=new[0],
            )
        ]
    note = ""
    if gone and new:
        note = (
            f"ambiguous rename: {len(gone)} deleted and {len(new)} created files share the "
            f"checksum {gone[0].checksum[:_DIGEST_PREVIEW]}...; reported separately"
        )
    return [
        *(Change(ChangeKind.DELETED, entry.path, before=entry, note=note) for entry in gone),
        *(Change(ChangeKind.CREATED, entry.path, after=entry, note=note) for entry in new),
    ]


def _order(change: Change) -> tuple[str, int]:
    return change.path, _KIND_ORDER.index(change.kind)


def detect_changes(baseline: Snapshot, current: Snapshot) -> list[Change]:
    """Return the changes that turn ``baseline`` into ``current``, sorted by path."""
    if baseline.algorithm != current.algorithm:
        raise IntegrityException(
            f"cannot compare a {baseline.algorithm} snapshot with a {current.algorithm} one: "
            "hash the current tree with the baseline's algorithm"
        )
    changes: list[Change] = []
    for before in baseline:
        after = current.get(before.path)
        if after is not None:
            changes.extend(_compare(before, after))
    gone = _by_content(entry for entry in baseline if entry.path not in current)
    new = _by_content(entry for entry in current if entry.path not in baseline)
    for key, entries in gone.items():
        changes.extend(_pair(entries, new.pop(key, [])))
    for entries in new.values():
        changes.extend(_pair([], entries))
    return sorted(changes, key=_order)
