"""SFTP backend: ``sftp://<host>[:<port>]/<absolute path>``.

``SFTPStorage()`` serves the files the shared
:data:`~automation_file.remote.sftp.client.sftp_instance` session can reach. The
caller opens that session as before (``sftp_instance.later_init(...)`` or
``FA_sftp_later_init``), with the host key pinned. Pass another connected
``SFTPClient`` to work with a second host, and ``root=`` to join every path to
one remote directory.

``stat`` reports the size and the modification time the server returns. Symbolic
links are followed when reading and writing. Deleting never follows them: the
link is removed and its target is left alone. A recursive listing does not
descend into a linked directory.
"""

from __future__ import annotations

import contextlib
import posixpath
import stat
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automation_file.exceptions import (
    StorageException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
)
from automation_file.storage.backend import (
    StorageBackend,
    join_path,
    missing_error,
    not_empty_error,
)
from automation_file.storage.session_storage import SessionStorage, require_session_host
from automation_file.storage.types import FileInfo
from automation_file.storage.uri import StorageURI

if TYPE_CHECKING:
    from automation_file.remote.sftp.client import SFTPClient

SFTP_SCHEME = "sftp"
_SSH_PORT = 22


def _closed(sftp: Any) -> bool:
    """Say whether the channel under ``sftp`` is closed.

    Using a closed channel raises a plain ``OSError``.
    """
    channel = sftp.get_channel()
    return channel is None or bool(channel.closed)


@contextlib.contextmanager
def _sftp_errors(sftp: Any, location: str) -> Iterator[None]:
    """Turn what paramiko raises into the storage layer's exceptions.

    paramiko reports an SFTP status as an ``OSError``: ``ENOENT`` for "no such
    file", ``EACCES`` for "permission denied" and no ``errno`` for any other.
    """
    try:
        import paramiko
    except ImportError as error:
        raise StorageUnavailableException(
            "paramiko is not installed; the SFTP backend needs it"
        ) from error
    try:
        yield
    except FileNotFoundError as error:
        raise missing_error(location) from error
    except PermissionError as error:
        raise StoragePermissionException(f"access to {location} was denied") from error
    # TimeoutError is what socket.timeout has been since Python 3.10.
    except (paramiko.SSHException, EOFError, TimeoutError, ConnectionError) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error
    except OSError as error:
        if _closed(sftp):
            raise StorageTransientException(f"{location}: the SFTP session is closed") from error
        raise StorageException(f"{location}: {error}") from error
    # UnicodeError: paramiko decodes names as UTF-8 and a server may send another encoding.
    except (paramiko.SFTPError, UnicodeError) as error:
        raise StorageException(f"{location}: {error}") from error


def _is_link(attributes: Any) -> bool:
    return stat.S_ISLNK(attributes.st_mode or 0)


def _is_directory(attributes: Any) -> bool:
    return stat.S_ISDIR(attributes.st_mode or 0)


def _file_info(path: str, attributes: Any) -> FileInfo:
    is_dir = _is_directory(attributes)
    modified = attributes.st_mtime
    return FileInfo(
        path=path,
        is_dir=is_dir,
        size=None if is_dir else attributes.st_size,
        modified_at=None if modified is None else datetime.fromtimestamp(modified, timezone.utc),
    )


def _status(sftp: Any, error: OSError) -> OSError:
    """Return ``error`` when it is an SFTP status, and raise it when the session broke."""
    if isinstance(error, (TimeoutError, ConnectionError)) or _closed(sftp):
        raise error
    return error


def _followed(sftp: Any, remote: str, link: Any) -> Any:
    """Return the attributes of what the link ``remote`` points to, or its own when that is gone."""
    try:
        return sftp.stat(remote)
    except FileNotFoundError:
        return link


def _directory_exists(sftp: Any, remote: str) -> bool:
    try:
        return _is_directory(sftp.stat(remote))
    except FileNotFoundError:
        return False


def _remove_tree(sftp: Any, remote: str) -> None:
    """Remove the directory ``remote`` and what it holds. A link is removed, never followed."""
    directories = [remote]
    pending = [remote]
    while pending:
        directory = pending.pop()
        for attributes in sftp.listdir_attr(directory):
            child = posixpath.join(directory, attributes.filename)
            if _is_directory(attributes):
                directories.append(child)
                pending.append(child)
            else:
                sftp.remove(child)
    for directory in reversed(directories):
        sftp.rmdir(directory)


