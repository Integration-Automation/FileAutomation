"""The Files service: browse and change what is behind a storage URI.

.. code-block:: python

    from automation_file.app import app_services

    files = app_services().files
    for entry in files.list_dir("s3://reports/2026"):
        print(entry.name, entry.size)
    files.preview("s3://reports/2026/q1.csv").text
    files.copy("s3://reports/2026/q1.csv", "local:///backup/")

Every path goes through the storage layer, so ``..`` is refused, credentials
in a URI are refused and a mounted directory cannot be left. A preview is
bounded twice: at most ``preview_bytes`` are returned, and a remote file larger
than ``fetch_limit`` is not fetched at all, because a backend without ranged
reads has to download a file before any of it can be read.
"""

from __future__ import annotations

import codecs
from dataclasses import asdict, dataclass
from typing import Any

from automation_file.app.errors import AppException
from automation_file.storage import (
    File,
    FileInfo,
    LocalStorage,
    MemoryStorage,
    Storage,
    StorageResolver,
    StorageURI,
    default_resolver,
    parse_storage_uri,
)

DEFAULT_PREVIEW_BYTES = 64 * 1024
DEFAULT_FETCH_LIMIT = 16 * 1024 * 1024
_HEX_PREVIEW_BYTES = 256
_TEXT_ENCODING = "utf-8"
_NUL = b"\x00"


@dataclass(frozen=True)
class FileEntry:
    """One file or directory, with the URI that addresses it."""

    uri: str
    path: str
    name: str
    is_dir: bool = False
    size: int | None = None
    modified_at: str | None = None
    content_type: str | None = None
    etag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the entry."""
        return asdict(self)


@dataclass(frozen=True)
class FilePreview:
    """The beginning of a file.

    ``text`` holds at most ``shown`` bytes of content, decoded as UTF-8; for
    ``binary`` content it is a hexadecimal dump of the first bytes. ``truncated``
    says the file is longer than what is shown, and ``note`` says why nothing is
    shown when the file was not read.
    """

    uri: str
    size: int | None
    shown: int = 0
    truncated: bool = False
    binary: bool = False
    text: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the preview."""
        return asdict(self)


def _entry(info: FileInfo, uri: StorageURI) -> FileEntry:
    return FileEntry(
        uri=str(uri),
        path=info.path,
        name=uri.name,
        is_dir=info.is_dir,
        size=info.size,
        modified_at=info.modified_at.isoformat() if info.modified_at else None,
        content_type=info.content_type,
        etag=info.etag,
    )


def _sort_key(entry: FileEntry) -> tuple[bool, str]:
    return (not entry.is_dir, entry.path.casefold())


def _decoded(data: bytes) -> str | None:
    """Return ``data`` as text, or ``None`` when it is not UTF-8 text."""
    if _NUL in data:
        return None
    try:
        # A sample may end in the middle of a character: do not treat that as an error.
        return codecs.getincrementaldecoder(_TEXT_ENCODING)().decode(data, final=False)
    except UnicodeDecodeError:
        return None


