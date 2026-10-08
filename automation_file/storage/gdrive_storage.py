"""Google Drive backend: ``gdrive://<root>/<path>``.

``GoogleDriveStorage()`` serves My Drive through the shared
:data:`~automation_file.remote.google_drive.client.driver_instance`, which the
caller initialises as before (``driver_instance.later_init(token_path,
credentials_path)`` or ``FA_drive_later_init``). ``root_id=`` makes another
folder, or a shared drive, the root; in a URI that ID is the authority
(``gdrive://<folder-id>/q1.csv``), and an empty authority or ``root`` is My Drive.

Drive addresses entries by ID and lets several entries in one folder carry the
same name, so a path is resolved one segment at a time, on every call:

* A name that two or more entries of a folder share cannot be addressed. The
  call raises :class:`~automation_file.exceptions.StorageException` with the
  count; it never picks one. A listing still shows each of them.
* A name that contains ``/`` cannot be addressed either and is left out of
  listings.
* Entries in the trash do not exist as far as this backend is concerned.

Folders are real directories. Writing to a path that holds a file uploads a new
revision of that file, so its ID, links and sharing stay; this is also what a
copy or a move onto an existing file does. A copy or a move to a new path
between two locations of one client is done by Drive itself. ``delete`` removes
permanently, without the trash, and a folder goes with everything in it.

Google Docs, Sheets, Slides and the other ``application/vnd.google-apps.*``
types have no binary content: they are listed with ``size=None`` and can be
moved, copied and deleted, but ``download``, ``read_bytes`` and ``checksum``
raise :class:`~automation_file.exceptions.StorageUnsupportedException`.
"""

# pylint: disable=protected-access  # a backend reads the private parts of another instance of its own kind

from __future__ import annotations

import contextlib
import json
import ssl
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePathTypeException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageUnsupportedException,
)
from automation_file.logging_config import file_automation_logger
from automation_file.storage.backend import (
    StorageBackend,
    guess_content_type,
    join_path,
    missing_error,
    not_a_file_error,
    not_empty_error,
    parent_of,
)
from automation_file.storage.timestamps import parse_rfc3339
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI

if TYPE_CHECKING:
    from automation_file.remote.google_drive.client import GoogleDriveClient

GDRIVE_SCHEME = "gdrive"
MY_DRIVE = "root"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_WORKSPACE_PREFIX = "application/vnd.google-apps."
_DEFAULT_MIME_TYPE = "application/octet-stream"
_ENTRY_FIELDS = (
    "id, name, mimeType, size, modifiedTime, md5Checksum, sha1Checksum, sha256Checksum, "
    "version, parents"
)
_LIST_FIELDS = f"nextPageToken, files({_ENTRY_FIELDS})"
_ROOT_FIELDS = "id, name, mimeType, modifiedTime, trashed"
_ID = "id"
_NAME = "name"
_MIME_TYPE = "mimeType"
_PARENTS = "parents"
_PAGE_SIZE = 1000
_DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_NOT_FOUND = 404
_FORBIDDEN = 403
_DENIED_STATUS = frozenset({401, _FORBIDDEN})
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500
# The reasons googleapiclient itself retries a 403 for.
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
# hashlib name -> the Drive field that carries that digest of a file's content.
_SERVER_DIGESTS = {"md5": "md5Checksum", "sha1": "sha1Checksum", "sha256": "sha256Checksum"}
_NOT_INSTALLED = "google-api-python-client is not installed; the Google Drive backend needs it"
_SAME_FILE = "source and target are the same file"

_Entry = dict[str, Any]


