"""SFTPStorage through the real paramiko client.

The client talks to paramiko's own ``SFTPServer`` over a socket pair inside the
process: no SSH daemon and no network, but every request is encoded, sent and
answered by paramiko exactly as it is against a remote host. The server keeps
its files in a temporary directory.

``test_storage_sftp.py`` runs the same contract against an in-memory stand-in,
which can fail on demand and can hold symbolic links. This module is what shows
that the stand-in answers the way paramiko does.
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("paramiko", reason="needs the sftp extra")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
import paramiko
from paramiko.sftp import SFTP_FAILURE, SFTP_OK, SFTP_OP_UNSUPPORTED

from automation_file.exceptions import (
    StorageException,
    StorageNotEmptyException,
    StorageTransientException,
)
from automation_file.remote.sftp.client import SFTPClient
from automation_file.storage import StorageBackend
from automation_file.storage.sftp_storage import SFTPStorage
from tests.storage_contract import StorageContract

TIMEOUT = 30.0
_BINARY = getattr(os, "O_BINARY", 0)


class _Server(paramiko.ServerInterface):
    """Lets anyone in: the peer is this very process."""

    def check_auth_none(self, username: str) -> int:
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username: str) -> str:
        return "none"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return paramiko.OPEN_SUCCEEDED


class _Files(paramiko.SFTPServerInterface):
    """The files below one local directory, served as the SFTP root ``/``."""

    def __init__(self, server: Any, root: Path, posix_rename: bool) -> None:
        super().__init__(server)
        self._root = root
        self._posix_rename = posix_rename

    def _local(self, path: str) -> str:
        return str(self._root) + self.canonicalize(path)

    def _attempt(self, action: Any, *arguments: Any) -> Any:
        """Run a filesystem call and answer its ``OSError`` with the SFTP status for it."""
        try:
            return action(*arguments)
        except OSError as error:
            return paramiko.SFTPServer.convert_errno(error.errno)

    def _listing(self, directory: str) -> list[paramiko.SFTPAttributes]:
        return [
            paramiko.SFTPAttributes.from_stat(os.lstat(os.path.join(directory, name)), name)
            for name in os.listdir(directory)
        ]

    def _opened(self, local: str, flags: int) -> paramiko.SFTPHandle:
        mode = "wb" if flags & os.O_WRONLY else "r+b" if flags & os.O_RDWR else "rb"
        stream = os.fdopen(os.open(local, flags | _BINARY, 0o666), mode)
        handle = paramiko.SFTPHandle(flags)
        handle.readfile = handle.writefile = stream
        return handle

    def _renamed(self, origin: str, target: str) -> int:
        os.rename(origin, target)
        return SFTP_OK

    def _replaced(self, origin: str, target: str) -> int:
        os.replace(origin, target)
        return SFTP_OK

    def list_folder(self, path: str) -> Any:
        return self._attempt(self._listing, self._local(path))

    def stat(self, path: str) -> Any:
        return self._attempt(lambda: paramiko.SFTPAttributes.from_stat(os.stat(self._local(path))))

    def lstat(self, path: str) -> Any:
        return self._attempt(lambda: paramiko.SFTPAttributes.from_stat(os.lstat(self._local(path))))

    def open(self, path: str, flags: int, attr: Any) -> Any:
        return self._attempt(self._opened, self._local(path), flags)

    def remove(self, path: str) -> int:
        return self._attempt(os.remove, self._local(path)) or SFTP_OK

    def mkdir(self, path: str, attr: Any) -> int:
        return self._attempt(os.mkdir, self._local(path)) or SFTP_OK

    def rmdir(self, path: str) -> int:
        return self._attempt(os.rmdir, self._local(path)) or SFTP_OK

    def rename(self, oldpath: str, newpath: str) -> int:
        """Plain SFTP rename as OpenSSH does it: it never replaces what is at the new name."""
        if os.path.lexists(self._local(newpath)):
            return SFTP_FAILURE
        return self._attempt(self._renamed, self._local(oldpath), self._local(newpath))

    def posix_rename(self, oldpath: str, newpath: str) -> int:
        if not self._posix_rename:
            return SFTP_OP_UNSUPPORTED
        return self._attempt(self._replaced, self._local(oldpath), self._local(newpath))


@pytest.fixture(scope="module")
def host_key() -> paramiko.PKey:
    return paramiko.RSAKey.generate(2048)


@contextlib.contextmanager
def loopback(
    root: Path, host_key: paramiko.PKey, *, posix_rename: bool = True
) -> Iterator[SFTPClient]:
    """Yield an ``SFTPClient`` whose session is a real paramiko one, served from ``root``.

    The transports are joined directly, without ``SSHClient``: there is no host to
    verify, both ends of the socket pair are this process.
    """
    server_socket, client_socket = socket.socketpair()
    server = paramiko.Transport(server_socket)
    client = paramiko.Transport(client_socket)
    try:
        server.add_server_key(host_key)
        server.set_subsystem_handler("sftp", paramiko.SFTPServer, _Files, root, posix_rename)
        server.start_server(event=threading.Event(), server=_Server())
        client.start_client(timeout=TIMEOUT)
        client.auth_none("tester")
        session = paramiko.SFTPClient.from_transport(client)
        assert session is not None
        session.get_channel().settimeout(TIMEOUT)
        connected = SFTPClient()
        connected._sftp = session
        connected._host = "loopback"
        connected._port = 22
        yield connected
    finally:
        client.close()
        server.close()


@pytest.fixture
def served(tmp_path: Path) -> Path:
    """The local directory the loopback server serves as ``/``."""
    root = tmp_path / "served"
    root.mkdir()
    return root


@pytest.fixture
def storage(served: Path, host_key: paramiko.PKey) -> Iterator[SFTPStorage]:
    with loopback(served, host_key) as client:
        yield SFTPStorage(client)


class TestSFTPStorageThroughParamikoContract(StorageContract):
    @pytest.fixture
    def backend(self, storage: SFTPStorage) -> StorageBackend:
        return storage


class TestSFTPStorageThroughParamikoWithoutPosixRenameContract(StorageContract):
    @pytest.fixture
    def backend(self, served: Path, host_key: paramiko.PKey) -> Iterator[StorageBackend]:
        with loopback(served, host_key, posix_rename=False) as client:
            yield SFTPStorage(client)


def test_stat_reports_what_the_server_returns(storage: SFTPStorage, served: Path) -> None:
    (served / "reports").mkdir()
    (served / "reports" / "q1.csv").write_bytes(b"a,b\n")
    info = storage.stat("reports/q1.csv")
    assert (info.path, info.is_dir, info.size) == ("reports/q1.csv", False, 4)
    assert info.modified_at is not None
    assert int(info.modified_at.timestamp()) == int((served / "reports" / "q1.csv").stat().st_mtime)
    assert (storage.stat("reports").is_dir, storage.stat("reports").size) == (True, None)
    assert storage.uri_for("reports/q1.csv") == "sftp://loopback/reports/q1.csv"


def test_an_upload_replaces_the_file_and_leaves_nothing_else(
    storage: SFTPStorage, served: Path
) -> None:
    storage.write_bytes("dir/a.txt", b"first")
    storage.write_bytes("dir/a.txt", b"second")
    storage.move_from(storage, "dir/a.txt", "dir/b.txt")
    assert [entry.name for entry in (served / "dir").iterdir()] == ["b.txt"]
    assert (served / "dir" / "b.txt").read_bytes() == b"second"
    with pytest.raises(StorageNotEmptyException):
        storage.delete("dir")
    storage.delete("dir", recursive=True)
    assert list(served.iterdir()) == []


def test_a_refusal_the_server_gives_no_reason_for_is_a_storage_error(
    storage: SFTPStorage, served: Path
) -> None:
    (served / "a.txt").write_bytes(b"x")
    with pytest.raises(StorageException) as caught:
        storage._mkdir("a.txt")
    assert type(caught.value) is StorageException
    assert type(caught.value.__cause__) is OSError
    assert caught.value.__cause__.errno is None


def test_a_closed_session_is_transient(served: Path, host_key: paramiko.PKey) -> None:
    with loopback(served, host_key) as client:
        storage = SFTPStorage(client)
        storage.write_bytes("a.txt", b"x")
        client.require_sftp().close()
        with pytest.raises(StorageTransientException) as caught:
            storage.stat("a.txt")
        assert isinstance(caught.value.__cause__, OSError)
        with pytest.raises(StorageTransientException):
            storage.write_bytes("b.txt", b"y")
    assert sorted(entry.name for entry in served.iterdir()) == ["a.txt"]
