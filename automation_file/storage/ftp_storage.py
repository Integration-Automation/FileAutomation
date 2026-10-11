"""FTP and FTPS backend: ``ftp://<host>[:<port>]/<absolute path>`` and ``ftps://...``.

``FTPStorage()`` serves the files the shared
:data:`~automation_file.remote.ftp.client.ftp_instance` session can reach. The
caller opens that session as before (``ftp_instance.later_init(...)`` or
``FA_ftp_later_init``, with ``tls=True`` for FTPS). Pass another connected
``FTPClient`` to work with a second host, and ``root=`` to join every path to one
remote directory.

A server that offers ``MLST`` (RFC 3659) is asked for the ``type``, ``size`` and
``modify`` facts of an entry. Any other server is probed: a directory is what
``CWD`` enters, a file is what ``SIZE`` and ``MDTM`` answer for, and a listing is
``NLST`` followed by one probe for each name. The working directory is put back
after a probe, so callers that use relative paths on the same session keep theirs.

FTP does not say reliably which names are symbolic links. Deleting never follows
one all the same: ``DELE`` removes a link and refuses a directory, so it is tried
before anything is descended into. A listing shows a link as the server shows it.
"""

from __future__ import annotations

import contextlib
import ftplib  # nosec B402 - error types and reply parsing; FTPClient opens the session
import posixpath
import weakref
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automation_file.exceptions import (
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
from automation_file.storage.session_storage import SessionStorage, require_session_host
from automation_file.storage.types import FileInfo
from automation_file.storage.uri import StorageURI

if TYPE_CHECKING:
    from automation_file.remote.ftp.client import FTPClient

FTP_SCHEME = "ftp"
FTPS_SCHEME = "ftps"
_FTP_PORT = 21
# "Requested action not taken, file unavailable": in a lookup, there is no such entry.
_UNAVAILABLE = "550"
_BINARY = "TYPE I"
_WANTED_FACTS = "OPTS MLST type;size;modify;"
_DIRECTORY_TYPES = frozenset({"dir", "cdir", "pdir"})
_SELF_AND_PARENT = frozenset({"cdir", "pdir"})
_NOT_ENTRIES = frozenset({"", ".", ".."})
_TIMESTAMP = "%Y%m%d%H%M%S"

# Whether the server behind a session offers MLST, asked once for each session.
_mlst_support: weakref.WeakKeyDictionary[Any, bool] = weakref.WeakKeyDictionary()


def _reply_code(error: ftplib.Error) -> str:
    return str(error)[:3]


@contextlib.contextmanager
def _ftp_errors(location: str) -> Iterator[None]:
    """Turn what ftplib raises into the storage layer's exceptions."""
    try:
        yield
    except ftplib.error_perm as error:
        raise StoragePermissionException(
            f"access to {location} was denied ({_reply_code(error)})"
        ) from error
    except ftplib.error_temp as error:
        raise StorageTransientException(f"{location}: FTP answered {_reply_code(error)}") from error
    # TimeoutError is what socket.timeout has been since Python 3.10.
    except (EOFError, TimeoutError, ConnectionError) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error
    # UnicodeError: a name or a reply that is not in the session's encoding.
    except (ftplib.Error, OSError, UnicodeError) as error:
        raise StorageException(f"{location}: {error}") from error


def _one_line(text: str) -> str:
    """Return ``text``, or refuse it: a line break would end the FTP command it is sent in."""
    if "\r" in text or "\n" in text:
        raise StorageURIException(f"FTP paths cannot contain a line break: {text!r}")
    return text


def _negotiate_mlst(ftp: Any) -> bool:
    try:
        features = ftp.sendcmd("FEAT").splitlines()[1:-1]
        if "MLST" not in {line.strip().partition(" ")[0].upper() for line in features}:
            return False
        ftp.sendcmd(_WANTED_FACTS)
    except ftplib.error_perm:
        # No FEAT, or the facts cannot be switched on: probe instead.
        return False
    return True


def _has_mlst(ftp: Any) -> bool:
    known = _mlst_support.get(ftp)
    if known is None:
        known = _mlst_support[ftp] = _negotiate_mlst(ftp)
    return known


def _timestamp(text: str | None) -> datetime | None:
    """Parse the UTC time of a ``modify`` fact or an ``MDTM`` reply: ``YYYYMMDDHHMMSS[.sss]``."""
    whole, _, fraction = (text or "").strip().partition(".")
    try:
        moment = datetime.strptime(whole, _TIMESTAMP)
        microsecond = int(fraction[:6].ljust(6, "0")) if fraction else 0
    except ValueError:
        return None
    return moment.replace(microsecond=microsecond, tzinfo=timezone.utc)


def _fact_info(path: str, facts: dict[str, str]) -> FileInfo:
    is_dir = facts.get("type", "").lower() in _DIRECTORY_TYPES
    size = facts.get("size", "")
    return FileInfo(
        path=path,
        is_dir=is_dir,
        size=int(size) if size.isascii() and size.isdigit() and not is_dir else None,
        modified_at=_timestamp(facts.get("modify")),
    )


def _mlst(ftp: Any, path: str, remote: str) -> FileInfo:
    """Describe ``remote`` from the one entry line of an ``MLST`` reply."""
    reply = ftp.sendcmd(f"MLST {remote}")
    lines = reply.split("\n")
    if len(lines) < 3 or not lines[1].startswith(" "):
        raise ftplib.error_reply(reply)
    facts: dict[str, str] = {}
    for fact in filter(None, lines[1][1:].partition(" ")[0].split(";")):
        name, _, value = fact.partition("=")
        facts[name.lower()] = value
    return _fact_info(path, facts)


def _mlsd(ftp: Any, path: str, remote: str) -> list[FileInfo]:
    found: list[FileInfo] = []
    for listed, facts in ftp.mlsd(remote):
        name = posixpath.basename(listed.rstrip("/"))
        if name in _NOT_ENTRIES or facts.get("type", "").lower() in _SELF_AND_PARENT:
            continue
        found.append(_fact_info(join_path(path, name), facts))
    return found


def _begin_probing(ftp: Any) -> str:
    """Return the working directory to go back to, and set the mode ``SIZE`` needs."""
    home = ftp.pwd()
    ftp.voidcmd(_BINARY)
    return home


def _enters(ftp: Any, remote: str, home: str) -> bool:
    """Say whether ``CWD`` enters ``remote``, going back to ``home`` when it does."""
    try:
        ftp.cwd(remote)
    except ftplib.error_perm as error:
        if _reply_code(error) != _UNAVAILABLE:
            raise
        return False
    ftp.cwd(home)
    return True


def _modified(ftp: Any, remote: str) -> datetime | None:
    try:
        return _timestamp(ftp.sendcmd(f"MDTM {remote}")[3:])
    except ftplib.error_perm:
        return None


def _probe(ftp: Any, path: str, remote: str, home: str) -> FileInfo:
    """Describe ``remote`` on a server without ``MLST``; 550 from ``SIZE`` means it is absent."""
    if _enters(ftp, remote, home):
        return FileInfo(path=path, is_dir=True)
    return FileInfo(path=path, size=ftp.size(remote), modified_at=_modified(ftp, remote))


def _probe_listed(ftp: Any, path: str, remote: str, home: str) -> FileInfo:
    """Like :func:`_probe` for a name ``NLST`` returned, which exists whatever ``SIZE`` says."""
    try:
        return _probe(ftp, path, remote, home)
    except ftplib.error_perm as error:
        if _reply_code(error) != _UNAVAILABLE:
            raise
        return FileInfo(path=path)


def _nlst(ftp: Any, remote: str) -> list[str]:
    """Return the names in the directory ``remote``, whether the server sends names or paths."""
    try:
        lines = ftp.nlst(remote)
    except ftplib.error_perm as error:
        if _reply_code(error) != _UNAVAILABLE:
            raise
        # How some servers say that an existing directory is empty.
        return []
    return sorted({posixpath.basename(line.rstrip("/")) for line in lines} - _NOT_ENTRIES)


def _names(ftp: Any, remote: str) -> list[str]:
    """Return the names in the directory ``remote``, from ``MLSD`` where the server has it."""
    if _has_mlst(ftp):
        return [info.path for info in _mlsd(ftp, "", remote)]
    return _nlst(ftp, remote)


def _unlinked(ftp: Any, remote: str) -> bool:
    """Try ``DELE``, which removes a file or a link and never a directory; say whether it did."""
    try:
        ftp.delete(remote)
    except ftplib.error_perm:
        return False
    return True


def _remove_tree(ftp: Any, remote: str) -> None:
    """Remove the directory ``remote`` and what it holds. A link is removed, never followed.

    FTP does not say reliably which names are links, so every name gets ``DELE``
    first: what that refuses is a directory to descend into.
    """
    directories = [remote]
    pending = [remote]
    while pending:
        directory = pending.pop()
        for name in _names(ftp, directory):
            child = posixpath.join(directory, name)
            if not _unlinked(ftp, child):
                directories.append(child)
                pending.append(child)
    for directory in reversed(directories):
        ftp.rmd(directory)


class FTPStorage(SessionStorage):
    """The directory tree below ``root`` on the host of one FTP or FTPS session."""

    scheme = FTP_SCHEME
    default_port = _FTP_PORT

    def __init__(self, client: FTPClient | None = None, *, root: str = "/") -> None:
        super().__init__(client, root=_one_line(root))

    def _shared_client(self) -> Any:
        from automation_file.remote.ftp.client import ftp_instance

        return ftp_instance

    def _open_session(self) -> Any:
        from automation_file.remote.ftp.client import FTPException

        try:
            return self.client.require_ftp()
        except FTPException as error:
            raise StorageUnavailableException(
                "the FTP session is not open; call ftp_instance.later_init(...) first, "
                "or give FTPStorage a connected FTPClient"
            ) from error

    def _errors(self, session: Any, location: str) -> AbstractContextManager[None]:
        return _ftp_errors(location)

    def _uri_scheme(self) -> str:
        return FTPS_SCHEME if self.client.tls else FTP_SCHEME

    def _normalize(self, path: str) -> str:
        return super()._normalize(_one_line(path))

    @contextlib.contextmanager
    def _lookup(self, path: str) -> Iterator[Any]:
        """Like :meth:`_session`, for a lookup: there 550 means that nothing has that name."""
        with self._session(path) as ftp:
            try:
                yield ftp
            except ftplib.error_perm as error:
                if _reply_code(error) != _UNAVAILABLE:
                    raise
                raise missing_error(self.uri_for(path)) from error

    def _stat(self, path: str) -> FileInfo | None:
        remote = self._remote(path)
        try:
            with self._lookup(path) as ftp:
                if _has_mlst(ftp):
                    return _mlst(ftp, path, remote)
                return _probe(ftp, path, remote, _begin_probing(ftp))
        except StorageNotFoundException:
            return None

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        remote = self._remote(path)
        with self._lookup(path) as ftp:
            if _has_mlst(ftp):
                return _mlsd(ftp, path, remote)
            names = _nlst(ftp, remote)
            # NLST switched the session to ASCII mode, so probing starts after it.
            home = _begin_probing(ftp)
            return [
                _probe_listed(ftp, join_path(path, name), posixpath.join(remote, name), home)
                for name in names
            ]

    def _store(self, session: Any, source: Path, remote: str) -> None:
        with open(source, "rb") as handle:
            session.storbinary(f"STOR {remote}", handle)

    def _rename(self, session: Any, origin: str, target: str) -> Exception | None:
        try:
            # A Unix server replaces a file at the target; others answer 5xx.
            session.rename(origin, target)
        except ftplib.error_perm as error:
            return error
        return None

    def _unlink(self, session: Any, remote: str) -> None:
        session.delete(remote)

    def _download(self, path: str, target: Path) -> None:
        with open(target, "wb") as handle, self._session(path) as ftp:
            ftp.retrbinary(f"RETR {self._remote(path)}", handle.write)

    def _mkdir(self, path: str) -> None:
        with self._session(path) as ftp:
            try:
                ftp.mkd(self._remote(path))
            except ftplib.error_perm:
                # The refusal stands unless the directory is there after all.
                existing = self._stat(path)
                if existing is None or not existing.is_dir:
                    raise

    def _delete_directory(self, path: str, recursive: bool) -> None:
        remote = self._remote(path)
        with self._session(path) as ftp:
            if _unlinked(ftp, remote):
                # It was a link to a directory: the link is gone, the directory stays.
                return
            if recursive:
                _remove_tree(ftp, remote)
            elif _names(ftp, remote):
                raise not_empty_error(self.uri_for(path))
            else:
                ftp.rmd(remote)


def ftp_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    """Serve ``ftp://`` and ``ftps://`` URIs through the shared FTP session.

    The URI names no host, or the host that session is connected to: see
    :func:`~automation_file.storage.session_storage.require_session_host`.
    ``ftps://`` is refused while the open session is not an FTPS one.
    """
    from automation_file.remote.ftp.client import ftp_instance

    require_session_host(uri, ftp_instance, FTPStorage.__name__)
    if uri.scheme == FTPS_SCHEME and ftp_instance.host and not ftp_instance.tls:
        raise StorageURIException(
            f"{str(uri)!r} asks for FTPS, but the open FTP session is not encrypted; "
            "open it with ftp_instance.later_init(..., tls=True)"
        )
    return FTPStorage(), uri.path
