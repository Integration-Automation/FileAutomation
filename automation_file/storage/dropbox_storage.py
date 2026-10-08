"""Dropbox backend: ``dropbox:///<path>``.

``DropboxStorage()`` serves the Dropbox of the shared
:data:`~automation_file.remote.dropbox_api.client.dropbox_instance`, which the
caller initialises as before (``dropbox_instance.later_init(token)`` or
``FA_dropbox_later_init``). Pass ``client=`` to use another ``dropbox.Dropbox``
client and ``root=`` to confine the backend to one folder.

Folders are real directories. ``stat`` reports the size, the server's
modification time, the revision as ``version`` and Dropbox's content hash as
``etag``. A file larger than :data:`UPLOAD_SESSION_THRESHOLD` goes up through an
upload session, :data:`UPLOAD_CHUNK_SIZE` bytes at a time, so it is never held in
memory as a whole.

Dropbox never replaces a file on copy or move: when the target exists it is
deleted first, then the copy or move runs.
"""

# pylint: disable=protected-access  # a backend reads the private parts of another instance of its own kind

from __future__ import annotations

import contextlib
from collections.abc import Callable, Hashable, Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.storage.backend import (
    StorageBackend,
    join_path,
    missing_error,
    not_empty_error,
)
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI, normalize_path

DROPBOX_SCHEME = "dropbox"
#: The size of one piece of an upload session. Dropbox asks for a multiple of 4 MiB.
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
#: A file larger than this goes up through an upload session instead of one request.
UPLOAD_SESSION_THRESHOLD = UPLOAD_CHUNK_SIZE
_NOT_INSTALLED = "dropbox is not installed; the Dropbox backend needs it"
# The branches of a Dropbox error under which "not_found" means the path, not an upload session.
_LOOKUP_BRANCHES = frozenset({"path", "path_lookup", "from_lookup"})
_MISSING_TAG = "not_found"
_CONFLICT_TAG = "conflict"
_FILE_CONFLICT = (_CONFLICT_TAG, "file")
_DENIED_TAGS = frozenset(
    {"access_restricted", "no_permission", "no_write_permission", "restricted_content"}
)
_TRANSIENT_TAGS = frozenset({"internal_error", "too_many_write_operations"})
_DENIED_STATUS = frozenset({401, 403})
_TRANSIENT_STATUS = frozenset({408, 429})
_SERVER_ERROR = 500


def _tags(error: Any) -> tuple[str, ...]:
    """Return the tag of a Dropbox error union and of every union nested in it.

    ``GetMetadataError('path', LookupError('not_found'))`` gives ``("path", "not_found")``.
    """
    tags: list[str] = []
    value = error
    while value is not None:
        tag = getattr(value, "_tag", None)
        if tag is None:
            # UploadWriteFailed is a struct that carries its WriteError as ``reason``.
            value = getattr(value, "reason", None)
        else:
            tags.append(str(tag))
            value = getattr(value, "_value", None)
    return tuple(tags)


def _api_error(tags: tuple[str, ...], location: str) -> StorageException:
    """Translate the tags of a route error (a 409 answer) into a storage exception."""
    reason = "/".join(tags) or "unknown"
    leaf = tags[-1] if tags else ""
    if leaf == _MISSING_TAG and len(tags) > 1 and tags[-2] in _LOOKUP_BRANCHES:
        return missing_error(location)
    if leaf in _DENIED_TAGS:
        return StoragePermissionException(f"access to {location} was denied ({reason})")
    if leaf in _TRANSIENT_TAGS:
        return StorageTransientException(f"{location}: Dropbox answered {reason}")
    if _CONFLICT_TAG in tags:
        return StorageAlreadyExistsException(
            f"{location}: something is already at that path ({reason})"
        )
    return StorageException(f"{location}: Dropbox error {reason}")


def _http_error(error: Any, location: str) -> StorageException:
    """Translate an error of the HTTP layer: bad credentials, throttling, a server fault."""
    status = getattr(error, "status_code", None)
    tags = _tags(getattr(error, "error", None))
    if status in _DENIED_STATUS or (tags and tags[-1] in _DENIED_TAGS):
        return StoragePermissionException(f"access to {location} was denied ({status})")
    if status in _TRANSIENT_STATUS or (isinstance(status, int) and status >= _SERVER_ERROR):
        return StorageTransientException(f"{location}: Dropbox answered {status}")
    return StorageException(f"{location}: Dropbox answered {status}")


