"""fsspec backend: any `fsspec <https://filesystem-spec.readthedocs.io>`_ filesystem as a storage.

fsspec has a filesystem for most services (Google Cloud Storage, HDFS, FTP,
archives, ...). ``FsspecStorage`` puts one of them behind the storage contract.
The filesystem object carries its own connection and credentials, so there is no
URI factory: a backend is mounted where its files should appear, under any scheme.

.. code-block:: python

    Storage.mount("gcs://reports", FsspecStorage.from_url("gcs://reports", directories=False))
    File("gcs://reports/2026/q1.csv").read()

``directories`` says whether the filesystem keeps a directory that has no files in
it. Pass ``False`` for an object store, where a directory is only a key prefix.

Paths are passed to the filesystem literally. ``copy()`` and ``mv()`` of fsspec
expand glob patterns, so a copy uses ``cp_file`` and a move uses ``mv`` only for
paths without ``*``, ``?`` or ``[``; other moves are a copy followed by a delete.
"""

from __future__ import annotations

import contextlib
from collections.abc import Hashable, Iterable, Iterator, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageUnsupportedException,
    StorageURIException,
)
from automation_file.storage.backend import StorageBackend, join_path, missing_error
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import canonical_scheme, normalize_path

FSSPEC_SCHEME = "fsspec"
_NOT_INSTALLED = "fsspec is not installed; the fsspec backend needs it"
_URI_SEPARATOR = "://"
_DIRECTORY = "directory"
# The keys under which filesystems report a modification time in info() and ls().
_MODIFIED_KEYS = ("mtime", "LastModified", "last_modified", "modified", "updated")
_GLOB_CHARACTERS = frozenset("*?[")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@contextlib.contextmanager
def _fsspec_errors(location: str) -> Iterator[None]:
    """Turn what an fsspec filesystem raises into the storage layer's exceptions."""
    try:
        yield
    except StorageException:
        raise
    except ImportError as error:
        raise StorageUnavailableException(f"{location}: {error}") from error
    except (FileNotFoundError, NotADirectoryError) as error:
        raise missing_error(location) from error
    except PermissionError as error:
        raise StoragePermissionException(f"access to {location} was denied") from error
    except (ConnectionError, TimeoutError) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error
    except NotImplementedError as error:
        raise StorageUnsupportedException(
            f"{location}: the filesystem does not implement this operation"
        ) from error
    except Exception as error:
        # A filesystem raises whatever the client library behind it raises.
        raise StorageException(f"{location}: {type(error).__name__}") from error


def _utc(value: Any) -> datetime | None:
    """Read a modification time as filesystems report one: datetime, epoch seconds, ISO 8601."""
    if isinstance(value, str):
        text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return _EPOCH + timedelta(seconds=value)
        except (OverflowError, ValueError):
            return None
    return None


def _listed_time(details: Mapping[str, Any]) -> datetime | None:
    """Return the modification time an ``info()`` or ``ls()`` entry carries, if it has one."""
    for key in _MODIFIED_KEYS:
        moment = _utc(details.get(key))
        if moment is not None:
            return moment
    return None


def _implements_modified(filesystem: Any) -> bool:
    """Say whether the filesystem has a ``modified()`` of its own; the base class has none."""
    try:
        from fsspec import AbstractFileSystem
    except ImportError as error:
        raise StorageUnavailableException(_NOT_INSTALLED) from error
    modified = getattr(filesystem, "modified", None)
    inherited = getattr(modified, "__func__", None) is AbstractFileSystem.modified
    return callable(modified) and not inherited


def _spelled(filesystem: Any, root: str) -> str:
    """Return ``root`` the way the filesystem spells its own paths."""
    if not root:
        return str(getattr(filesystem, "root_marker", ""))
    strip = getattr(filesystem, "_strip_protocol", None)
    return str(strip(root)) if callable(strip) else root.rstrip("/")


def _without_credentials(url: str) -> str:
    """Return ``url`` without the user information it may carry, for messages."""
    scheme, separator, rest = url.partition(_URI_SEPARATOR)
    if not separator:
        return url
    authority, slash, path = rest.partition("/")
    return f"{scheme}{separator}{authority.rpartition('@')[2]}{slash}{path}"


def _scheme_of(url: str, filesystem: Any) -> str:
    """Pick the scheme of a storage built from ``url``: as written, else the filesystem's."""
    written, separator, _ = url.partition(_URI_SEPARATOR)
    protocol = getattr(filesystem, "protocol", ())
    candidates = [written] if separator else []
    candidates.extend([protocol] if isinstance(protocol, str) else protocol)
    for candidate in candidates:
        with contextlib.suppress(StorageURIException):
            return canonical_scheme(candidate)
    return FSSPEC_SCHEME


