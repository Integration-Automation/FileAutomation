"""The contract every storage backend implements.

:class:`StorageBackend` is a Template Method class. Its public methods --
``exists``, ``stat``, ``list_dir``, ``mkdir``, ``upload``, ``download``,
``delete``, ``checksum``, ``read_bytes``, ``write_bytes``, ``copy_from`` and
``move_from`` -- are the same for every backend: they normalise the path, check
what is already there, raise the same :class:`StorageException` subclasses and
create missing parent directories. A backend only supplies the primitives named
with a leading underscore, so a new backend gets the shared behaviour for free
and the contract suite (``tests/storage_contract.py``) checks it the same way as
the built-in ones.

Paths are relative to the backend's root, use ``/`` and never start with one.
The root itself is the empty string.
"""

from __future__ import annotations

import contextlib
import hashlib
import mimetypes
import os
import shutil
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import BinaryIO, TypeVar

from automation_file.core.checksum import file_checksum
from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageException,
    StorageNotEmptyException,
    StorageNotFoundException,
    StoragePathTypeException,
    StorageUnsupportedException,
)
from automation_file.storage import observe
from automation_file.storage.streams import StagedReader, StagedWriter, new_scratch_file
from automation_file.storage.types import Checksum, FileInfo, StorageCapabilities
from automation_file.storage.uri import normalize_path

DEFAULT_CHECKSUM_ALGORITHM = "sha256"
_STAGED_NAME = "staged"
# Digests of these need an explicit length, so they have no fixed hex form.
_VARIABLE_LENGTH_PREFIX = "shake"

_BackendT = TypeVar("_BackendT", bound="StorageBackend")


def checked_algorithm(algorithm: str) -> str:
    """Return the lower-case name of a fixed-length hash ``hashlib`` provides."""
    name = algorithm.strip().lower()
    if name not in hashlib.algorithms_available or name.startswith(_VARIABLE_LENGTH_PREFIX):
        raise StorageUnsupportedException(f"unsupported checksum algorithm: {algorithm!r}")
    return name


def parent_of(path: str) -> str:
    """Return the directory part of a normalised path (empty for a top-level entry)."""
    return path.rpartition("/")[0]


def join_path(directory: str, name: str) -> str:
    """Append ``name`` to a normalised directory path."""
    return f"{directory}/{name}" if directory else name


def guess_content_type(name: str) -> str | None:
    """Guess a MIME type from the suffixes of ``name``."""
    # Only the suffixes are passed on: guess_type() parses its argument as a URL.
    return mimetypes.guess_type("_" + "".join(PurePosixPath(name).suffixes))[0]


def missing_error(location: str) -> StorageNotFoundException:
    return StorageNotFoundException(f"{location} does not exist")


def not_a_file_error(location: str) -> StoragePathTypeException:
    return StoragePathTypeException(f"{location} is a directory, not a file")


def not_empty_error(location: str) -> StorageNotEmptyException:
    return StorageNotEmptyException(
        f"{location} is not empty; pass recursive=True to delete its contents"
    )


def _by_path(info: FileInfo) -> str:
    return info.path


def _by_depth(info: FileInfo) -> int:
    return info.path.count("/")


