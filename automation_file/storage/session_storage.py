"""Shared behaviour of the backends that work through one login session: SFTP and FTP.

A session backend serves the directory tree below ``root`` on the host its client
is connected to. :class:`SessionStorage` supplies what does not depend on the
protocol:

* Every storage path is joined to ``root`` and sent as an absolute remote path.
* An upload goes to a sibling ``.part`` name that is renamed over the target, so
  a failed upload never leaves a truncated file behind.
* A move within one session is a rename.
* One operation runs on a session at a time: neither a paramiko SFTP channel nor
  an FTP control connection can serve two callers at once.

:func:`require_session_host` is the rule the ``sftp://`` and ``ftp://`` factories
share: a URI names no host, or the host of the open session.
"""

from __future__ import annotations

import contextlib
import posixpath
import threading
import uuid
import weakref
from abc import abstractmethod
from collections.abc import Hashable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from automation_file.exceptions import StorageException, StorageURIException
from automation_file.logging_config import file_automation_logger
from automation_file.storage.backend import StorageBackend
from automation_file.storage.types import StorageCapabilities
from automation_file.storage.uri import StorageURI, normalize_path

_PARTIAL_SUFFIX = "part"
_ASIDE_SUFFIX = "old"

_locks: weakref.WeakKeyDictionary[Any, threading.RLock] = weakref.WeakKeyDictionary()
_locks_guard = threading.Lock()


def session_lock(session: Any) -> threading.RLock:
    """Return the lock that lets one caller at a time use ``session``."""
    with _locks_guard:
        return _locks.setdefault(session, threading.RLock())


def absolute_root(root: str) -> str:
    """Return ``root`` as an absolute remote path with no trailing slash (``/`` stays ``/``)."""
    return f"/{normalize_path(root)}"


def hidden_sibling(remote: str, suffix: str) -> str:
    """Return a unique dot-name next to ``remote``: ``.<name>.<random>.<suffix>``."""
    directory, name = posixpath.split(remote)
    return posixpath.join(directory, f".{name}.{uuid.uuid4().hex}.{suffix}")


def split_authority(authority: str) -> tuple[str, int | None]:
    """Split ``host``, ``host:port`` or ``[v6-address]:port`` into the host and the port."""
    if authority.startswith("["):
        host, _, rest = authority[1:].partition("]")
        port = rest.removeprefix(":")
    elif authority.count(":") == 1:
        host, _, port = authority.partition(":")
    else:
        host, port = authority, ""
    if not port:
        return host, None
    if not (port.isascii() and port.isdigit()):
        raise StorageURIException(f"invalid port in the storage URI authority {authority!r}")
    return host, int(port)


def session_authority(host: str | None, port: int | None, default_port: int) -> str:
    """Return the URI authority of a session: empty without one, the port only when unusual."""
    if not host:
        return ""
    name = f"[{host}]" if ":" in host else host
    return name if port is None or port == default_port else f"{name}:{port}"


def require_session_host(uri: StorageURI, client: Any, backend: str) -> None:
    """Refuse a URI that names another host than the one ``client`` is connected to.

    An empty authority means "the open session". So does any authority while no
    session is open: the first operation then raises ``StorageUnavailableException``.
    ``backend`` is the class name the message tells the caller to mount.
    """
    connected = client.host
    if not uri.authority or not connected:
        return
    host, port = split_authority(uri.authority)
    if host.casefold() == connected.strip("[]").casefold() and port in (None, client.port):
        return
    session = f"{connected}:{client.port}"
    mount = f'Storage.mount("{uri.scheme}://{uri.authority}", {backend}(client))'
    raise StorageURIException(
        f"{str(uri)!r} names the host {uri.authority!r}, but the open {uri.scheme} session is "
        f"connected to {session!r}. To reach another host, connect a second client to it and "
        f"mount a backend for it: {mount}"
    )


