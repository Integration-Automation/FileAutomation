"""In-memory backend: a storage that lives in the process and needs no setup.

Meant for tests, dry runs and examples. ``memory://<name>/<path>`` addresses the
store called ``<name>``, created on first use and kept until the process exits or
:func:`clear_memory_stores` runs.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from automation_file.storage.backend import StorageBackend, parent_of
from automation_file.storage.types import FileInfo, StorageCapabilities

MEMORY_SCHEME = "memory"


@dataclass(frozen=True)
class _Blob:
    data: bytes
    modified_at: datetime


class MemoryStorage(StorageBackend):
    """A thread-safe tree of files and directories held in memory."""

    scheme = MEMORY_SCHEME
    capabilities = StorageCapabilities(directories=True, modified_at=True)

    def __init__(self, name: str = "") -> None:
        self._name = name
        self._lock = threading.RLock()
        self._files: dict[str, _Blob] = {}
        self._directories: set[str] = set()

    @property
    def name(self) -> str:
        """The store name, which is the authority of its ``memory://`` URIs."""
        return self._name

    def uri_for(self, path: str = "") -> str:
        clean = self._normalize(path)
        root = f"{MEMORY_SCHEME}://{self._name}"
        return f"{root}/{clean}" if clean or not self._name else root

    def __repr__(self) -> str:
        return f"MemoryStorage({self._name!r})"

    def _stat(self, path: str) -> FileInfo | None:
        with self._lock:
            blob = self._files.get(path)
            if blob is not None:
                return FileInfo(path=path, size=len(blob.data), modified_at=blob.modified_at)
            if not path or path in self._directories:
                return FileInfo(path=path, is_dir=True)
            return None

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        with self._lock:
            names = [name for name in (*self._directories, *self._files) if parent_of(name) == path]
            return [info for info in map(self._stat, names) if info is not None]

    def _upload(self, source: Path, path: str) -> None:
        blob = _Blob(source.read_bytes(), datetime.now(timezone.utc))
        with self._lock:
            self._files[path] = blob

    def _download(self, path: str, target: Path) -> None:
        target.write_bytes(self._read_bytes(path))

    def _read_bytes(self, path: str) -> bytes:
        with self._lock:
            return self._files[path].data

    def _delete_file(self, path: str) -> None:
        with self._lock:
            del self._files[path]

    def _mkdir(self, path: str) -> None:
        with self._lock:
            self._directories.add(path)

    def _rmdir(self, path: str) -> None:
        with self._lock:
            self._directories.discard(path)


_stores: dict[str, MemoryStorage] = {}
_stores_lock = threading.Lock()


def memory_store(name: str = "") -> MemoryStorage:
    """Return the shared in-memory store called ``name``, creating it on first use."""
    with _stores_lock:
        store = _stores.get(name)
        if store is None:
            store = _stores[name] = MemoryStorage(name)
        return store


def clear_memory_stores() -> None:
    """Forget every shared in-memory store and what it holds."""
    with _stores_lock:
        _stores.clear()
