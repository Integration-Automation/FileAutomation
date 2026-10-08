"""OneDrive backend: ``onedrive:///<path>``.

``OneDriveStorage()`` serves the signed-in user's drive (Microsoft Graph
``/me/drive``) through the shared
:data:`~automation_file.remote.onedrive.client.onedrive_instance`, which the
caller initialises as before (``onedrive_instance.later_init(access_token)``,
``device_code_login(...)`` or the ``FA_onedrive_*`` actions). ``root=`` confines
the backend to one folder of the drive. The URI authority is always empty.

Folders are real directories. OneDrive compares names without regard to case and
keeps the case they were written with, so ``Report.txt`` and ``report.txt`` are
one item; a move between two such spellings renames it.

A file up to 4 MiB goes up in one request, a larger one through an upload session
in fragments read from the file as they are sent. A download is streamed to the
target file. Writing to a path that holds a file replaces its content and keeps
the item, which is also what a copy or a move onto an existing file does. A move
to a new path between two locations of one client is done by OneDrive itself; a
copy goes through a local staging file. ``delete`` sends the item to the
recycle bin, a folder together with everything in it.

``stat`` reports the size, modification time, ETag and MIME type of a file.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import quote

from automation_file.exceptions import (
    OneDriveException,
    StorageException,
    StoragePathTypeException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.logging_config import file_automation_logger
from automation_file.storage.backend import (
    StorageBackend,
    guess_content_type,
    join_path,
    missing_error,
    not_empty_error,
    parent_of,
)
from automation_file.storage.timestamps import parse_rfc3339
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI, normalize_path

if TYPE_CHECKING:
    from automation_file.remote.onedrive.client import OneDriveClient

ONEDRIVE_SCHEME = "onedrive"
_DRIVE_ROOT = "/me/drive/root"
_CHILDREN = "/children"
_CONTENT = "/content"
_UPLOAD_SESSION = "/createUploadSession"
_ITEM_FIELDS = "id,name,size,lastModifiedDateTime,eTag,file,folder,parentReference"
_SELECT = "$select"
_TOP = "$top"
_PARENT_REFERENCE = "parentReference"
_FOLDER = "folder"
_ID = "id"
_NAME = "name"
_GET = "GET"
_PUT = "PUT"
_POST = "POST"
_PATCH = "PATCH"
_DELETE = "DELETE"
_NEXT_LINK = "@odata.nextLink"
_CONFLICT_BEHAVIOR = "@microsoft.graph.conflictBehavior"
_DEFAULT_MIME_TYPE = "application/octet-stream"
_HTTPS = "https://"
# Graph takes a whole file in one PUT up to this size; larger ones need an upload session.
_SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024
# Every fragment of an upload session but the last must be a multiple of 320 KiB.
_UPLOAD_FRAGMENT_UNIT = 320 * 1024
_UPLOAD_CHUNK_SIZE = 32 * _UPLOAD_FRAGMENT_UNIT
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
_TRANSFER_TIMEOUT = 120.0
_OK_STATUS = range(200, 300)
_UPLOAD_DONE_STATUS = frozenset({200, 201})
_NOT_FOUND = 404
_CONFLICT = 409
_DENIED_STATUS = frozenset({401, 403})
_RETRY_STATUS = frozenset({408, 429})
_SERVER_ERROR = 500
_NO_STATUS: frozenset[int] = frozenset()
_MISSING_OK = frozenset({_NOT_FOUND})
_MKDIR_TOLERATED = frozenset({_NOT_FOUND, _CONFLICT})
_ERROR_CODE_LIMIT = 64
_NOT_INSTALLED = "requests is not installed; the OneDrive backend needs it"
_SAME_FILE = "source and target are the same file"

_Item = dict[str, Any]


@contextlib.contextmanager
def _transport_errors(location: str, *, chain_cause: bool = True) -> Iterator[None]:
    """Turn the errors of ``requests`` into the storage layer's exceptions.

    ``chain_cause=False`` is for requests that reach a pre-authenticated URL (an
    upload session, the redirect of a download): the text of a ``requests`` error
    quotes the URL, so that error is not kept as the cause.
    """
    try:
        import requests
    except ImportError as error:
        raise StorageUnavailableException(_NOT_INSTALLED) from error
    dropped = (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )
    try:
        yield
    except requests.RequestException as error:
        transient = isinstance(error, dropped) and not isinstance(
            error, requests.exceptions.SSLError
        )
        kind = StorageTransientException if transient else StorageException
        raise kind(f"{location}: {type(error).__name__}") from (error if chain_cause else None)


def _error_code(response: Any) -> str:
    """Return the ``error.code`` of a Graph error body (empty when there is none)."""
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return ""
    return code[:_ERROR_CODE_LIMIT] if isinstance(code, str) else ""


def _failure(response: Any, location: str) -> StorageException:
    """Return the storage exception a failed Graph response stands for."""
    status = int(response.status_code)
    detail = f"{status} {_error_code(response)}".strip()
    if status == _NOT_FOUND:
        return missing_error(location)
    if status in _DENIED_STATUS:
        return StoragePermissionException(f"access to {location} was denied ({detail})")
    if status in _RETRY_STATUS or status >= _SERVER_ERROR:
        return StorageTransientException(f"{location}: OneDrive answered {detail}")
    return StorageException(f"{location}: OneDrive error {detail}")


def _document(response: Any, location: str) -> _Item:
    """Return the JSON object in the body of ``response``."""
    try:
        document = response.json()
    except ValueError as error:
        raise StorageException(
            f"{location}: OneDrive answered with a body that is not JSON"
        ) from error
    if not isinstance(document, dict):
        raise StorageException(f"{location}: OneDrive answered with an unexpected JSON value")
    return document


def _leaf(path: str) -> str:
    return path.rpartition("/")[2]


def _is_same_item(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """Say whether two driveItem resources are one item of one drive."""

    def identity(item: Mapping[str, Any]) -> tuple[Any, Any]:
        reference = item.get(_PARENT_REFERENCE)
        drive = reference.get("driveId") if isinstance(reference, Mapping) else None
        return drive, item.get(_ID)

    return first.get(_ID) is not None and identity(first) == identity(second)


def _item_info(path: str, item: Mapping[str, Any]) -> FileInfo:
    modified_at = parse_rfc3339(item.get("lastModifiedDateTime"))
    if _FOLDER in item:
        return FileInfo(path=path, is_dir=True, modified_at=modified_at)
    etag = item.get("eTag")
    facet = item.get("file")
    return FileInfo(
        path=path,
        size=int(item.get("size") or 0),
        modified_at=modified_at,
        etag=str(etag).strip('"') if etag else None,
        content_type=facet.get("mimeType") if isinstance(facet, Mapping) else None,
    )


class OneDriveStorage(StorageBackend):
    """The signed-in user's OneDrive, whole or confined to the folder ``root``."""

    scheme = ONEDRIVE_SCHEME
    capabilities = StorageCapabilities(
        directories=True, modified_at=True, etag=True, content_type=True
    )

    def __init__(self, client: OneDriveClient | None = None, *, root: str = "") -> None:
        self._explicit_client = client
        self._root = normalize_path(root)

    @property
    def root(self) -> str:
        """The folder this backend is confined to (empty for the whole drive)."""
        return self._root

    @property
    def _client(self) -> OneDriveClient:
        client = self._explicit_client
        if client is None:
            from automation_file.remote.onedrive.client import onedrive_instance

            client = onedrive_instance
        try:
            client.require_session()
        except OneDriveException as error:
            raise StorageUnavailableException(
                "the OneDrive client is not initialised; call onedrive_instance.later_init() "
                "or device_code_login(), or pass client= to OneDriveStorage"
            ) from error
        return client

    def uri_for(self, path: str = "") -> str:
        return str(StorageURI(ONEDRIVE_SCHEME, "", self._drive_path(self._normalize(path))))

    # ------------------------------------------------------------------ talking to Graph

    def _drive_path(self, path: str) -> str:
        """Return ``path`` relative to the root of the drive."""
        return join_path(self._root, path) if path else self._root

    def _item_url(self, path: str, facet: str = "") -> str:
        """Return the Graph path of the item ``path``, or of one of its facets (``/children``)."""
        drive_path = self._drive_path(path)
        if not drive_path:
            return f"{_DRIVE_ROOT}{facet}"
        address = f"{_DRIVE_ROOT}:/{quote(drive_path, safe='/')}"
        return f"{address}:{facet}" if facet else address

    def _send(
        self,
        method: str,
        target: str,
        location: str,
        *,
        tolerate: frozenset[int] = _NO_STATUS,
        chain_cause: bool = True,
        **options: Any,
    ) -> Any:
        """Send one request through the client and return the response.

        A status outside 2xx and outside ``tolerate`` raises the storage exception
        it stands for.
        """
        client = self._client
        with _transport_errors(location, chain_cause=chain_cause):
            response = client.graph_send(method, target, **options)
        if response.status_code in _OK_STATUS or response.status_code in tolerate:
            return response
        failure = _failure(response, location)
        response.close()
        raise failure

    def _item(self, path: str) -> _Item | None:
        """Return the driveItem at ``path``, or ``None`` when nothing is there."""
        location = self.uri_for(path)
        response = self._send(
            _GET,
            self._item_url(path),
            location,
            tolerate=_MISSING_OK,
            params={_SELECT: _ITEM_FIELDS},
        )
        return None if response.status_code == _NOT_FOUND else _document(response, location)

    def _existing_item(self, path: str) -> _Item:
        item = self._item(path)
        if item is None:
            raise missing_error(self.uri_for(path))
        return item

    # ------------------------------------------------------------------ StorageBackend primitives

    def _stat(self, path: str) -> FileInfo | None:
        item = self._item(path)
        return None if item is None else _item_info(path, item)

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        location = self.uri_for(path)
        found: list[FileInfo] = []
        target: str | None = self._item_url(path, _CHILDREN)
        options: dict[str, Any] = {"params": {_SELECT: _ITEM_FIELDS}}
        while target:
            page = _document(self._send(_GET, target, location, **options), location)
            found.extend(
                _item_info(join_path(path, str(item[_NAME])), item)
                for item in page.get("value", [])
                if item.get(_NAME)
            )
            # The link to the next page is a full URL that carries the query of this one.
            following = page.get(_NEXT_LINK)
            target = following if isinstance(following, str) else None
            options = {}
        return found

    def _upload(self, source: Path, path: str) -> None:
        location = self.uri_for(path)
        with open(source, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size > _SIMPLE_UPLOAD_MAX:
                self._upload_in_session(handle, size, path, location)
                return
            self._send(
                _PUT,
                self._item_url(path, _CONTENT),
                location,
                # Bytes, not the handle: requests would send an empty stream chunked.
                data=handle.read(),
                headers={"Content-Type": guess_content_type(path) or _DEFAULT_MIME_TYPE},
                timeout=_TRANSFER_TIMEOUT,
            )

    def _upload_in_session(self, handle: BinaryIO, size: int, path: str, location: str) -> None:
        opened = self._send(
            _POST,
            self._item_url(path, _UPLOAD_SESSION),
            location,
            json={"item": {_CONFLICT_BEHAVIOR: "replace"}},
        )
        upload_url = _document(opened, location).get("uploadUrl")
        if not isinstance(upload_url, str) or not upload_url.startswith(_HTTPS):
            raise StorageException(f"{location}: OneDrive opened an upload session without a URL")
        completed = False
        try:
            self._send_fragments(handle, size, upload_url, location)
            completed = True
        finally:
            if not completed:
                self._cancel_session(upload_url, location)

    def _send_fragments(self, handle: BinaryIO, size: int, upload_url: str, location: str) -> None:
        sent = 0
        status = 0
        while sent < size:
            fragment = handle.read(min(_UPLOAD_CHUNK_SIZE, size - sent))
            if not fragment:
                raise StorageException(f"{location}: the local source shrank during the upload")
            end = sent + len(fragment)
            # The upload URL is pre-authenticated: it gets no bearer token and stays out of errors.
            status = self._send(
                _PUT,
                upload_url,
                location,
                chain_cause=False,
                authorized=False,
                data=fragment,
                headers={"Content-Range": f"bytes {sent}-{end - 1}/{size}"},
                timeout=_TRANSFER_TIMEOUT,
            ).status_code
            sent = end
        if status not in _UPLOAD_DONE_STATUS:
            raise StorageException(
                f"{location}: OneDrive did not complete the upload session ({status})"
            )

    def _cancel_session(self, upload_url: str, location: str) -> None:
        try:
            self._send(_DELETE, upload_url, location, chain_cause=False, authorized=False)
        except StorageException as error:
            file_automation_logger.warning(
                "OneDriveStorage: the upload session for %s could not be cancelled (%s); "
                "it expires on its own",
                location,
                type(error).__name__,
            )

    def _download(self, path: str, target: Path) -> None:
        location = self.uri_for(path)
        # Graph redirects to a pre-authenticated download URL, so no error keeps its cause.
        response = self._send(
            _GET,
            self._item_url(path, _CONTENT),
            location,
            chain_cause=False,
            stream=True,
            timeout=_TRANSFER_TIMEOUT,
        )
        with (
            response,
            _transport_errors(location, chain_cause=False),
            open(target, "wb") as handle,
        ):
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                handle.write(chunk)

    def _delete_file(self, path: str) -> None:
        self._send(_DELETE, self._item_url(path), self.uri_for(path))

    def _mkdir(self, path: str) -> None:
        location = self.uri_for(path)
        response = self._send(
            _POST,
            self._item_url(parent_of(path), _CHILDREN),
            location,
            tolerate=_MKDIR_TOLERATED,
            json={_NAME: _leaf(path), _FOLDER: {}, _CONFLICT_BEHAVIOR: "fail"},
        )
        if response.status_code == _NOT_FOUND:
            # Only the folder ``root=`` names can be missing here: the caller made the others.
            raise missing_error(self.uri_for(parent_of(path)))
        if response.status_code != _CONFLICT:
            return
        existing = self._item(path)
        if existing is None:
            raise StorageException(f"{location}: OneDrive reported a name conflict")
        if _FOLDER not in existing:
            raise StoragePathTypeException(f"{location} is a file")

    def _delete_directory(self, path: str, recursive: bool) -> None:
        location = self.uri_for(path)
        if not recursive:
            # OneDrive removes a folder with everything in it, so "empty" is checked here.
            page = self._send(
                _GET,
                self._item_url(path, _CHILDREN),
                location,
                params={_SELECT: _ID, _TOP: 1},
            )
            if _document(page, location).get("value"):
                raise not_empty_error(location)
        self._send(_DELETE, self._item_url(path), location)

    # ------------------------------------------------------------------ copy and move inside OneDrive

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if isinstance(source, OneDriveStorage):
            existing = self._item(path)
            # Two roots, or two spellings, can name one item: copying it onto itself is refused.
            if existing is not None and _is_same_item(source._existing_item(source_path), existing):
                raise StorageException(f"{self.uri_for(path)}: {_SAME_FILE}")
        return False

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, OneDriveStorage):
            return False
        location = self.uri_for(path)
        one_client = source._client is self._client
        existing = self._item(path)
        if existing is not None:
            if not _is_same_item(source._existing_item(source_path), existing):
                # Another file is there: it is replaced in place by a staged copy.
                return False
            respelled = source._drive_path(source_path) != self._drive_path(path)
            if not (one_client and respelled):
                raise StorageException(f"{location}: {_SAME_FILE}")
        elif not one_client:
            return False
        folder = self._existing_item(parent_of(path))
        self._send(
            _PATCH,
            source._item_url(source_path),
            location,
            json={_PARENT_REFERENCE: {_ID: folder[_ID]}, _NAME: _leaf(path)},
        )
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, OneDriveStorage)
            and other._root == self._root
            and other._explicit_client is self._explicit_client
        )

    def __hash__(self) -> int:
        return hash((ONEDRIVE_SCHEME, self._root, id(self._explicit_client)))

    def __repr__(self) -> str:
        return f"OneDriveStorage(root={self._root!r})"


def onedrive_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    """Scheme factory for ``onedrive:///<path>`` on the shared ``onedrive_instance``."""
    if uri.authority:
        intended = StorageURI(ONEDRIVE_SCHEME, "", join_path(uri.authority, uri.path))
        raise StorageURIException(
            f"{str(uri)!r} names {uri.authority!r} as its authority; a OneDrive URI addresses "
            f"the signed-in user's drive and takes an empty one, as in '{intended}'"
        )
    return OneDriveStorage(), uri.path