def _error_reasons(error: Any) -> set[str]:
    """Return the ``reason`` codes in the error body Drive sent (none when it is not JSON)."""
    try:
        entries = json.loads(error.content.decode("utf-8"))["error"]["errors"]
    except (AttributeError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return set()
    if not isinstance(entries, list):
        return set()
    return {
        str(entry["reason"]) for entry in entries if isinstance(entry, dict) and entry.get("reason")
    }


def _translated(error: Any, location: str) -> StorageException:
    """Turn a ``googleapiclient`` ``HttpError`` into the storage exception it stands for."""
    status = int(error.resp.status)
    reasons = _error_reasons(error)
    detail = " ".join([str(status), *sorted(reasons)])
    if status == _NOT_FOUND:
        return missing_error(location)
    throttled = status == _FORBIDDEN and bool(reasons & _RATE_LIMIT_REASONS)
    if throttled or status == _TOO_MANY_REQUESTS or status >= _SERVER_ERROR:
        return StorageTransientException(f"{location}: Google Drive answered {detail}")
    if status in _DENIED_STATUS:
        return StoragePermissionException(f"access to {location} was denied ({detail})")
    return StorageException(f"{location}: Google Drive error {detail}")


@contextlib.contextmanager
def _drive_errors(location: str) -> Iterator[None]:
    """Turn googleapiclient, google-auth and transport errors into the storage layer's exceptions.

    A message carries the status and Drive's reason codes, never the text of the
    SDK error: that text quotes the request URL. The SDK error stays the cause.
    """
    try:
        import httplib2
        from google.auth import exceptions as auth_errors
        from googleapiclient import errors as api_errors
    except ImportError as error:
        raise StorageUnavailableException(_NOT_INSTALLED) from error
    try:
        yield
    except api_errors.HttpError as error:
        raise _translated(error, location) from error
    except auth_errors.RefreshError as error:
        raise StoragePermissionException(
            f"access to {location} was denied: the Google credentials could not be refreshed"
        ) from error
    except ssl.SSLCertVerificationError as error:
        raise StorageException(f"{location}: {type(error).__name__}") from error
    except (
        auth_errors.TransportError,
        httplib2.ServerNotFoundError,
        ssl.SSLError,
        ConnectionError,
        TimeoutError,
    ) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error
    except (api_errors.Error, auth_errors.GoogleAuthError, httplib2.HttpLib2Error) as error:
        raise StorageException(f"{location}: {type(error).__name__}") from error


def _quoted(value: str) -> str:
    """Return ``value`` as a string literal of the Drive query language."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _children_query(folder_id: str, name: str | None = None) -> str:
    """Return the query for what a folder holds outside the trash, or for one name in it."""
    named = "" if name is None else f" and name = {_quoted(name)}"
    return f"{_quoted(folder_id)} in parents{named} and trashed = false"


def _leaf(path: str) -> str:
    return path.rpartition("/")[2]


def _is_folder(entry: Mapping[str, Any]) -> bool:
    return entry.get(_MIME_TYPE) == FOLDER_MIME_TYPE


def _is_workspace_document(entry: Mapping[str, Any]) -> bool:
    """Say whether ``entry`` is a Docs / Sheets / Slides style entry without binary content."""
    return str(entry.get(_MIME_TYPE) or "").startswith(_WORKSPACE_PREFIX) and not _is_folder(entry)


def _is_addressable(name: str) -> bool:
    """Say whether a Drive name can be one segment of a storage path."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\x00" not in name


def _file_info(path: str, entry: Mapping[str, Any]) -> FileInfo:
    modified_at = parse_rfc3339(entry.get("modifiedTime"))
    if _is_folder(entry):
        return FileInfo(path=path, is_dir=True, modified_at=modified_at)
    size = entry.get("size")
    version = entry.get("version")
    return FileInfo(
        path=path,
        # Drive reports a storage size for Workspace documents; it is not a content length.
        size=None if size is None or _is_workspace_document(entry) else int(size),
        modified_at=modified_at,
        etag=entry.get("md5Checksum"),
        version=None if version is None else str(version),
        content_type=entry.get(_MIME_TYPE),
    )


class GoogleDriveStorage(StorageBackend):
    """My Drive, or the tree below the folder (or shared drive) ``root_id``."""

    scheme = GDRIVE_SCHEME
    capabilities = StorageCapabilities(
        directories=True, modified_at=True, etag=True, version=True, content_type=True
    )

    def __init__(self, client: GoogleDriveClient | None = None, *, root_id: str = MY_DRIVE) -> None:
        self._explicit_client = client
        self._root_id = root_id.strip() or MY_DRIVE
        # The ID is the authority of this backend's URIs, so it has to be usable as one.
        StorageURI(GDRIVE_SCHEME, self._root_id)

    @property
    def root_id(self) -> str:
        """The ID of the folder this backend treats as its root (``root`` is My Drive)."""
        return self._root_id

    @property
    def _service(self) -> Any:
        client = self._explicit_client
        if client is None:
            from automation_file.remote.google_drive.client import driver_instance

            client = driver_instance
        try:
            return client.require_service()
        except RuntimeError as error:
            raise StorageUnavailableException(
                "the Google Drive client is not initialised; call "
                "driver_instance.later_init(token_path, credentials_path) "
                "or pass client= to GoogleDriveStorage"
            ) from error

    def uri_for(self, path: str = "") -> str:
        authority = "" if self._root_id == MY_DRIVE else self._root_id
        return str(StorageURI(GDRIVE_SCHEME, authority, self._normalize(path)))

    # ------------------------------------------------------------------ resolving paths

    def _matches(self, query: str, location: str, *, first_only: bool = False) -> list[_Entry]:
        """Return the entries ``query`` selects, reading every page (or until one is found)."""
        files = self._service.files()
        found: list[_Entry] = []
        token: str | None = None
        with _drive_errors(location):
            while True:
                page = files.list(
                    q=query,
                    fields=_LIST_FIELDS,
                    pageSize=1 if first_only else _PAGE_SIZE,
                    pageToken=token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                found.extend(page.get("files", []))
                token = page.get("nextPageToken")
                if not token or (first_only and found):
                    return found

    def _child(self, folder_id: str, name: str, location: str) -> _Entry | None:
        """Return the entry called ``name`` in the folder, or ``None``; refuse a shared name."""
        found = self._matches(_children_query(folder_id, name), location)
        # Compared again here: the query's "=" is not relied on to tell upper from lower case.
        matches = [entry for entry in found if entry.get(_NAME) == name]
        if len(matches) > 1:
            raise StorageException(
                f"{location}: {len(matches)} entries share the name {name!r} in that Google Drive "
                "folder, so the path does not say which one is meant; rename or remove the others"
            )
        return matches[0] if matches else None

    def _root_entry(self) -> _Entry | None:
        with _drive_errors(self.uri_for("")):
            entry: _Entry = (
                self._service.files()
                .get(fileId=self._root_id, fields=_ROOT_FIELDS, supportsAllDrives=True)
                .execute()
            )
        return None if entry.get("trashed") else entry

    def _descend(self, path: str) -> _Entry | None:
        folder_id = self._root_id
        entry: _Entry | None = None
        walked = ""
        for name in path.split("/"):
            if entry is not None and not _is_folder(entry):
                return None
            walked = join_path(walked, name)
            entry = self._child(folder_id, name, self.uri_for(walked))
            if entry is None:
                return None
            folder_id = str(entry[_ID])
        return entry

    def _entry(self, path: str) -> _Entry | None:
        """Return the Drive resource at ``path``, or ``None`` when nothing is there."""
        try:
            return self._descend(path) if path else self._root_entry()
        except StorageNotFoundException:
            # The root, or a folder on the way, is gone: nothing exists below it.
            return None

    def _existing(self, path: str) -> _Entry:
        entry = self._entry(path)
        if entry is None:
            raise missing_error(self.uri_for(path))
        return entry

    def _folder_id(self, path: str) -> str:
        """Return the ID of the existing folder ``path``."""
        if not path:
            return self._root_id
        entry = self._existing(path)
        if not _is_folder(entry):
            raise StoragePathTypeException(f"{self.uri_for(path)} is not a directory")
        return str(entry[_ID])

    def _content_entry(self, path: str) -> _Entry:
        """Return the entry of the file ``path``, which must have binary content."""
        location = self.uri_for(path)
        entry = self._existing(path)
        if _is_folder(entry):
            raise not_a_file_error(location)
        if _is_workspace_document(entry):
            raise StorageUnsupportedException(
                f"{location} is a Google Workspace document ({entry.get(_MIME_TYPE)}): it has no "
                "binary content to download, read or hash"
            )
        return entry

    def _scan(self, folder_id: str, path: str) -> list[tuple[str, _Entry]]:
        """Return ``(path, entry)`` for every addressable child of the folder at ``path``."""
        location = self.uri_for(path)
        found: list[tuple[str, _Entry]] = []
        for entry in self._matches(_children_query(folder_id), location):
            name = str(entry.get(_NAME) or "")
            if _is_addressable(name):
                found.append((join_path(path, name), entry))
            else:
                file_automation_logger.warning(
                    "GoogleDriveStorage: %s holds an entry named %r that no path can address; "
                    "it is left out of the listing",
                    location,
                    name,
                )
        return found

    # ------------------------------------------------------------------ StorageBackend primitives

    def _stat(self, path: str) -> FileInfo | None:
        entry = self._entry(path)
        return None if entry is None else _file_info(path, entry)

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        return [
            _file_info(child, entry) for child, entry in self._scan(self._folder_id(path), path)
        ]

    def _walk(self, path: str) -> Iterable[FileInfo]:
        # By ID, not by path: one listing per folder, and two folders of one name are both read.
        found: list[FileInfo] = []
        pending = [(self._folder_id(path), path)]
        while pending:
            folder_id, base = pending.pop()
            for child, entry in self._scan(folder_id, base):
                found.append(_file_info(child, entry))
                if _is_folder(entry):
                    pending.append((str(entry[_ID]), child))
        return found

    def _upload(self, source: Path, path: str) -> None:
        location = self.uri_for(path)
        name = _leaf(path)
        folder_id = self._folder_id(parent_of(path))
        existing = self._child(folder_id, name, location)
        if existing is not None and _is_folder(existing):
            raise not_a_file_error(location)
        if existing is not None and _is_workspace_document(existing):
            raise StorageUnsupportedException(
                f"{location} is a Google Workspace document ({existing.get(_MIME_TYPE)}); "
                "a file cannot replace it"
            )
        mime_type = guess_content_type(name) or _DEFAULT_MIME_TYPE
        files = self._service.files()
        with _drive_errors(location):
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(str(source), mimetype=mime_type, resumable=True)
            try:
                if existing is None:
                    request = files.create(
                        body={_NAME: name, _PARENTS: [folder_id], _MIME_TYPE: mime_type},
                        media_body=media,
                        fields=_ID,
                        supportsAllDrives=True,
                    )
                else:
                    # A new revision of the same file: its ID, links and sharing stay.
                    request = files.update(
                        fileId=existing[_ID],
                        media_body=media,
                        fields=_ID,
                        supportsAllDrives=True,
                    )
                request.execute()
            finally:
                # MediaFileUpload only closes its file when it is collected, and an error
                # in flight keeps it alive: on Windows the source could not be removed.
                media.stream().close()

    def _download(self, path: str, target: Path) -> None:
        location = self.uri_for(path)
        entry = self._content_entry(path)
        files = self._service.files()
        with _drive_errors(location), open(target, "wb") as handle:
            from googleapiclient.http import MediaIoBaseDownload

            request = files.get_media(fileId=entry[_ID], supportsAllDrives=True)
            downloader = MediaIoBaseDownload(handle, request, chunksize=_DOWNLOAD_CHUNK_SIZE)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    def _checksum(self, path: str, algorithm: str) -> str:
        entry = self._content_entry(path)
        digest = entry.get(_SERVER_DIGESTS.get(algorithm, ""))
        return str(digest).lower() if digest else super()._checksum(path, algorithm)

    def _remove(self, file_id: str, location: str) -> None:
        with _drive_errors(location):
            self._service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

    def _delete_file(self, path: str) -> None:
        self._remove(str(self._existing(path)[_ID]), self.uri_for(path))

    def _mkdir(self, path: str) -> None:
        location = self.uri_for(path)
        name = _leaf(path)
        folder_id = self._folder_id(parent_of(path))
        existing = self._child(folder_id, name, location)
        if existing is not None:
            if not _is_folder(existing):
                raise StoragePathTypeException(f"{location} is a file")
            return
        with _drive_errors(location):
            self._service.files().create(
                body={_NAME: name, _MIME_TYPE: FOLDER_MIME_TYPE, _PARENTS: [folder_id]},
                fields=_ID,
                supportsAllDrives=True,
            ).execute()

    def _delete_directory(self, path: str, recursive: bool) -> None:
        location = self.uri_for(path)
        folder_id = self._folder_id(path)
        # Drive removes a folder with everything in it, so "empty" is checked here, against
        # every child and not only the ones a path can address.
        if not recursive and self._matches(_children_query(folder_id), location, first_only=True):
            raise not_empty_error(location)
        self._remove(folder_id, location)

    # ------------------------------------------------------------------ copy and move inside Drive

    def _native_transfer(
        self, source: StorageBackend, source_path: str, path: str
    ) -> tuple[_Entry, str] | None:
        """Return the source entry and the target folder's ID when Drive can do the transfer.

        ``None`` sends the caller through a staged copy: the source is another backend
        or another client, or the target exists and is replaced in place to keep its ID.
        """
        if not isinstance(source, GoogleDriveStorage):
            return None
        location = self.uri_for(path)
        origin = source._existing(source_path)
        folder_id = self._folder_id(parent_of(path))
        existing = self._child(folder_id, _leaf(path), location)
        if existing is not None:
            # Two roots can show one file under two paths; replacing it with itself and
            # then deleting the "source" would lose it.
            if existing[_ID] == origin[_ID]:
                raise StorageException(f"{location}: {_SAME_FILE}")
            return None
        if source._service is not self._service:
            return None
        return origin, folder_id

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        transfer = self._native_transfer(source, source_path, path)
        if transfer is None:
            return False
        origin, folder_id = transfer
        with _drive_errors(self.uri_for(path)):
            self._service.files().copy(
                fileId=origin[_ID],
                body={_NAME: _leaf(path), _PARENTS: [folder_id]},
                fields=_ID,
                supportsAllDrives=True,
            ).execute()
        return True

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        transfer = self._native_transfer(source, source_path, path)
        if transfer is None:
            return False
        origin, folder_id = transfer
        location = self.uri_for(path)
        files = self._service.files()
        with _drive_errors(location):
            if folder_id == MY_DRIVE:
                # "parents" holds real IDs, so the alias is resolved before the two are compared.
                my_drive = files.get(fileId=MY_DRIVE, fields=_ID, supportsAllDrives=True)
                folder_id = str(my_drive.execute()[_ID])
            parents = [str(parent) for parent in origin.get(_PARENTS) or []]
            moved: dict[str, str] = {}
            if folder_id not in parents:
                moved["addParents"] = folder_id
                if parents:
                    moved["removeParents"] = ",".join(parents)
            files.update(
                fileId=origin[_ID],
                body={_NAME: _leaf(path)},
                fields=_ID,
                supportsAllDrives=True,
                **moved,
            ).execute()
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, GoogleDriveStorage)
            and other._root_id == self._root_id
            and other._explicit_client is self._explicit_client
        )

    def __hash__(self) -> int:
        return hash((GDRIVE_SCHEME, self._root_id, id(self._explicit_client)))

    def __repr__(self) -> str:
        return f"GoogleDriveStorage(root_id={self._root_id!r})"


def gdrive_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    """Scheme factory for ``gdrive://<root>/<path>`` on the shared ``driver_instance``.

    The authority is the ID of the root folder; empty or ``root`` means My Drive.
    """
    return GoogleDriveStorage(root_id=uri.authority or MY_DRIVE), uri.path