class SFTPStorage(SessionStorage):
    """The directory tree below ``root`` on the host of one SFTP session."""

    scheme = SFTP_SCHEME
    default_port = _SSH_PORT

    def __init__(self, client: SFTPClient | None = None, *, root: str = "/") -> None:
        super().__init__(client, root=root)

    def _shared_client(self) -> Any:
        from automation_file.remote.sftp.client import sftp_instance

        return sftp_instance

    def _open_session(self) -> Any:
        try:
            return self.client.require_sftp()
        except RuntimeError as error:
            raise StorageUnavailableException(
                "the SFTP session is not open; call sftp_instance.later_init(...) first, "
                "or give SFTPStorage a connected SFTPClient"
            ) from error

    def _errors(self, session: Any, location: str) -> AbstractContextManager[None]:
        return _sftp_errors(session, location)

    def _stat(self, path: str) -> FileInfo | None:
        with self._session(path) as sftp:
            try:
                return _file_info(path, sftp.stat(self._remote(path)))
            except FileNotFoundError:
                return None

    def _entries(self, sftp: Any, path: str) -> list[tuple[FileInfo, bool]]:
        """Return every child of the directory ``path`` and whether it is a symbolic link."""
        remote = self._remote(path)
        found: list[tuple[FileInfo, bool]] = []
        for listed in sftp.listdir_attr(remote):
            linked = _is_link(listed)
            child = posixpath.join(remote, listed.filename)
            attributes = _followed(sftp, child, listed) if linked else listed
            found.append((_file_info(join_path(path, listed.filename), attributes), linked))
        return found

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        with self._session(path) as sftp:
            return [info for info, _ in self._entries(sftp, path)]

    def _walk(self, path: str) -> Iterable[FileInfo]:
        found: list[FileInfo] = []
        pending = [path]
        with self._session(path) as sftp:
            while pending:
                for info, linked in self._entries(sftp, pending.pop()):
                    found.append(info)
                    if info.is_dir and not linked:
                        pending.append(info.path)
        return found

    def _store(self, session: Any, source: Path, remote: str) -> None:
        session.put(str(source), remote)

    def _rename(self, session: Any, origin: str, target: str) -> Exception | None:
        try:
            # posix-rename@openssh.com replaces a file at the target in one step.
            session.posix_rename(origin, target)
            return None
        except OSError as error:
            if _status(session, error).errno is not None:
                return error
        # A status without an errno: this server may not have the extension. The
        # plain rename it does have replaces nothing on most servers.
        try:
            session.rename(origin, target)
        except OSError as error:
            return _status(session, error)
        return None

    def _unlink(self, session: Any, remote: str) -> None:
        session.remove(remote)

    def _download(self, path: str, target: Path) -> None:
        with self._session(path) as sftp:
            sftp.get(self._remote(path), str(target))

    def _mkdir(self, path: str) -> None:
        remote = self._remote(path)
        with self._session(path) as sftp:
            try:
                sftp.mkdir(remote)
            except OSError as error:
                # "It is already there" arrives as a status without an errno.
                if _status(sftp, error).errno is not None or not _directory_exists(sftp, remote):
                    raise

    def _delete_directory(self, path: str, recursive: bool) -> None:
        remote = self._remote(path)
        with self._session(path) as sftp:
            if _is_link(sftp.lstat(remote)):
                sftp.remove(remote)
            elif recursive:
                _remove_tree(sftp, remote)
            elif sftp.listdir_attr(remote):
                raise not_empty_error(self.uri_for(path))
            else:
                sftp.rmdir(remote)


def sftp_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    """Serve ``sftp://[<host>[:<port>]]/<path>`` through the shared SFTP session.

    The URI names no host, or the host that session is connected to: see
    :func:`~automation_file.storage.session_storage.require_session_host`.
    """
    from automation_file.remote.sftp.client import sftp_instance

    require_session_host(uri, sftp_instance, SFTPStorage.__name__)
    return SFTPStorage(), uri.path