class FileService:
    """List, inspect, preview, copy, move and delete through storage URIs."""

    def __init__(
        self,
        resolver: StorageResolver | None = None,
        *,
        preview_bytes: int = DEFAULT_PREVIEW_BYTES,
        fetch_limit: int = DEFAULT_FETCH_LIMIT,
    ) -> None:
        if preview_bytes < 1 or fetch_limit < 1:
            raise AppException("preview_bytes and fetch_limit must be 1 or more")
        self._resolver = default_resolver if resolver is None else resolver
        self._preview_bytes = preview_bytes
        self._fetch_limit = fetch_limit

    def normalize(self, uri: str) -> str:
        """Return ``uri`` in its canonical form; a local path becomes a ``local://`` URI."""
        return str(parse_storage_uri(uri))

    def parent(self, uri: str) -> str:
        """Return the URI one level up; a root is its own parent."""
        return str(parse_storage_uri(uri).parent)

    def child(self, uri: str, name: str) -> str:
        """Return the URI of ``name`` below the directory ``uri``."""
        return str(parse_storage_uri(uri).joinpath(name))

    def exists(self, uri: str) -> bool:
        """Return whether a file or a directory is at ``uri``."""
        return self._file(uri).exists()

    def stat(self, uri: str) -> FileEntry:
        """Return the entry at ``uri``."""
        target = self._file(uri)
        return _entry(target.stat(), target.uri)

    def list_dir(self, uri: str, recursive: bool = False) -> list[FileEntry]:
        """Return the entries of the directory ``uri``: directories first, then by path."""
        directory = Storage(uri, resolver=self._resolver)
        entries = [
            _entry(info, directory.uri.joinpath(info.path))
            for info in directory.list_dir(recursive=recursive)
        ]
        return sorted(entries, key=_sort_key)

    def preview(self, uri: str, max_bytes: int | None = None) -> FilePreview:
        """Return the beginning of the file ``uri``, at most ``max_bytes`` of it."""
        limit = self._preview_bytes if max_bytes is None else max_bytes
        if limit < 1:
            raise AppException("a preview needs at least one byte")
        target = self._file(uri)
        info = target.stat()
        location = str(target.uri)
        if info.is_dir:
            raise AppException(f"{location} is a directory; there is nothing to preview")
        if not self._reads_in_place(target) and (info.size or 0) > self._fetch_limit:
            return FilePreview(
                uri=location,
                size=info.size,
                truncated=True,
                note=(
                    f"not fetched: {info.size} bytes is more than the preview limit of "
                    f"{self._fetch_limit} bytes for a remote file"
                ),
            )
        with target.open_read() as stream:
            data = stream.read(limit + 1)
        truncated = len(data) > limit
        sample = data[:limit]
        text = _decoded(sample)
        if text is None:
            return FilePreview(
                uri=location,
                size=info.size,
                shown=min(len(sample), _HEX_PREVIEW_BYTES),
                truncated=truncated or len(sample) > _HEX_PREVIEW_BYTES,
                binary=True,
                text=sample[:_HEX_PREVIEW_BYTES].hex(" "),
                note="binary content, shown as hexadecimal",
            )
        return FilePreview(
            uri=location, size=info.size, shown=len(sample), truncated=truncated, text=text
        )

    def copy(self, source: str, target: str, overwrite: bool = True) -> FileEntry:
        """Copy ``source`` to ``target`` and return the new entry.

        A file copied onto an existing directory lands inside it under its own
        name. A directory is copied with everything below it.
        """
        origin = self._file(source)
        if origin.stat().is_dir:
            Storage(source, resolver=self._resolver).copy_to(
                Storage(target, resolver=self._resolver), overwrite=overwrite
            )
            return self.stat(target)
        copied = origin.copy_to(self._destination(origin, target), overwrite=overwrite)
        return _entry(copied.stat(), copied.uri)

    def move(self, source: str, target: str, overwrite: bool = True) -> FileEntry:
        """Move the file ``source`` to ``target`` and return the new entry.

        A file moved onto an existing directory lands inside it. A directory is
        refused: copy it and delete the original once the copy has been checked.
        """
        origin = self._file(source)
        if origin.stat().is_dir:
            raise AppException(
                f"{origin.uri} is a directory; copy it and delete the original instead of moving it"
            )
        moved = origin.move_to(self._destination(origin, target), overwrite=overwrite)
        return _entry(moved.stat(), moved.uri)

    def delete(self, uri: str, recursive: bool = False) -> bool:
        """Remove the file or directory at ``uri``; a directory with entries needs ``recursive``."""
        Storage(uri, resolver=self._resolver).delete("", recursive=recursive)
        return True

    def mkdir(self, uri: str) -> bool:
        """Create the directory ``uri`` and its missing parents."""
        Storage(uri, resolver=self._resolver).mkdir()
        return True

    def _file(self, uri: str) -> File:
        return File(uri, resolver=self._resolver)

    def _destination(self, origin: File, target: str) -> File:
        """Return where ``origin`` goes: ``target``, or inside it when it is a directory."""
        destination = self._file(target)
        if destination.is_dir():
            return self._file(str(destination.uri.joinpath(origin.name)))
        return destination

    def _reads_in_place(self, target: File) -> bool:
        """Return whether the backend can read the start of a file without fetching all of it."""
        backend = self._resolver.resolve(target.uri)[0]
        return isinstance(backend, (LocalStorage, MemoryStorage))