class FsspecStorage(StorageBackend):
    """An fsspec filesystem, whole or confined to the directory ``root``.

    ``scheme`` and ``capabilities`` belong to the instance: they depend on the
    filesystem it was given.
    """

    scheme = FSSPEC_SCHEME

    def __init__(
        self,
        filesystem: Any,
        *,
        root: str = "",
        scheme: str = FSSPEC_SCHEME,
        directories: bool = True,
    ) -> None:
        self._fs = filesystem
        self._root = _spelled(filesystem, root)
        self._prefix = f"{self._root.rstrip('/')}/" if self._root else ""
        self.scheme = canonical_scheme(scheme)
        self.capabilities = StorageCapabilities(
            directories=directories, modified_at=_implements_modified(filesystem)
        )

    @classmethod
    def from_url(
        cls, url: str, *, directories: bool = True, **storage_options: Any
    ) -> FsspecStorage:
        """Build the storage of an fsspec URL; the path of the URL becomes the root.

        ``storage_options`` go to the constructor of the filesystem.
        """
        try:
            from fsspec.core import url_to_fs
        except ImportError as error:
            raise StorageUnavailableException(_NOT_INSTALLED) from error
        location = _without_credentials(url)
        with _fsspec_errors(location):
            try:
                filesystem, root = url_to_fs(url, **storage_options)
            except ValueError as error:
                raise StorageURIException(f"fsspec cannot open {location!r}: {error}") from error
        return cls(
            filesystem, root=root, scheme=_scheme_of(url, filesystem), directories=directories
        )

    @property
    def filesystem(self) -> Any:
        """The fsspec filesystem this backend talks to."""
        return self._fs

    @property
    def root(self) -> str:
        """The directory this backend is confined to, as the filesystem spells it."""
        return self._root

    def _identity(self, path: str) -> Hashable:
        # Two roots of one filesystem name a file by the same full path.
        return (id(self._fs), self._full(path))

    def uri_for(self, path: str = "") -> str:
        return f"{self.scheme}{_URI_SEPARATOR}{self._full(self._normalize(path))}"

    def _normalize(self, path: str) -> str:
        clean = normalize_path(path)
        if ".." in clean.replace("\\", "/").split("/"):
            # Some filesystems (local on Windows, SMB) read a backslash as a separator.
            raise StorageURIException(f"storage paths cannot contain '..' segments: {path!r}")
        return clean

    def _full(self, path: str) -> str:
        """Return the path the filesystem knows ``path`` by."""
        return f"{self._prefix}{path}" if path else self._root

    def _stat(self, path: str) -> FileInfo | None:
        if not path and not self.capabilities.directories:
            # Without real directories the root is a key prefix, and a prefix is always there.
            return FileInfo(path=path, is_dir=True)
        full = self._full(path)
        try:
            with _fsspec_errors(self.uri_for(path)):
                info = self._describe(path, self._fs.info(full))
                if info.is_dir or info.modified_at is not None:
                    return info
                return replace(info, modified_at=self._asked_time(full))
        except StorageNotFoundException:
            return None

    def _describe(self, path: str, details: Mapping[str, Any]) -> FileInfo:
        modified = _listed_time(details)
        if details.get("type") == _DIRECTORY:
            return FileInfo(path=path, is_dir=True, modified_at=modified)
        size = details.get("size")
        return FileInfo(
            path=path, size=int(size) if isinstance(size, int) else None, modified_at=modified
        )

    def _asked_time(self, full: str) -> datetime | None:
        """Ask ``modified()`` for a time that ``info()`` did not carry."""
        if not self.capabilities.modified_at:
            return None
        try:
            return _utc(self._fs.modified(full))
        except NotImplementedError:
            return None

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        full = self._full(path)
        try:
            with _fsspec_errors(self.uri_for(path)):
                listing = self._fs.ls(full, detail=True)
        except StorageNotFoundException:
            if path or self.capabilities.directories:
                raise
            # A root that is only a key prefix has no keys below it yet.
            return []
        found: list[FileInfo] = []
        for details in listing:
            name = str(details.get("name", "")).rstrip("/")
            # A placeholder object some stores keep for the directory itself is not a child.
            if name and name != full.rstrip("/"):
                child = join_path(path, name.rsplit("/", 1)[-1])
                found.append(self._describe(child, details))
        return found

    def _upload(self, source: Path, path: str) -> None:
        with _fsspec_errors(self.uri_for(path)):
            self._fs.put_file(str(source), self._full(path))

    def _download(self, path: str, target: Path) -> None:
        with _fsspec_errors(self.uri_for(path)):
            self._fs.get_file(self._full(path), str(target))

    def _read_bytes(self, path: str) -> bytes:
        with _fsspec_errors(self.uri_for(path)):
            return bytes(self._fs.cat_file(self._full(path)))

    def _delete_file(self, path: str) -> None:
        with _fsspec_errors(self.uri_for(path)):
            self._fs.rm_file(self._full(path))

    def _mkdir(self, path: str) -> None:
        with _fsspec_errors(self.uri_for(path)):
            self._fs.makedirs(self._full(path), exist_ok=True)

    def _rmdir(self, path: str) -> None:
        # A directory that a filesystem only implies is gone once its last file is.
        with contextlib.suppress(StorageNotFoundException), _fsspec_errors(self.uri_for(path)):
            self._fs.rmdir(self._full(path))

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, FsspecStorage) or source._fs is not self._fs:
            return False
        try:
            with _fsspec_errors(self.uri_for(path)):
                # cp_file() takes both paths literally; copy() expands glob patterns.
                self._fs.cp_file(source._full(source_path), self._full(path))
        except StorageUnsupportedException:
            return False
        return True

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, FsspecStorage) or source._fs is not self._fs:
            return False
        origin, target = source._full(source_path), self._full(path)
        if _GLOB_CHARACTERS.intersection(origin + target):
            # mv() would read the path as a pattern; copy then delete names it literally.
            return False
        try:
            with _fsspec_errors(self.uri_for(path)):
                self._fs.mv(origin, target)
        except StorageUnsupportedException:
            return False
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FsspecStorage) and other._fs is self._fs and other._root == self._root
        )

    def __hash__(self) -> int:
        return hash((id(self._fs), self._root))

    def __repr__(self) -> str:
        return f"FsspecStorage({type(self._fs).__name__}, root={self._root!r})"