class StorageBackend(ABC):
    """One storage root: a directory tree, a bucket, a share, a remote session."""

    #: Class-wide defaults. A backend whose instances differ (one adapter over many
    #: kinds of filesystem) assigns its own in ``__init__``.
    scheme: str = ""
    capabilities: StorageCapabilities = StorageCapabilities()

    # ------------------------------------------------------------------ primitives

    @abstractmethod
    def _stat(self, path: str) -> FileInfo | None:
        """Return the entry at ``path`` with ``FileInfo.path == path``, or ``None`` if absent.

        The root (``""``) is a directory.
        """

    @abstractmethod
    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        """Return the immediate children of the existing directory ``path``."""

    @abstractmethod
    def _upload(self, source: Path, path: str) -> None:
        """Store the local file ``source`` at ``path``, replacing a file already there.

        The parent directory exists and ``path`` is not a directory.
        """

    @abstractmethod
    def _download(self, path: str, target: Path) -> None:
        """Write the existing file ``path`` to the local file ``target``."""

    @abstractmethod
    def _delete_file(self, path: str) -> None:
        """Remove the existing file ``path``."""

    def _mkdir(self, path: str) -> None:
        """Create the directory ``path``; its parent exists. An existing directory is not an error.

        Called only when ``capabilities.directories`` is true.
        """
        raise StorageUnsupportedException(f"{self.uri_for(path)}: this backend cannot mkdir")

    def _rmdir(self, path: str) -> None:
        """Remove the empty directory ``path``.

        Called only when ``capabilities.directories`` is true.
        """
        raise StorageUnsupportedException(f"{self.uri_for(path)}: this backend cannot rmdir")

    def _walk(self, path: str) -> Iterable[FileInfo]:
        """Return every descendant of the directory ``path``, directories included.

        The default recurses through :meth:`_list_dir`. An object store overrides it
        with one flat listing.
        """
        found: list[FileInfo] = []
        pending = [path]
        while pending:
            for info in self._list_dir(pending.pop()):
                found.append(info)
                if info.is_dir:
                    pending.append(info.path)
        return found

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        """Copy a file from ``source`` without a local staging copy; ``False`` if unable."""
        return False

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        """Move a file from ``source`` natively (a rename); ``False`` if unable."""
        return False

    def _checksum(self, path: str, algorithm: str) -> str:
        """Return the hex digest of the file ``path``. The default hashes a staged copy."""
        with tempfile.TemporaryDirectory() as scratch:
            staged = Path(scratch) / _STAGED_NAME
            self._download(path, staged)
            return file_checksum(staged, algorithm)

    def _read_bytes(self, path: str) -> bytes:
        """Return the content of the file ``path``. The default reads a staged copy."""
        with tempfile.TemporaryDirectory() as scratch:
            staged = Path(scratch) / _STAGED_NAME
            self._download(path, staged)
            return staged.read_bytes()

    def _open_read(self, path: str) -> BinaryIO:
        """Return a binary file object over the file ``path``.

        The default serves a staged copy that is removed when the object is closed.
        """
        scratch, staged = new_scratch_file()
        reader: BinaryIO | None = None
        try:
            self._download(path, staged)
            reader = StagedReader(staged, scratch)
            return reader
        finally:
            if reader is None:
                shutil.rmtree(scratch, ignore_errors=True)

    def _delete_directory(self, path: str, recursive: bool) -> None:
        """Remove the directory ``path``, which is not the root."""
        if not recursive:
            if any(True for _ in self._list_dir(path)):
                raise not_empty_error(self.uri_for(path))
        else:
            for info in sorted(self._walk(path), key=_by_depth, reverse=True):
                if not info.is_dir:
                    self._delete_file(info.path)
                elif self.capabilities.directories:
                    self._rmdir(info.path)
        if self.capabilities.directories:
            self._rmdir(path)

    def _normalize(self, path: str) -> str:
        """Normalise a caller-supplied path. Backends with extra separators extend it."""
        return normalize_path(path)

    def _is_root(self, path: str) -> bool:
        """Say whether ``path`` is a root that :meth:`delete` must refuse to remove."""
        return not path

    # ------------------------------------------------------------------ public API

    def uri_for(self, path: str = "") -> str:
        """Return the storage URI of ``path`` in this backend, for messages and logs."""
        return f"{self.scheme}:///{self._normalize(path)}"

    def exists(self, path: str) -> bool:
        """Return True when a file or a directory is at ``path``."""
        return self._stat(self._normalize(path)) is not None

    def stat(self, path: str) -> FileInfo:
        """Return the :class:`FileInfo` of ``path``; raise ``StorageNotFoundException`` if absent."""
        clean = self._normalize(path)
        info = self._stat(clean)
        if info is None:
            raise missing_error(self.uri_for(clean))
        return info

    def list_dir(self, path: str = "", *, recursive: bool = False) -> list[FileInfo]:
        """Return the entries under the directory ``path``, sorted by path.

        ``recursive=True`` returns every descendant, directories included.
        """
        clean = self._normalize(path)
        if not self.stat(clean).is_dir:
            raise StoragePathTypeException(f"{self.uri_for(clean)} is not a directory")
        entries = self._walk(clean) if recursive else self._list_dir(clean)
        return sorted(entries, key=_by_path)

    def mkdir(self, path: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        """Create the directory ``path``.

        Where directories are only implied by file paths (``capabilities.directories``
        is false) nothing is created and nothing needs to be.
        """
        with self._observing("mkdir", path):
            clean = self._normalize(path)
            info = self._stat(clean)
            if info is not None:
                if not info.is_dir:
                    raise StoragePathTypeException(f"{self.uri_for(clean)} is a file")
                if not exist_ok:
                    raise StorageAlreadyExistsException(f"{self.uri_for(clean)} already exists")
                return
            if not self.capabilities.directories:
                return
            self._make_parents(clean, create=parents)
            self._mkdir(clean)

    def upload(
        self, local_path: str | os.PathLike[str], path: str, *, overwrite: bool = True
    ) -> FileInfo:
        """Store the local file ``local_path`` at ``path`` and return its ``FileInfo``.

        Missing parent directories are created.
        """
        with self._observing("upload", path):
            source = Path(local_path)
            if not source.is_file():
                raise StorageNotFoundException(f"local source is not a file: {source}")
            clean = self._writable_file(path, overwrite)
            self._make_parents(clean)
            self._upload(source, clean)
            return self.stat(clean)

    def download(
        self, path: str, local_path: str | os.PathLike[str], *, overwrite: bool = True
    ) -> Path:
        """Write the file ``path`` to ``local_path`` and return that path.

        The content lands in a sibling ``.part`` file that replaces the target once
        complete, so a failed download never leaves a truncated target behind.
        """
        with self._observing("download", path):
            clean = self._existing_file(path)
            target = Path(local_path)
            if target.is_dir():
                raise StoragePathTypeException(f"local target is a directory: {target}")
            if not overwrite and target.exists():
                raise StorageAlreadyExistsException(f"local target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
            try:
                self._download(clean, partial)
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)
            return target

    def delete(self, path: str, *, recursive: bool = False, missing_ok: bool = False) -> None:
        """Remove the file or directory at ``path``.

        A directory with entries needs ``recursive=True``. The storage root is never
        removed.
        """
        with self._observing("delete", path):
            clean = self._normalize(path)
            info = self._stat(clean)
            if info is None:
                if missing_ok:
                    return
                raise missing_error(self.uri_for(clean))
            if not info.is_dir:
                self._delete_file(clean)
                return
            if self._is_root(clean):
                raise StorageUnsupportedException(
                    f"refusing to delete the storage root {self.uri_for(clean)}"
                )
            self._delete_directory(clean, recursive)

    def checksum(self, path: str, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> Checksum:
        """Return the :class:`Checksum` of the file ``path`` (SHA-256 by default)."""
        name = checked_algorithm(algorithm)
        return Checksum(name, self._checksum(self._existing_file(path), name))

    def read_bytes(self, path: str) -> bytes:
        """Return the whole content of the file ``path``."""
        with self._observing("read", path):
            return self._read_bytes(self._existing_file(path))

    def open_read(self, path: str) -> BinaryIO:
        """Return a binary file object over the file ``path``; close it when done.

        Use it for a file too large to hold in memory with :meth:`read_bytes`.
        """
        with self._observing("read", path):
            return self._open_read(self._existing_file(path))

    def open_write(self, path: str, *, overwrite: bool = True) -> BinaryIO:
        """Return a binary file object whose content becomes the file ``path`` on close.

        Nothing is stored when a ``with`` block is left through an exception. The
        ``overwrite`` check runs now and again when the content is stored.
        """
        clean = self._writable_file(path, overwrite)
        return StagedWriter(lambda staged: self.upload(staged, clean, overwrite=overwrite))

    def write_bytes(self, path: str, data: bytes, *, overwrite: bool = True) -> FileInfo:
        """Store ``data`` as the file ``path`` and return its ``FileInfo``."""
        with tempfile.TemporaryDirectory() as scratch:
            staged = Path(scratch) / _STAGED_NAME
            staged.write_bytes(data)
            return self.upload(staged, path, overwrite=overwrite)

    def copy_from(
        self, source: StorageBackend, source_path: str, path: str, *, overwrite: bool = True
    ) -> FileInfo:
        """Copy the file ``source_path`` of ``source`` (which may be this backend) to ``path``.

        The copy is native when the two backends can do it between themselves and
        goes through a local staging file otherwise.
        """
        with self._observing("copy", path, (source, source_path)), observe.suppressed():
            origin, target = self._transfer_paths(source, source_path, path, overwrite)
            self._pull(source, origin, target)
            return self.stat(target)

    def move_from(
        self, source: StorageBackend, source_path: str, path: str, *, overwrite: bool = True
    ) -> FileInfo:
        """Move the file ``source_path`` of ``source`` to ``path``: a rename, or copy then delete."""
        with self._observing("move", path, (source, source_path)), observe.suppressed():
            origin, target = self._transfer_paths(source, source_path, path, overwrite)
            if not self._move_from(source, origin, target):
                self._pull(source, origin, target)
                source.delete(origin)
            return self.stat(target)

    def close(self) -> None:  # noqa: B027 - optional hook: most backends hold nothing open
        """Release what the backend holds open. The default holds nothing."""

    def __enter__(self: _BackendT) -> _BackendT:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ shared steps

    def _display_uri(self, path: str) -> str:
        """Return the URI of ``path`` for a report, even when the path itself is invalid."""
        try:
            return self.uri_for(path)
        except StorageException:
            return f"{self.scheme}:{path}"

    @contextlib.contextmanager
    def _observing(
        self, operation: str, path: str, origin: tuple[StorageBackend, str] | None = None
    ) -> Iterator[None]:
        """Report the enclosed operation, with its outcome and duration, to the observers."""
        if not observe.has_listeners():
            yield
            return
        started = time.perf_counter()
        failure: BaseException | None = None
        try:
            yield
        except BaseException as error:
            failure = error
            raise
        finally:
            observe.notify(
                observe.StorageOperation(
                    operation=operation,
                    uri=self._display_uri(path),
                    backend=self.scheme,
                    status=observe.STATUS_ERROR if failure else observe.STATUS_OK,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    source_uri=origin[0]._display_uri(origin[1]) if origin else None,
                    error=f"{type(failure).__name__}: {failure}" if failure else None,
                    error_type=type(failure).__name__ if failure else None,
                )
            )

    def _existing_file(self, path: str) -> str:
        clean = self._normalize(path)
        if self.stat(clean).is_dir:
            raise not_a_file_error(self.uri_for(clean))
        return clean

    def _writable_file(self, path: str, overwrite: bool) -> str:
        clean = self._normalize(path)
        if not clean:
            raise StoragePathTypeException(f"{self.uri_for(clean)} is the storage root, not a file")
        existing = self._stat(clean)
        if existing is None:
            return clean
        if existing.is_dir:
            raise not_a_file_error(self.uri_for(clean))
        if not overwrite:
            raise StorageAlreadyExistsException(f"{self.uri_for(clean)} already exists")
        return clean

    def _make_parents(self, path: str, *, create: bool = True) -> None:
        if not self.capabilities.directories:
            return
        missing: list[str] = []
        parent = parent_of(path)
        while parent:
            info = self._stat(parent)
            if info is not None:
                if not info.is_dir:
                    raise StoragePathTypeException(f"{self.uri_for(parent)} is a file")
                break
            missing.append(parent)
            parent = parent_of(parent)
        if missing and not create:
            raise missing_error(self.uri_for(missing[0]))
        for directory in reversed(missing):
            self._mkdir(directory)

    def _transfer_paths(
        self, source: StorageBackend, source_path: str, path: str, overwrite: bool
    ) -> tuple[str, str]:
        info = source.stat(source_path)
        if info.is_dir:
            raise not_a_file_error(source.uri_for(info.path))
        target = self._normalize(path)
        if source == self and info.path == target:
            raise StorageException(f"{self.uri_for(target)}: source and target are the same file")
        target = self._writable_file(target, overwrite)
        self._make_parents(target)
        return info.path, target

    def _pull(self, source: StorageBackend, origin: str, target: str) -> None:
        if self._copy_from(source, origin, target):
            return
        with tempfile.TemporaryDirectory() as scratch:
            staged = source.download(origin, Path(scratch) / _STAGED_NAME)
            self._upload(staged, target)
