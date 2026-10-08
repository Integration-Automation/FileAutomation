"""The monitored tree: where it is, which backend serves it, and what is left out of it.

Everything the integrity subsystem reads goes through :class:`Target`, and
:class:`Target` goes through the storage layer, so a tree may live in any
backend. Two things depend on the backend being a
:class:`~automation_file.storage.LocalStorage`: the permission bits of a file,
and the directory a watcher can observe.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

from automation_file.exceptions import (
    FileNotExistsException,
    PathTraversalException,
    StorageNotFoundException,
    StoragePathTypeException,
)
from automation_file.integrity.errors import IntegrityException
from automation_file.storage.backend import StorageBackend, join_path
from automation_file.storage.local_storage import LocalStorage
from automation_file.storage.resolver import StorageResolver, default_resolver
from automation_file.storage.storage import Storage
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import LOCAL_SCHEME, StorageURI, URILike, parse_storage_uri

PathRule = Callable[[str], bool]
ModeReader = Callable[[str], int | None]


def _no_mode(_path: str) -> int | None:
    return None


class Target:
    """A directory somewhere in storage, read for snapshots."""

    def __init__(self, uri: URILike, *, resolver: StorageResolver | None = None) -> None:
        self._resolver = resolver if resolver is not None else default_resolver
        self._uri = parse_storage_uri(uri)
        self._storage = Storage(self._uri, resolver=self._resolver)
        self._left_out: list[PathRule] = []
        # Windows compares local paths without regard to case.
        self._case_blind = self._uri.scheme == LOCAL_SCHEME and os.sep == "\\"

    @property
    def uri(self) -> StorageURI:
        return self._uri

    @property
    def storage(self) -> Storage:
        return self._storage

    @property
    def resolver(self) -> StorageResolver:
        return self._resolver

    @property
    def backend(self) -> StorageBackend:
        """The backend that serves the tree right now."""
        return self._resolver.resolve(self._uri)[0]

    @property
    def backend_name(self) -> str:
        return self.backend.scheme

    @property
    def capabilities(self) -> StorageCapabilities:
        return self.backend.capabilities

    def fold(self, path: str) -> str:
        """Return ``path`` in the form paths of this tree are compared in."""
        return path.casefold() if self._case_blind else path

    def relative(self, other: URILike) -> str | None:
        """Return the path of ``other`` inside this tree: ``""`` for the tree itself, ``None`` outside."""
        candidate = parse_storage_uri(other)
        if candidate.scheme != self._uri.scheme:
            return None
        if self.fold(candidate.authority) != self.fold(self._uri.authority):
            return None
        own = self._uri.path.split("/") if self._uri.path else []
        theirs = candidate.path.split("/") if candidate.path else []
        head = theirs[: len(own)]
        if [self.fold(segment) for segment in head] != [self.fold(segment) for segment in own]:
            return None
        return "/".join(theirs[len(own) :])

    def leave_out(self, rule: PathRule) -> None:
        """Skip every file whose folded path ``rule`` accepts."""
        self._left_out.append(rule)

    def is_left_out(self, path: str) -> bool:
        folded = self.fold(path)
        return any(rule(folded) for rule in self._left_out)

    def files(self, below: str = "") -> list[FileInfo]:
        """Return every file at any depth under ``below``, with paths relative to the tree.

        A prefix of an object store that holds nothing is an empty tree. A
        directory of a filesystem that is missing is an error.
        """
        try:
            listing = self._storage.list_dir(below, recursive=True)
        except StorageNotFoundException as error:
            if below or not self.capabilities.directories:
                return []
            raise IntegrityException(f"target {self._uri} does not exist") from error
        except StoragePathTypeException as error:
            if below:
                return []
            raise IntegrityException(f"target {self._uri} is not a directory") from error
        return [info for info in listing if not info.is_dir and not self.is_left_out(info.path)]

    def at(self, path: str) -> list[FileInfo]:
        """Return the files at ``path``: the file itself, all below a directory, none if gone.

        A file is described the way :meth:`files` describes it, so the result
        compares cleanly with a baseline taken from a listing.
        """
        try:
            info = self._storage.stat(path)
            if info.is_dir:
                return self.files(path)
            if self.is_left_out(info.path):
                return []
            return [self._as_listed(info)]
        except FileNotExistsException:
            return []

    def _as_listed(self, info: FileInfo) -> FileInfo:
        """Return the listing's view of the file ``info``.

        On a filesystem ``stat`` and a listing agree. An object store answers
        ``stat`` from an HTTP header with whole seconds and a listing with the
        stored time, so the two can differ for the same object.
        """
        if self.capabilities.directories:
            return info
        parent = info.path.rpartition("/")[0]
        for listed in self._storage.list_dir(parent):
            if listed.path == info.path and not listed.is_dir:
                return listed
        return info

    def local_root(self) -> Path | None:
        """Return the directory of the tree on this machine, or ``None`` for another backend."""
        backend, base = self._resolver.resolve(self._uri)
        return backend.local_path(base) if isinstance(backend, LocalStorage) else None

    def mode_reader(self) -> ModeReader:
        """Return a function that reads the permission bits of a path; always ``None`` off-disk."""
        backend, base = self._resolver.resolve(self._uri)
        if not isinstance(backend, LocalStorage):
            return _no_mode
        local = backend

        def read(path: str) -> int | None:
            try:
                return stat.S_IMODE(local.local_path(join_path(base, path)).stat().st_mode)
            except (OSError, PathTraversalException):
                return None

        return read