@contextlib.contextmanager
def _dropbox_errors(location: str) -> Iterator[None]:
    """Turn Dropbox SDK errors and dropped connections into the storage layer's exceptions."""
    try:
        from dropbox import exceptions as dropbox_errors
        from requests import exceptions as request_errors
    except ImportError as error:
        raise StorageUnavailableException(_NOT_INSTALLED) from error
    try:
        yield
    except dropbox_errors.ApiError as error:
        raise _api_error(_tags(error.error), location) from error
    except dropbox_errors.HttpError as error:
        raise _http_error(error, location) from error
    except dropbox_errors.DropboxException as error:
        raise StorageException(f"{location}: {type(error).__name__}") from error
    except (
        request_errors.ConnectionError,
        request_errors.Timeout,
        request_errors.ChunkedEncodingError,
    ) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error


def _dropbox_files() -> Any:
    """Return the ``dropbox.files`` module, which holds the SDK's data types."""
    try:
        from dropbox import files
    except ImportError as error:
        raise StorageUnavailableException(_NOT_INSTALLED) from error
    return files


def _utc(moment: Any) -> datetime | None:
    """Return a Dropbox timestamp, which the SDK hands over naive and in UTC, as aware UTC."""
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _file_info(path: str, metadata: Any, files: Any) -> FileInfo | None:
    """Describe a metadata entry; ``None`` for one that is neither a file nor a folder."""
    if isinstance(metadata, files.FolderMetadata):
        return FileInfo(path=path, is_dir=True)
    if isinstance(metadata, files.FileMetadata):
        return FileInfo(
            path=path,
            size=int(metadata.size),
            modified_at=_utc(metadata.server_modified),
            etag=metadata.content_hash,
            version=metadata.rev,
        )
    return None


def _upload_in_session(client: Any, files: Any, handle: BinaryIO, remote: str) -> None:
    """Send an open file to Dropbox one chunk at a time and commit it at ``remote``."""
    session = client.files_upload_session_start(handle.read(UPLOAD_CHUNK_SIZE))
    cursor = files.UploadSessionCursor(session_id=session.session_id, offset=handle.tell())
    pending = handle.read(UPLOAD_CHUNK_SIZE)
    # One chunk is read ahead, so the last one is known when it is sent.
    while following := handle.read(UPLOAD_CHUNK_SIZE):
        client.files_upload_session_append_v2(pending, cursor)
        cursor.offset += len(pending)
        pending = following
    commit = files.CommitInfo(path=remote, mode=files.WriteMode.overwrite)
    client.files_upload_session_finish(pending, cursor, commit)


