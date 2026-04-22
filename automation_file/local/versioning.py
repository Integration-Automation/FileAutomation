"""Simple file versioning store.

:class:`FileVersioner` keeps numbered snapshots of files under a versions
directory. Callers snapshot a file before mutating it, list prior versions,
restore one, or prune to keep only the most recent ``keep`` copies.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from automation_file.exceptions import VersioningException

_VERSION_RE = re.compile(r"^v(\d+)__(\d+)$")


@dataclass(frozen=True)
class VersionEntry:
    """One snapshot returned by :meth:`FileVersioner.list_versions`."""

    version: int
    timestamp: float
    path: Path


class FileVersioner:
    """Store numbered snapshots beneath ``root``.

    Each source file is versioned in its own subdirectory so multiple files
    can coexist. The subdirectory name is the source path's POSIX form with
    path separators replaced by ``__sep__`` to flatten safely.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def save_version(self, path: str | os.PathLike[str]) -> VersionEntry:
        """Snapshot the file at ``path`` and return the new entry."""
        src = Path(path)
        if not src.is_file():
            raise VersioningException(f"source is not a file: {src}")
        bucket = self._bucket_for(src)
        bucket.mkdir(parents=True, exist_ok=True)
        next_version = self._next_version(bucket)
        timestamp_ns = time.time_ns()
        target = bucket / f"v{next_version:06d}__{timestamp_ns}"
        shutil.copy2(src, target)
        return VersionEntry(version=next_version, timestamp=timestamp_ns / 1e9, path=target)

    def list_versions(self, path: str | os.PathLike[str]) -> list[VersionEntry]:
        """Return every recorded snapshot of ``path``, oldest first."""
        bucket = self._bucket_for(Path(path))
        if not bucket.is_dir():
            return []
        entries: list[VersionEntry] = []
        for child in bucket.iterdir():
            if not child.is_file():
                continue
            match = _VERSION_RE.match(child.name)
            if not match:
                continue
            version = int(match.group(1))
            timestamp = int(match.group(2)) / 1e9
            entries.append(VersionEntry(version=version, timestamp=timestamp, path=child))
        entries.sort(key=lambda entry: entry.version)
        return entries

    def restore(self, path: str | os.PathLike[str], version: int) -> None:
        """Restore ``path`` from the snapshot with the given version number."""
        for entry in self.list_versions(path):
            if entry.version == version:
                shutil.copy2(entry.path, path)
                return
        raise VersioningException(f"no version {version} for {path}")

    def prune(self, path: str | os.PathLike[str], keep: int) -> int:
        """Keep only the ``keep`` most recent versions; return rows deleted."""
        if keep < 0:
            raise VersioningException("keep must be >= 0")
        entries = self.list_versions(path)
        if len(entries) <= keep:
            return 0
        victims = entries[: len(entries) - keep]
        for entry in victims:
            entry.path.unlink(missing_ok=True)
        return len(victims)

    def _bucket_for(self, src: Path) -> Path:
        safe = _flatten_path(src)
        return self._root / safe

    def _next_version(self, bucket: Path) -> int:
        highest = 0
        for child in bucket.iterdir():
            match = _VERSION_RE.match(child.name)
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1


def _flatten_path(src: Path) -> str:
    # Resolve to absolute, strip drive letter on Windows, collapse separators.
    resolved = src.resolve()
    drive, body = os.path.splitdrive(resolved)
    flat = (drive.replace(":", "") + body).replace(os.sep, "__sep__")
    flat = flat.replace("/", "__sep__")
    return flat.strip("_") or "root"