class SessionStorage(StorageBackend):
    """A :class:`StorageBackend` over the directory tree one login session can reach."""

    capabilities = StorageCapabilities(directories=True, modified_at=True)
    #: The port a URI of this backend leaves out.
    default_port = 0

    def __init__(self, client: Any = None, *, root: str = "/") -> None:
        self._explicit_client = client
        self._root = absolute_root(root)

    @property
    def root(self) -> str:
        """The absolute remote directory every path of this backend is joined to."""
        return self._root

    @property
    def client(self) -> Any:
        """The client whose session this backend works through."""
        if self._explicit_client is not None:
            return self._explicit_client
        return self._shared_client()

    # ------------------------------------------------------------------ the protocol

    @abstractmethod
    def _shared_client(self) -> Any:
        """Return the process-wide client, used when none was passed in."""

    @abstractmethod
    def _open_session(self) -> Any:
        """Return the client's open session, or raise ``StorageUnavailableException``."""

    @abstractmethod
    def _errors(self, session: Any, location: str) -> AbstractContextManager[None]:
        """Return a context manager that turns the errors of ``session`` into storage errors."""

    @abstractmethod
    def _store(self, session: Any, source: Path, remote: str) -> None:
        """Write the local file ``source`` to the remote file ``remote``."""

    @abstractmethod
    def _rename(self, session: Any, origin: str, target: str) -> Exception | None:
        """Rename ``origin`` to ``target`` and return ``None``, or return the server's refusal.

        A refusal is an error the server answers with, which it may do because a
        file is at ``target``. A session that broke is raised as usual.
        """

    @abstractmethod
    def _unlink(self, session: Any, remote: str) -> None:
        """Remove the remote file ``remote``."""

    def _uri_scheme(self) -> str:
        """Return the scheme :meth:`uri_for` writes; a backend with two schemes picks one."""
        return self.scheme

    # ------------------------------------------------------------------ shared steps

    def _remote(self, path: str) -> str:
        """Return the absolute remote path of the normalised storage path ``path``."""
        return posixpath.join(self._root, path) if path else self._root

    def _identity(self, path: str) -> Hashable:
        # Two roots of one client name a file by the same absolute path.
        return (self.scheme, id(self.client), self._remote(path))

    @contextlib.contextmanager
    def _session(self, path: str) -> Iterator[Any]:
        """Yield the open session for one operation on ``path``, its errors translated."""
        session = self._open_session()
        with session_lock(session), self._errors(session, self.uri_for(path)):
            yield session

    def uri_for(self, path: str = "") -> str:
        client = self.client
        authority = session_authority(client.host, client.port, self.default_port)
        remote = self._remote(self._normalize(path)).lstrip("/")
        root = f"{self._uri_scheme()}://{authority}"
        return f"{root}/{remote}" if remote or not authority else root

    def _upload(self, source: Path, path: str) -> None:
        remote = self._remote(path)
        partial = hidden_sibling(remote, _PARTIAL_SUFFIX)
        with self._session(path) as session:
            stored = False
            try:
                self._store(session, source, partial)
                self._replace(session, partial, remote)
                stored = True
            finally:
                if not stored:
                    self._discard(session, partial)

    def _replace(self, session: Any, origin: str, target: str) -> None:
        """Rename ``origin`` to ``target``, replacing a file that is already there.

        Most servers do that in one step. A server that will not rename onto an
        existing file has that file moved aside first, and put back when the rename
        still does not happen: the one case in which the replacement is not atomic.
        """
        refusal = self._rename(session, origin, target)
        if refusal is None:
            return
        aside = hidden_sibling(target, _ASIDE_SUFFIX)
        if self._rename(session, target, aside) is not None:
            # Nothing is in the way, or nothing can be renamed: the refusal stands.
            raise refusal
        replaced = False
        try:
            refusal = self._rename(session, origin, target)
            replaced = refusal is None
        finally:
            if not replaced:
                self._put_back(session, aside, target)
        if refusal is not None:
            raise refusal
        self._discard(session, aside)

    def _put_back(self, session: Any, aside: str, target: str) -> None:
        """Give ``target`` its file back. The failed rename is the news, so this only logs."""
        try:
            with self._errors(session, target):
                refusal = self._rename(session, aside, target)
        except StorageException as error:
            refusal = error
        if refusal is not None:
            file_automation_logger.warning(
                "%s: %s was not replaced and its content is now at %s (%s)",
                type(self).__name__,
                target,
                aside,
                type(refusal).__name__,
            )

    def _discard(self, session: Any, remote: str) -> None:
        """Remove the leftover ``remote``. What happened before is the news, so this only logs."""
        try:
            with self._errors(session, remote):
                self._unlink(session, remote)
        except StorageException as error:
            file_automation_logger.warning(
                "%s: %s may have been left behind (%s)",
                type(self).__name__,
                remote,
                type(error).__name__,
            )

    def _delete_file(self, path: str) -> None:
        with self._session(path) as session:
            self._unlink(session, self._remote(path))

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, SessionStorage) or not self._shares_session(source):
            return False
        origin, target = source._remote(source_path), self._remote(path)
        if origin == target:
            raise StorageException(f"{self.uri_for(path)}: source and target are the same file")
        with self._session(path) as session:
            self._replace(session, origin, target)
        return True

    def _shares_session(self, other: SessionStorage) -> bool:
        return other.scheme == self.scheme and other.client is self.client

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SessionStorage)
            and self._shares_session(other)
            and other._root == self._root
        )

    def __hash__(self) -> int:
        return hash((self.scheme, self._root, id(self.client)))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(root={self._root!r})"
