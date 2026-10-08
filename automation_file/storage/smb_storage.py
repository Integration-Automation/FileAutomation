"""SMB / CIFS backend, mounted on an :class:`~automation_file.remote.smb.client.SMBClient`.

The client carries the server, the share and the credentials, so there is no URI
factory: a backend is mounted where its files should appear.

.. code-block:: python

    client = SMBClient("nas.example.com", "projects", "user", password)
    Storage.mount("smb://nas.example.com/projects", SMBStorage(client))
    File("smb://nas.example.com/projects/2026/plan.docx").download_to("plan.docx")

Directories are real. ``stat`` reports the size and the modification time. A move
between two paths of one client is a rename on the server; a copy goes through a
local staging file.
"""

from __future__ import annotations

import contextlib
import errno
from collections.abc import Hashable, Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from automation_file.exceptions import (
    SMBException,
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
)
from automation_file.storage.backend import StorageBackend, join_path, missing_error
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI, normalize_path

if TYPE_CHECKING:
    from automation_file.remote.smb.client import SMBClient, SMBEntry

SMB_SCHEME = "smb"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MISSING_ERRNO = frozenset({errno.ENOENT, errno.ENOTDIR})
# NTSTATUS STATUS_ACCESS_DENIED, which smbprotocol passes on without an errno.
_STATUS_ACCESS_DENIED = 0xC0000022
_PROTOCOL_ERROR = ("SMBException",)
_LOGON_ERRORS = ("AccessDenied", "LogonFailure", "SMBAuthenticationError")
_SELF_AND_PARENT = frozenset({".", ".."})
_MAX_CAUSES = 5


def _protocol_errors(names: Iterable[str]) -> tuple[type[BaseException], ...]:
    """Return the named ``smbprotocol.exceptions`` classes this installation has."""
    try:
        from smbprotocol import exceptions as smb_errors
    except ImportError:
        # Without smbprotocol none of its errors can have been raised.
        return ()
    found = (getattr(smb_errors, name, None) for name in names)
    return tuple(error for error in found if isinstance(error, type))


def _causes(error: BaseException) -> list[BaseException]:
    """Return ``error`` and the errors it was raised from, outermost first."""
    found: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(found) < _MAX_CAUSES:
        found.append(current)
        current = current.__cause__
    return found


def _is_missing(error: BaseException) -> bool:
    # smbprotocol raises an OSError subclass of its own, so the errno decides.
    return (
        isinstance(error, (FileNotFoundError, NotADirectoryError))
        or getattr(error, "errno", None) in _MISSING_ERRNO
    )


def _is_denied(error: BaseException, logon_errors: tuple[type[BaseException], ...]) -> bool:
    return (
        isinstance(error, (PermissionError, *logon_errors))
        or getattr(error, "errno", None) == errno.EACCES
        or getattr(error, "ntstatus", None) == _STATUS_ACCESS_DENIED
    )


def _translated(error: BaseException, location: str) -> StorageException:
    """Translate a client error by what it, or an error behind it, says went wrong."""
    causes = _causes(error)
    if any(isinstance(cause, ImportError) for cause in causes):
        return StorageUnavailableException("smbprotocol is not installed; the SMB backend needs it")
    if any(_is_missing(cause) for cause in causes):
        return missing_error(location)
    logon_errors = _protocol_errors(_LOGON_ERRORS)
    if any(_is_denied(cause, logon_errors) for cause in causes):
        return StoragePermissionException(f"access to {location} was denied")
    if any(isinstance(cause, (ConnectionError, TimeoutError)) for cause in causes):
        return StorageTransientException(f"{location}: {error}")
    return StorageException(f"{location}: {error}")


def _client_failures() -> tuple[type[BaseException], ...]:
    """Return what a client call raises.

    The client wraps an ``OSError``; smbprotocol's own errors and the ``ValueError``
    of a failed connection come through as they are.
    """
    return (SMBException, OSError, ValueError, *_protocol_errors(_PROTOCOL_ERROR))


@contextlib.contextmanager
def _smb_errors(location: str) -> Iterator[None]:
    """Turn SMB client and smbprotocol errors into the storage layer's exceptions."""
    try:
        yield
    except _client_failures() as error:
        raise _translated(error, location) from error


def _moment(seconds: float | None) -> datetime | None:
    """Return seconds since the epoch as aware UTC; before 1970 is fine, out of range is not."""
    if seconds is None:
        return None
    try:
        return _EPOCH + timedelta(seconds=seconds)
    except OverflowError:
        return None


def _file_info(path: str, entry: SMBEntry) -> FileInfo:
    return FileInfo(
        path=path,
        is_dir=entry.is_dir,
        size=None if entry.is_dir else entry.size,
        modified_at=_moment(entry.mtime),
    )


class SMBStorage(StorageBackend):
    """The share an ``SMBClient`` is connected to, or the directory ``root`` on it."""

    scheme = SMB_SCHEME
    capabilities = StorageCapabilities(directories=True, modified_at=True)

    def __init__(self, client: SMBClient, *, root: str = "") -> None:
        self._client = client
        self._root = self._normalize(root)

    @property
    def root(self) -> str:
        """The directory this backend is confined to, relative to the share."""
        return self._root

    def _identity(self, path: str) -> Hashable:
        # Two roots of one share; SMB ignores case name a file by the same full path.
        return (SMB_SCHEME, id(self._client), self._remote(path).lower())

    def uri_for(self, path: str = "") -> str:
        inside = "/".join((self._client.share, self._root, self._normalize(path)))
        return str(StorageURI(SMB_SCHEME, self._client.server, inside))

    def _normalize(self, path: str) -> str:
        # A backslash separates SMB path segments too, so "..\\.." must not get past the check.
        return normalize_path(path.replace("\\", "/"))

    def _remote(self, path: str) -> str:
        return join_path(self._root, path) if path else self._root

    def _stat(self, path: str) -> FileInfo | None:
        try:
            with _smb_errors(self.uri_for(path)):
                entry = self._client.stat(self._remote(path))
        except StorageNotFoundException:
            return None
        return _file_info(path, entry)

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        with _smb_errors(self.uri_for(path)):
            entries = self._client.list_dir(self._remote(path))
        return [
            _file_info(join_path(path, entry.name), entry)
            for entry in entries
            if entry.name not in _SELF_AND_PARENT
        ]

    def _upload(self, source: Path, path: str) -> None:
        with _smb_errors(self.uri_for(path)):
            self._client.upload(source, self._remote(path))

    def _download(self, path: str, target: Path) -> None:
        with _smb_errors(self.uri_for(path)):
            self._client.download(self._remote(path), target)

    def _delete_file(self, path: str) -> None:
        with _smb_errors(self.uri_for(path)):
            self._client.delete(self._remote(path))

    def _mkdir(self, path: str) -> None:
        with _smb_errors(self.uri_for(path)):
            self._client.mkdir(self._remote(path))

    def _rmdir(self, path: str) -> None:
        with _smb_errors(self.uri_for(path)):
            self._client.rmdir(self._remote(path))

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, SMBStorage) or source._client is not self._client:
            return False
        with _smb_errors(self.uri_for(path)):
            self._client.rename(source._remote(source_path), self._remote(path), overwrite=True)
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SMBStorage)
            and other._client is self._client
            and other._root == self._root
        )

    def __hash__(self) -> int:
        return hash((SMB_SCHEME, id(self._client), self._root))

    def __repr__(self) -> str:
        return f"SMBStorage({self.uri_for()!r})"
