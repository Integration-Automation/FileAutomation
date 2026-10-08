"""Shared behaviour of object stores: flat keys, where a directory is only a key prefix.

:class:`ObjectStorage` turns the :class:`StorageBackend` primitives into five
calls on a key/value store -- ``_head``, ``_scan``, ``_put``, ``_get`` and
``_remove`` -- so an adapter for S3, Azure Blob or a similar service is a thin
translation of those calls and of the service's errors.

* A directory exists while a key lies below it; ``mkdir`` creates nothing.
* A key that ends with ``/`` is a placeholder some tools write to make an empty
  "folder" visible. It is never listed as a file, and deleting the directory
  removes it too.
* ``prefix`` confines the backend to the keys below one prefix of the container.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Hashable, Iterable
from dataclasses import replace
from pathlib import Path

from automation_file.exceptions import StorageNotFoundException
from automation_file.storage.backend import StorageBackend, join_path, not_empty_error, parent_of
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import normalize_path

_PLACEHOLDER_SUFFIX = "/"


def implied_directories(paths: Iterable[str], base: str) -> list[FileInfo]:
    """Return the directories that lie between ``base`` and each of ``paths``."""
    found: set[str] = set()
    for path in paths:
        parent = parent_of(path)
        while parent != base and parent not in found:
            found.add(parent)
            parent = parent_of(parent)
    return [FileInfo(path=directory, is_dir=True) for directory in sorted(found)]


class ObjectStorage(StorageBackend):
    """A :class:`StorageBackend` over a flat key space."""

    capabilities = StorageCapabilities(directories=False)

    def __init__(self, prefix: str = "") -> None:
        self._prefix = normalize_path(prefix)

    @property
    def prefix(self) -> str:
        """The key prefix this backend is confined to (empty for the whole container)."""
        return self._prefix

    # ------------------------------------------------------------------ the key/value store

    @abstractmethod
    def _head(self, key: str) -> FileInfo | None:
        """Return the object at exactly ``key`` (``FileInfo.path`` is free), or ``None``."""

    @abstractmethod
    def _scan(self, key_prefix: str, *, shallow: bool) -> Iterable[FileInfo]:
        """Yield the objects whose key starts with ``key_prefix``; ``FileInfo.path`` is the key.

        With ``shallow=True`` only one level is returned: the objects directly below
        the prefix, and one ``FileInfo(is_dir=True)`` per deeper prefix, its path
        without the trailing ``/``.
        """

    @abstractmethod
    def _put(self, source: Path, key: str) -> None:
        """Store the local file ``source`` as the object ``key``."""

    @abstractmethod
    def _get(self, key: str, target: Path) -> None:
        """Write the object ``key`` to the local file ``target``."""

    @abstractmethod
    def _remove(self, key: str) -> None:
        """Delete the object ``key``."""

    # ------------------------------------------------------------------ StorageBackend primitives

    def _store_identity(self) -> Hashable:
        """Identify the container behind this backend, the same for every prefix of it."""
        return id(self)

    def _identity(self, path: str) -> Hashable:
        return (self._store_identity(), self._key(path))

    def _key(self, path: str) -> str:
        return join_path(self._prefix, path) if path else self._prefix

    def _below(self, path: str) -> str:
        key = self._key(path)
        return f"{key}/" if key else ""

    def _visible(self, info: FileInfo) -> FileInfo:
        """Re-express a key as a path relative to this backend's prefix."""
        return replace(info, path=info.path[len(self._prefix) + 1 :]) if self._prefix else info

    def _stat(self, path: str) -> FileInfo | None:
        if not path:
            return FileInfo(path="", is_dir=True)
        info = self._head(self._key(path))
        if info is not None:
            return replace(info, path=path, is_dir=False)
        try:
            has_entries = any(True for _ in self._scan(self._below(path), shallow=True))
        except StorageNotFoundException:
            # The container itself is missing, so nothing exists inside it.
            return None
        return FileInfo(path=path, is_dir=True) if has_entries else None

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        return [
            self._visible(info)
            for info in self._scan(self._below(path), shallow=True)
            if not info.path.endswith(_PLACEHOLDER_SUFFIX)
        ]

    def _walk(self, path: str) -> Iterable[FileInfo]:
        entries = [self._visible(info) for info in self._scan(self._below(path), shallow=False)]
        files = [info for info in entries if not info.path.endswith(_PLACEHOLDER_SUFFIX)]
        # A placeholder's parent is the directory it marks, so it implies that directory too.
        return [*implied_directories((info.path for info in entries), path), *files]

    def _upload(self, source: Path, path: str) -> None:
        self._put(source, self._key(path))

    def _download(self, path: str, target: Path) -> None:
        self._get(self._key(path), target)

    def _delete_file(self, path: str) -> None:
        self._remove(self._key(path))

    def _delete_directory(self, path: str, recursive: bool) -> None:
        keys = [info.path for info in self._scan(self._below(path), shallow=False)]
        if not recursive and any(not key.endswith(_PLACEHOLDER_SUFFIX) for key in keys):
            raise not_empty_error(self.uri_for(path))
        for key in keys:
            self._remove(key)
