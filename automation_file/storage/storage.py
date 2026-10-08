"""``Storage``: a directory in any backend, and the table of backends itself.

.. code-block:: python

    from automation_file import Storage

    reports = Storage("s3://reports/2026")
    for info in reports.list_dir(recursive=True):
        print(info.path, info.size)
    reports.upload("q1.csv", "q1.csv")
    reports.file("q1.csv").copy_to("local:///backup/q1.csv")

Paths given to an instance, and the ``FileInfo.path`` values it returns, are
relative to the URI the instance was created with.

The static methods manage the process-wide table: ``Storage.mount`` binds a
backend instance to a URI, ``Storage.register_scheme`` installs a factory for a
whole scheme, ``Storage.resolve`` shows where a URI leads.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from automation_file.storage.backend import DEFAULT_CHECKSUM_ALGORITHM, StorageBackend
from automation_file.storage.file import File
from automation_file.storage.resolver import BackendFactory, StorageResolver, default_resolver
from automation_file.storage.types import Checksum, FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI, URILike, normalize_path, parse_storage_uri

if TYPE_CHECKING:
    from automation_file.storage.tree import TreeResult


def _rebased(info: FileInfo, backend_base: str, asked: str) -> FileInfo:
    """Swap the backend's own prefix of ``info.path`` for the path the caller asked with."""
    tail = info.path[len(backend_base) :].lstrip("/")
    visible_base = normalize_path(asked)
    return replace(
        info, path=f"{visible_base}/{tail}" if visible_base and tail else visible_base or tail
    )


class Storage:
    """A directory somewhere in storage. Creating one touches nothing."""

    def __init__(self, uri: URILike, *, resolver: StorageResolver | None = None) -> None:
        self._uri = parse_storage_uri(uri)
        self._resolver = resolver if resolver is not None else default_resolver

    # ------------------------------------------------------------------ the backend table

    @staticmethod
    def mount(uri: URILike, backend: StorageBackend) -> None:
        """Serve ``uri`` and everything below it from ``backend``."""
        default_resolver.mount(uri, backend)

    @staticmethod
    def unmount(uri: URILike) -> bool:
        """Remove the mount at exactly ``uri``; return whether there was one."""
        return default_resolver.unmount(uri)

    @staticmethod
    def register_scheme(scheme: str, factory: BackendFactory) -> None:
        """Serve every unmounted URI of ``scheme`` through ``factory``."""
        default_resolver.register_scheme(scheme, factory)

    @staticmethod
    def schemes() -> list[str]:
        """Return every scheme that has a factory or a mount."""
        return default_resolver.schemes()

    @staticmethod
    def resolve(uri: URILike) -> tuple[StorageBackend, str]:
        """Return the backend that serves ``uri`` and the path inside that backend."""
        return default_resolver.resolve(uri)

    # ------------------------------------------------------------------ one directory

    @property
    def uri(self) -> StorageURI:
        return self._uri

    @property
    def backend(self) -> StorageBackend:
        """The backend that serves this storage right now."""
        return self._resolver.resolve(self._uri)[0]

    @property
    def capabilities(self) -> StorageCapabilities:
        return self.backend.capabilities

    def file(self, path: str) -> File:
        """Return the :class:`File` at ``path`` below this storage."""
        return File(self._uri.joinpath(path), resolver=self._resolver)

    def exists(self, path: str = "") -> bool:
        backend, target = self._locate(path)
        return backend.exists(target)

    def stat(self, path: str = "") -> FileInfo:
        backend, target = self._locate(path)
        return _rebased(backend.stat(target), target, path)

    def list_dir(self, path: str = "", *, recursive: bool = False) -> list[FileInfo]:
        """Return the entries under ``path``, sorted; ``recursive`` adds every descendant."""
        backend, target = self._locate(path)
        return [
            _rebased(info, target, path) for info in backend.list_dir(target, recursive=recursive)
        ]

    def mkdir(self, path: str = "", *, parents: bool = True, exist_ok: bool = True) -> None:
        backend, target = self._locate(path)
        backend.mkdir(target, parents=parents, exist_ok=exist_ok)

    def upload(
        self, local_path: str | os.PathLike[str], path: str, *, overwrite: bool = True
    ) -> FileInfo:
        """Store the local file ``local_path`` at ``path``."""
        backend, target = self._locate(path)
        return _rebased(backend.upload(local_path, target, overwrite=overwrite), target, path)

    def download(
        self, path: str, local_path: str | os.PathLike[str], *, overwrite: bool = True
    ) -> Path:
        """Write the file ``path`` to the local file ``local_path``."""
        backend, target = self._locate(path)
        return backend.download(target, local_path, overwrite=overwrite)

    def delete(self, path: str, *, recursive: bool = False, missing_ok: bool = False) -> None:
        """Remove the file or directory ``path``; ``""`` is this storage's own directory."""
        backend, target = self._locate(path)
        backend.delete(target, recursive=recursive, missing_ok=missing_ok)

    def checksum(self, path: str, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> Checksum:
        backend, target = self._locate(path)
        return backend.checksum(target, algorithm)

    def copy_to(self, target: URILike | Storage, *, overwrite: bool = True) -> TreeResult:
        """Copy every file below this storage to ``target``, in any backend."""
        from automation_file.storage.tree import copy_tree

        return copy_tree(self, self._as_storage(target), overwrite=overwrite)

    def sync_to(
        self,
        target: URILike | Storage,
        *,
        delete: bool = False,
        checksum: bool = False,
        dry_run: bool = False,
    ) -> TreeResult:
        """Make ``target`` hold what this storage holds, copying only what changed."""
        from automation_file.storage.tree import sync_tree

        return sync_tree(
            self, self._as_storage(target), delete=delete, checksum=checksum, dry_run=dry_run
        )

    def _as_storage(self, target: URILike | Storage) -> Storage:
        if isinstance(target, Storage):
            return target
        return Storage(target, resolver=self._resolver)

    def _locate(self, path: str) -> tuple[StorageBackend, str]:
        return self._resolver.resolve(self._uri.joinpath(path))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Storage) and other._uri == self._uri

    def __hash__(self) -> int:
        return hash(self._uri)

    def __str__(self) -> str:
        return str(self._uri)

    def __repr__(self) -> str:
        return f"Storage({str(self._uri)!r})"
