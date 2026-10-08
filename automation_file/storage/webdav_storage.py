"""WebDAV backend, mounted on a :class:`~automation_file.remote.webdav.client.WebDAVClient`.

The client carries the base URL and the credentials, so there is no URI factory:
a backend is mounted where its files should appear.

.. code-block:: python

    client = WebDAVClient("https://files.example.com/remote.php/dav", "user", password)
    Storage.mount("webdav://files.example.com", WebDAVStorage(client))
    File("webdav://files.example.com/reports/q1.csv").read()

Collections are real directories. ``stat`` is a ``PROPFIND`` with ``Depth: 0`` and
reports the size, ``getlastmodified``, ``getetag`` and ``getcontenttype``. Copy
and move between two paths of one client are done by the server (``COPY`` /
``MOVE``), and deleting a directory is one ``DELETE``.
"""

# pylint: disable=protected-access  # a backend reads the private parts of another instance of its own kind

from __future__ import annotations

import contextlib
from collections.abc import Hashable, Iterable, Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
    WebDAVException,
)
from automation_file.storage.backend import (
    StorageBackend,
    join_path,
    missing_error,
    not_empty_error,
)
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI, normalize_path

if TYPE_CHECKING:
    from automation_file.remote.webdav.client import WebDAVClient, WebDAVEntry

WEBDAV_SCHEME = "webdav"
_MISSING_STATUS = 404
_BELOW_A_FILE_STATUS = 400
_DENIED_STATUS = frozenset({401, 403})
_TRANSIENT_STATUS = frozenset({408, 429})
_SERVER_ERROR = 500
# MKCOL answers 405 when something is already at the path.
_ALREADY_THERE_STATUS = 405
# What a server without COPY / MOVE answers to them.
_NO_SUCH_METHOD_STATUS = frozenset({405, 501})


def _status_error(status: int | None, location: str) -> StorageException:
    """Translate the HTTP status of a failed request into a storage exception."""
    if status is None:
        return StorageException(f"{location}: the WebDAV request failed")
    if status == _MISSING_STATUS:
        return missing_error(location)
    if status in _DENIED_STATUS:
        return StoragePermissionException(f"access to {location} was denied ({status})")
    if status in _TRANSIENT_STATUS or status >= _SERVER_ERROR:
        return StorageTransientException(f"{location}: the WebDAV server answered {status}")
    return StorageException(f"{location}: the WebDAV server answered {status}")


@contextlib.contextmanager
def _webdav_errors(location: str) -> Iterator[None]:
    """Turn WebDAV client errors and dropped connections into the storage layer's exceptions."""
    try:
        from requests import exceptions as request_errors
    except ImportError as error:
        raise StorageUnavailableException(
            "requests is not installed; the WebDAV backend needs it"
        ) from error
    dropped = (
        request_errors.ConnectionError,
        request_errors.Timeout,
        request_errors.ChunkedEncodingError,
    )
    try:
        yield
    except WebDAVException as error:
        cause = error.__cause__
        if error.status_code is None and isinstance(cause, dropped):
            raise StorageTransientException(f"{location}: {type(cause).__name__}") from error
        raise _status_error(error.status_code, location) from error
    except dropped as error:
        # A download is streamed after the client has checked the response.
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error


def _status_of(error: StorageException) -> int | None:
    """Return the HTTP status behind a translated error."""
    return getattr(error.__cause__, "status_code", None)


def _modified(text: str | None) -> datetime | None:
    """Parse ``getlastmodified``, an HTTP date, into an aware UTC datetime."""
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _etag(text: str | None) -> str | None:
    """Drop the quotes of a strong validator; a weak one (``W/"..."``) is kept as it is."""
    if text and len(text) > 1 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def _file_info(path: str, entry: WebDAVEntry) -> FileInfo:
    modified = _modified(entry.last_modified)
    if entry.is_dir:
        return FileInfo(path=path, is_dir=True, modified_at=modified)
    return FileInfo(
        path=path,
        size=entry.size,
        modified_at=modified,
        etag=_etag(entry.etag),
        content_type=entry.content_type,
    )


