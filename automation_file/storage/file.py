"""``File``: one file in any storage backend, addressed by URI.

.. code-block:: python

    from automation_file import File

    report = File("s3://reports/2026/q1.csv")
    report.exists()
    report.size
    data = report.read()
    report.copy_to("sftp://nas/archive/q1.csv")
    report.checksum().matches("sha256:9f86d0...")

The backend is looked up on every call, so a ``File`` can be created before its
backend is initialised or mounted.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from automation_file.exceptions import StorageNotFoundException, StoragePathTypeException
from automation_file.storage.backend import DEFAULT_CHECKSUM_ALGORITHM, StorageBackend
from automation_file.storage.resolver import StorageResolver, default_resolver
from automation_file.storage.types import Checksum, FileInfo
from automation_file.storage.uri import StorageURI, URILike, parse_storage_uri

_DEFAULT_ENCODING = "utf-8"
_DEFAULT_CHUNK = 1024 * 1024


def _expected_algorithm(expected: str | Checksum, fallback: str) -> str:
    if isinstance(expected, Checksum):
        return expected.algorithm
    if ":" in expected:
        return Checksum.parse(expected).algorithm
    return fallback


class File:
    """A file somewhere in storage. Creating one touches nothing."""

    def __init__(self, uri: URILike, *, resolver: StorageResolver | None = None) -> None:
        self._uri = parse_storage_uri(uri)
        self._resolver = resolver if resolver is not None else default_resolver

    @property
    def uri(self) -> StorageURI:
        return self._uri

    @property
    def name(self) -> str:
        return self._uri.name

    def exists(self) -> bool:
        """Return True when anything -- a file or a directory -- is at this URI."""
        backend, path = self._locate()
        return backend.exists(path)

    def is_file(self) -> bool:
        return self._type_is(directory=False)

    def is_dir(self) -> bool:
        return self._type_is(directory=True)

    def stat(self) -> FileInfo:
        """Return this file's :class:`FileInfo`; its ``path`` is the path of the URI."""
        backend, path = self._locate()
        return replace(backend.stat(path), path=self._uri.path)

    @property
    def size(self) -> int | None:
        return self.stat().size

    @property
    def modified_at(self) -> datetime | None:
        return self.stat().modified_at

    @property
    def etag(self) -> str | None:
        return self.stat().etag

    @property
    def version(self) -> str | None:
        return self.stat().version

    @property
    def content_type(self) -> str | None:
        return self.stat().content_type

    @property
    def metadata(self) -> Mapping[str, str]:
        return self.stat().metadata

    def read(self) -> bytes:
        """Return the whole content."""
        backend, path = self._locate()
        return backend.read_bytes(path)

    def read_text(self, encoding: str = _DEFAULT_ENCODING) -> str:
        return self.read().decode(encoding)

    def write(
        self, data: bytes | str, *, overwrite: bool = True, encoding: str = _DEFAULT_ENCODING
    ) -> FileInfo:
        """Store ``data`` as the content; text is encoded with ``encoding``."""
        payload = data.encode(encoding) if isinstance(data, str) else data
        backend, path = self._locate()
        return replace(backend.write_bytes(path, payload, overwrite=overwrite), path=self._uri.path)

    def open_read(self) -> BinaryIO:
        """Return a binary file object over the content; close it when done."""
        backend, path = self._locate()
        return backend.open_read(path)

    def open_write(self, *, overwrite: bool = True) -> BinaryIO:
        """Return a binary file object whose content is stored when it is closed."""
        backend, path = self._locate()
        return backend.open_write(path, overwrite=overwrite)

    def iter_chunks(self, chunk_size: int = _DEFAULT_CHUNK) -> Iterator[bytes]:
        """Yield the content in blocks of at most ``chunk_size`` bytes."""
        with self.open_read() as stream:
            yield from iter(lambda: stream.read(chunk_size), b"")

    def upload_from(
        self, local_path: str | os.PathLike[str], *, overwrite: bool = True
    ) -> FileInfo:
        """Store the local file ``local_path`` as the content."""
        backend, path = self._locate()
        return replace(backend.upload(local_path, path, overwrite=overwrite), path=self._uri.path)

    def download_to(self, local_path: str | os.PathLike[str], *, overwrite: bool = True) -> Path:
        """Write the content to the local file ``local_path`` and return that path."""
        backend, path = self._locate()
        return backend.download(path, local_path, overwrite=overwrite)

    def copy_to(self, target: URILike | File, *, overwrite: bool = True) -> File:
        """Copy this file to ``target`` in any backend and return the new ``File``."""
        destination = self._as_file(target)
        source_backend, source_path = self._locate()
        target_backend, target_path = destination._locate()
        target_backend.copy_from(source_backend, source_path, target_path, overwrite=overwrite)
        return destination

    def move_to(self, target: URILike | File, *, overwrite: bool = True) -> File:
        """Move this file to ``target`` in any backend and return the new ``File``."""
        destination = self._as_file(target)
        source_backend, source_path = self._locate()
        target_backend, target_path = destination._locate()
        target_backend.move_from(source_backend, source_path, target_path, overwrite=overwrite)
        return destination

    def delete(self, *, missing_ok: bool = False) -> None:
        """Remove this file. A directory is refused: delete it through ``Storage``."""
        backend, path = self._locate()
        try:
            info = backend.stat(path)
        except StorageNotFoundException:
            if missing_ok:
                return
            raise
        if info.is_dir:
            raise StoragePathTypeException(
                f"{self._uri} is a directory; remove it with Storage(...).delete(recursive=True)"
            )
        backend.delete(path)

    def checksum(self, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> Checksum:
        """Return the :class:`Checksum` of the content (SHA-256 by default)."""
        backend, path = self._locate()
        return backend.checksum(path, algorithm)

    def verify(
        self, expected: str | Checksum, *, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM
    ) -> bool:
        """Return whether the content has the digest ``expected``.

        ``expected`` is a ``Checksum``, ``"algorithm:digest"`` or a bare digest of
        ``algorithm``.
        """
        return self.checksum(_expected_algorithm(expected, algorithm)).matches(expected)

    def _locate(self) -> tuple[StorageBackend, str]:
        return self._resolver.resolve(self._uri)

    def _as_file(self, target: URILike | File) -> File:
        return target if isinstance(target, File) else File(target, resolver=self._resolver)

    def _type_is(self, *, directory: bool) -> bool:
        backend, path = self._locate()
        try:
            return backend.stat(path).is_dir is directory
        except StorageNotFoundException:
            return False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, File) and other._uri == self._uri

    def __hash__(self) -> int:
        return hash(self._uri)

    def __str__(self) -> str:
        return str(self._uri)

    def __repr__(self) -> str:
        return f"File({str(self._uri)!r})"
