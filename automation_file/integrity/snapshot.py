"""Snapshot: what a directory tree holds at one moment.

A :class:`Snapshot` lists every file below a target with its size, modification
time, checksum and whatever else the backend reports. It is frozen and turns
into a JSON-friendly dictionary with ``to_dict``; ``from_dict`` reads it back
and rejects anything that is not a well-formed entry.

:func:`build_snapshot` produces one through the storage layer, so it works on
any backend. Directories are not recorded: an empty directory is invisible.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from automation_file.exceptions import FileNotExistsException, StorageURIException
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.hashing import DEFAULT_ALGORITHM, HashEngine
from automation_file.integrity.target import Target
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import normalize_path

# The character that sorts right after "/": every path below "a/" lies in ["a/", "a0").
_AFTER_SEPARATOR = chr(ord("/") + 1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(moment: datetime | None) -> datetime | None:
    """Return ``moment`` as an aware UTC time; a naive one is taken to be UTC already."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_timestamp(value: object, name: str) -> datetime | None:
    """Read an ISO 8601 timestamp written by ``to_dict``; ``None`` stays ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntegrityException(f"{name} must be an ISO 8601 timestamp, got {value!r}")
    text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        return as_utc(datetime.fromisoformat(text))
    except ValueError as error:
        raise IntegrityException(f"{name} is not an ISO 8601 timestamp: {value!r}") from error


def _text(data: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    value = data.get(key, default)
    if value is None or isinstance(value, str):
        return value
    raise IntegrityException(f"snapshot entry field {key!r} must be text, got {value!r}")


def _count(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IntegrityException(
            f"snapshot entry field {key!r} must be a non-negative integer, got {value!r}"
        )
    return value


def _entry_path(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityException(f"snapshot entry has no usable 'path': {value!r}")
    try:
        clean = normalize_path(value)
    except StorageURIException as error:
        raise IntegrityException(f"snapshot entry path {value!r} is not valid: {error}") from error
    if not clean:
        raise IntegrityException("snapshot entry has an empty 'path'")
    return clean


@dataclass(frozen=True)
class SnapshotEntry:
    """One file of a snapshot. Fields a backend cannot provide are ``None``.

    ``mode`` holds the permission bits and is recorded only for a local file.
    """

    path: str
    size: int | None = None
    modified_at: datetime | None = None
    checksum: str = ""
    algorithm: str = DEFAULT_ALGORITHM
    content_type: str | None = None
    backend: str = ""
    version: str | None = None
    etag: str | None = None
    mode: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping; ``modified_at`` becomes ISO 8601."""
        return {
            "path": self.path,
            "size": self.size,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "checksum": self.checksum,
            "algorithm": self.algorithm,
            "content_type": self.content_type,
            "backend": self.backend,
            "version": self.version,
            "etag": self.etag,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(
        cls, data: Any, *, algorithm: str = DEFAULT_ALGORITHM, backend: str = ""
    ) -> SnapshotEntry:
        """Build an entry from ``to_dict`` output; ``algorithm`` and ``backend`` fill gaps."""
        if not isinstance(data, Mapping):
            raise IntegrityException(f"snapshot entry must be an object, got {data!r}")
        return cls(
            path=_entry_path(data.get("path")),
            size=_count(data, "size"),
            modified_at=parse_timestamp(data.get("modified_at"), "snapshot entry 'modified_at'"),
            checksum=(_text(data, "checksum") or "").strip().lower(),
            algorithm=_text(data, "algorithm") or algorithm,
            content_type=_text(data, "content_type"),
            backend=_text(data, "backend") or backend,
            version=_text(data, "version"),
            etag=_text(data, "etag"),
            mode=_count(data, "mode"),
        )


def _by_path(entry: SnapshotEntry) -> str:
    return entry.path


@dataclass(frozen=True)
class Snapshot:
    """Every file below ``root`` (a storage URI) at ``created_at``, sorted by path."""

    root: str
    backend: str = ""
    algorithm: str = DEFAULT_ALGORITHM
    created_at: datetime = field(default_factory=_now)
    entries: tuple[SnapshotEntry, ...] = ()
    _index: Mapping[str, SnapshotEntry] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.entries, key=_by_path))
        index = {entry.path: entry for entry in ordered}
        if len(index) != len(ordered):
            raise IntegrityException(f"a snapshot of {self.root} lists a path more than once")
        object.__setattr__(self, "entries", ordered)
        object.__setattr__(self, "_index", index)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(self._index)

    def get(self, path: str) -> SnapshotEntry | None:
        """Return the entry at ``path``, or ``None``."""
        return self._index.get(path)

    def below(self, path: str) -> tuple[SnapshotEntry, ...]:
        """Return the entry at ``path`` and every entry under it as a directory."""
        if not path:
            return self.entries
        start = bisect_left(self.entries, f"{path}/", key=_by_path)
        end = bisect_left(self.entries, f"{path}{_AFTER_SEPARATOR}", key=_by_path)
        exact = self._index.get(path)
        return (*((exact,) if exact is not None else ()), *self.entries[start:end])

    def merged(
        self, *, removed: Iterable[str], added: Iterable[SnapshotEntry], root: str, backend: str
    ) -> Snapshot:
        """Return a new snapshot of ``root`` without ``removed`` and with ``added`` on top."""
        dropped = set(removed)
        kept = {entry.path: entry for entry in self.entries if entry.path not in dropped}
        kept.update((entry.path, entry) for entry in added)
        return Snapshot(
            root=root, backend=backend, algorithm=self.algorithm, entries=tuple(kept.values())
        )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[SnapshotEntry]:
        return iter(self.entries)

    def __contains__(self, path: object) -> bool:
        return path in self._index

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the snapshot."""
        return {
            "created_at": self.created_at.isoformat(),
            "root": self.root,
            "backend": self.backend,
            "algorithm": self.algorithm,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Snapshot:
        """Build a snapshot from ``to_dict`` output."""
        if not isinstance(data, Mapping):
            raise IntegrityException(f"a snapshot must be an object, got {data!r}")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise IntegrityException("a snapshot needs an 'entries' list")
        algorithm = _text(data, "algorithm") or DEFAULT_ALGORITHM
        backend = _text(data, "backend") or ""
        return cls(
            root=_text(data, "root") or "",
            backend=backend,
            algorithm=algorithm,
            created_at=parse_timestamp(data.get("created_at"), "snapshot 'created_at'") or _now(),
            entries=tuple(
                SnapshotEntry.from_dict(entry, algorithm=algorithm, backend=backend)
                for entry in entries
            ),
        )


def quick_matches(infos: Iterable[FileInfo], baseline: Snapshot) -> dict[str, SnapshotEntry]:
    """Return the baseline entries a quick pass takes on trust, by path.

    A file is trusted when its size, modification time and etag are the ones the
    baseline recorded. An entry that recorded neither a time nor an etag gives
    nothing to compare beyond the size, so its file is hashed.
    """
    trusted: dict[str, SnapshotEntry] = {}
    for info in infos:
        known = baseline.get(info.path)
        if known is not None and _same_stamp(info, known):
            trusted[info.path] = known
    return trusted


def _same_stamp(info: FileInfo, known: SnapshotEntry) -> bool:
    if known.size is None or info.size != known.size:
        return False
    if known.modified_at is None and known.etag is None:
        return False
    return as_utc(info.modified_at) == known.modified_at and info.etag == known.etag


def _detailed(target: Target, capabilities: StorageCapabilities, info: FileInfo) -> FileInfo | None:
    """Add what a listing leaves out (version, content type); ``None`` when the file is gone."""
    lacks_version = capabilities.version and info.version is None
    lacks_type = capabilities.content_type and info.content_type is None
    if not (lacks_version or lacks_type):
        return info
    try:
        detail = target.storage.stat(info.path)
    except FileNotExistsException:
        return None
    return replace(
        info,
        version=info.version or detail.version,
        content_type=info.content_type or detail.content_type,
    )


def build_snapshot(
    target: Target,
    engine: HashEngine,
    infos: Sequence[FileInfo],
    *,
    known: Mapping[str, SnapshotEntry] | None = None,
) -> Snapshot:
    """Return the snapshot of the files ``infos`` of ``target``.

    A path in ``known`` keeps the checksum of its entry there instead of being
    hashed; that is how a quick pass skips the files it trusts. A file that
    vanishes while the snapshot is taken is left out.
    """
    trusted = known or {}
    served_by = target.backend
    backend, capabilities = served_by.scheme, served_by.capabilities
    read_mode = target.mode_reader()

    def describe(info: FileInfo) -> SnapshotEntry | None:
        carried = trusted.get(info.path)
        if carried is not None:
            digest: str | None = carried.checksum
            detail: FileInfo | None = replace(
                info,
                version=info.version or carried.version,
                content_type=info.content_type or carried.content_type,
            )
        else:
            digest = engine.hash_file(target.storage, info.path)
            detail = _detailed(target, capabilities, info) if digest is not None else None
        if digest is None or detail is None:
            return None
        return SnapshotEntry(
            path=info.path,
            size=detail.size,
            modified_at=as_utc(detail.modified_at),
            checksum=digest,
            algorithm=engine.algorithm,
            content_type=detail.content_type,
            backend=backend,
            version=detail.version,
            etag=detail.etag,
            mode=read_mode(info.path),
        )

    by_path = {info.path: info for info in infos}
    described = engine.map(lambda path: describe(by_path[path]), by_path)
    return Snapshot(
        root=str(target.uri),
        backend=backend,
        algorithm=engine.algorithm,
        entries=tuple(entry for entry in described.values() if entry is not None),
    )