class WebDAVStorage(StorageBackend):
    """The collection a ``WebDAVClient`` points at, or the collection ``root`` below it."""

    scheme = WEBDAV_SCHEME
    capabilities = StorageCapabilities(
        directories=True, modified_at=True, etag=True, content_type=True
    )

    def __init__(self, client: WebDAVClient, *, root: str = "") -> None:
        self._client = client
        self._root = self._normalize(root)

    @property
    def root(self) -> str:
        """The collection this backend is confined to, relative to the client's base URL."""
        return self._root

    def _identity(self, path: str) -> Hashable:
        # Two roots of one server name a file by the same full path.
        return (WEBDAV_SCHEME, id(self._client), self._remote(path))

    def uri_for(self, path: str = "") -> str:
        base = urlsplit(self._client.base_url)
        # The host without any user information the base URL may carry.
        authority = base.netloc.rpartition("@")[2]
        return str(
            StorageURI(WEBDAV_SCHEME, authority, "/".join((unquote(base.path), self._root, path)))
        )

    def _normalize(self, path: str) -> str:
        clean = normalize_path(path)
        if clean != clean.rstrip():
            # WebDAVClient trims the path it is given, so the name could not be addressed.
            raise StorageURIException(f"a WebDAV path cannot end with white space: {path!r}")
        return clean

    def _remote(self, path: str) -> str:
        """Return the path to ask the client for.

        With the leading slash the client neither trims white space off the first
        segment nor reads the path as an absolute URL.
        """
        joined = join_path(self._root, path) if path else self._root
        return f"/{joined}"

    def _collection(self, path: str) -> str:
        """Like :meth:`_remote`, with the trailing slash a collection is addressed by."""
        remote = self._remote(path)
        return remote if remote.endswith("/") else f"{remote}/"

    def _stat(self, path: str) -> FileInfo | None:
        try:
            with _webdav_errors(self.uri_for(path)):
                entry = self._client.stat(self._remote(path))
        except StorageNotFoundException:
            return None
        except StorageException as error:
            # Apache answers 400, not 404, for a path below a file: nothing can be there.
            if _status_of(error) != _BELOW_A_FILE_STATUS:
                raise
            return None
        return _file_info(path, entry)

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        with _webdav_errors(self.uri_for(path)):
            entries = self._client.list_dir(self._collection(path), include_self=False)
        return [_file_info(join_path(path, entry.name), entry) for entry in entries if entry.name]

    def _upload(self, source: Path, path: str) -> None:
        with _webdav_errors(self.uri_for(path)):
            self._client.upload(source, self._remote(path))

    def _download(self, path: str, target: Path) -> None:
        with _webdav_errors(self.uri_for(path)):
            self._client.download(self._remote(path), target)

    def _delete_file(self, path: str) -> None:
        with _webdav_errors(self.uri_for(path)):
            self._client.delete(self._remote(path))

    def _mkdir(self, path: str) -> None:
        try:
            with _webdav_errors(self.uri_for(path)):
                self._client.mkcol(self._collection(path))
        except StorageException as error:
            if _status_of(error) != _ALREADY_THERE_STATUS:
                raise
            existing = self._stat(path)
            if existing is None or not existing.is_dir:
                raise

    def _rmdir(self, path: str) -> None:
        with _webdav_errors(self.uri_for(path)):
            self._client.delete(self._collection(path))

    def _delete_directory(self, path: str, recursive: bool) -> None:
        # DELETE removes a collection with everything in it, in one request.
        if not recursive and any(True for _ in self._list_dir(path)):
            raise not_empty_error(self.uri_for(path))
        self._rmdir(path)

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        return self._relocate(source, source_path, path, move=False)

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        return self._relocate(source, source_path, path, move=True)

    def _relocate(self, source: StorageBackend, source_path: str, path: str, *, move: bool) -> bool:
        """COPY or MOVE on the server; ``False`` when it has to go through a staging file."""
        if not isinstance(source, WebDAVStorage) or source._client is not self._client:
            return False
        relocate = self._client.move if move else self._client.copy
        try:
            with _webdav_errors(self.uri_for(path)):
                relocate(source._remote(source_path), self._remote(path), overwrite=True)
        except StorageException as error:
            if _status_of(error) in _NO_SUCH_METHOD_STATUS:
                return False
            raise
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, WebDAVStorage)
            and other._client is self._client
            and other._root == self._root
        )

    def __hash__(self) -> int:
        return hash((WEBDAV_SCHEME, id(self._client), self._root))

    def __repr__(self) -> str:
        return f"WebDAVStorage({self.uri_for()!r})"