class DropboxStorage(StorageBackend):
    """A Dropbox account, whole or confined to the folder ``root``."""

    scheme = DROPBOX_SCHEME
    capabilities = StorageCapabilities(directories=True, modified_at=True, etag=True, version=True)

    def __init__(self, client: Any = None, *, root: str = "") -> None:
        self._explicit_client = client
        self._root = normalize_path(root)

    @property
    def root(self) -> str:
        """The folder this backend is confined to (empty for the whole Dropbox)."""
        return self._root

    @property
    def _client(self) -> Any:
        if self._explicit_client is not None:
            return self._explicit_client
        from automation_file.remote.dropbox_api.client import dropbox_instance

        try:
            return dropbox_instance.require_client()
        except RuntimeError as error:
            raise StorageUnavailableException(
                "the Dropbox client is not initialised; call dropbox_instance.later_init() "
                "or pass client= to DropboxStorage"
            ) from error

    def _identity(self, path: str) -> Hashable:
        # Two roots of one account; Dropbox ignores case name a file by the same full path.
        return (DROPBOX_SCHEME, id(self._client), self._remote(path).lower())

    def uri_for(self, path: str = "") -> str:
        return str(StorageURI(DROPBOX_SCHEME, "", self._below_root(self._normalize(path))))

    def _below_root(self, path: str) -> str:
        return join_path(self._root, path) if path else self._root

    def _remote(self, path: str) -> str:
        """Return the Dropbox path of ``path``: empty for the account root, ``/a/b`` otherwise."""
        joined = self._below_root(path)
        return f"/{joined}" if joined else ""

    def _stat(self, path: str) -> FileInfo | None:
        remote = self._remote(path)
        if not remote:
            # The account root has no metadata of its own; it is always there.
            return FileInfo(path=path, is_dir=True)
        files = _dropbox_files()
        try:
            with _dropbox_errors(self.uri_for(path)):
                metadata = self._client.files_get_metadata(remote)
        except StorageNotFoundException:
            return None
        return _file_info(path, metadata, files)

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        files = _dropbox_files()
        with _dropbox_errors(self.uri_for(path)):
            page = self._client.files_list_folder(self._remote(path))
            entries = list(page.entries)
            while page.has_more:
                page = self._client.files_list_folder_continue(page.cursor)
                entries.extend(page.entries)
        described = (_file_info(join_path(path, entry.name), entry, files) for entry in entries)
        return [info for info in described if info is not None]

    def _upload(self, source: Path, path: str) -> None:
        files = _dropbox_files()
        remote = self._remote(path)
        with _dropbox_errors(self.uri_for(path)), open(source, "rb") as handle:
            if source.stat().st_size > UPLOAD_SESSION_THRESHOLD:
                _upload_in_session(self._client, files, handle, remote)
            else:
                self._client.files_upload(handle.read(), remote, mode=files.WriteMode.overwrite)

    def _download(self, path: str, target: Path) -> None:
        with _dropbox_errors(self.uri_for(path)):
            self._client.files_download_to_file(str(target), self._remote(path))

    def _delete_file(self, path: str) -> None:
        with _dropbox_errors(self.uri_for(path)):
            self._client.files_delete_v2(self._remote(path))

    def _mkdir(self, path: str) -> None:
        try:
            with _dropbox_errors(self.uri_for(path)):
                self._client.files_create_folder_v2(self._remote(path))
        except StorageAlreadyExistsException:
            existing = self._stat(path)
            if existing is None or not existing.is_dir:
                raise

    def _rmdir(self, path: str) -> None:
        # One call deletes a file or a folder, and a folder goes with everything in it.
        self._delete_file(path)

    def _delete_directory(self, path: str, recursive: bool) -> None:
        if not recursive and any(True for _ in self._list_dir(path)):
            raise not_empty_error(self.uri_for(path))
        self._rmdir(path)

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, DropboxStorage) or source._client is not self._client:
            return False
        self._relocate(self._client.files_copy_v2, source._remote(source_path), path)
        return True

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, DropboxStorage) or source._client is not self._client:
            return False
        self._relocate(self._client.files_move_v2, source._remote(source_path), path)
        return True

    def _relocate(self, relocate: Callable[[str, str], Any], origin: str, path: str) -> None:
        """Run a Dropbox copy or move to ``path``, replacing a file that is in the way."""
        location = self.uri_for(path)
        target = self._remote(path)
        try:
            with _dropbox_errors(location):
                relocate(origin, target)
            return
        except StorageAlreadyExistsException as error:
            # Only a file is ever removed to make room: deleting a folder takes its content.
            if _tags(getattr(error.__cause__, "error", None))[-2:] != _FILE_CONFLICT:
                raise
        with _dropbox_errors(location):
            if self._entry_id(origin) == self._entry_id(target):
                # Dropbox compares names without case, so another spelling is the same file.
                raise StorageException(f"{location}: source and target are the same file")
            self._client.files_delete_v2(target)
            relocate(origin, target)

    def _entry_id(self, remote: str) -> Any:
        """Return the identifier of the entry at ``remote``, the same for every spelling of it."""
        return getattr(self._client.files_get_metadata(remote), "id", None)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, DropboxStorage)
            and other._root == self._root
            and other._explicit_client is self._explicit_client
        )

    def __hash__(self) -> int:
        return hash((DROPBOX_SCHEME, self._root, id(self._explicit_client)))

    def __repr__(self) -> str:
        return f"DropboxStorage(root={self._root!r})"


def dropbox_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    """Serve ``dropbox:///<path>`` from the shared Dropbox client."""
    if uri.authority:
        correct = StorageURI(DROPBOX_SCHEME, "", f"{uri.authority}/{uri.path}")
        raise StorageURIException(
            f"{str(uri)!r} names the host {uri.authority!r}; a Dropbox path follows an empty "
            f"authority, as in {str(correct)!r}"
        )
    return DropboxStorage(), uri.path
