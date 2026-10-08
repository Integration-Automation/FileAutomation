"""SFTPStorage: the storage contract against an in-memory stand-in for paramiko's SFTP client.

The stand-in keeps a tree of directories, files and symbolic links. It answers
the calls the adapter makes -- ``stat``, ``lstat``, ``listdir_attr``, ``put``,
``get``, ``remove``, ``mkdir``, ``rmdir``, ``posix_rename`` and ``rename`` -- with
paramiko's own ``SFTPAttributes`` and with the exceptions paramiko turns an SFTP
status into. No connection is opened.
"""

from __future__ import annotations

import errno
import inspect
import posixpath
import re
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("paramiko", reason="needs the sftp extra")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
import paramiko
from paramiko.sftp import (
    SFTP_EOF,
    SFTP_FAILURE,
    SFTP_NO_SUCH_FILE,
    SFTP_OP_UNSUPPORTED,
    SFTP_PERMISSION_DENIED,
)

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.remote.sftp.client import SFTPClient, sftp_instance
from automation_file.storage import File, Storage, StorageBackend, StorageResolver
from automation_file.storage.session_storage import session_lock
from automation_file.storage.sftp_storage import (
    SFTP_SCHEME,
    SFTPStorage,
    sftp_factory,
)
from tests.storage_contract import StorageContract

HOST = "nas.example"
MODIFIED = 1_791_426_600.0


@dataclass
class _Directory:
    modified: float


@dataclass
class _Regular:
    data: bytes
    modified: float


@dataclass
class _Link:
    target: str


_Node = _Directory | _Regular | _Link


def _no_such_file() -> OSError:
    """What paramiko raises for SSH_FX_NO_SUCH_FILE: a ``FileNotFoundError``."""
    return OSError(errno.ENOENT, "No such file")


def _denied() -> OSError:
    """What paramiko raises for SSH_FX_PERMISSION_DENIED: a ``PermissionError``."""
    return OSError(errno.EACCES, "Permission denied")


def _failure(text: str = "Failure") -> OSError:
    """What paramiko raises for every other status: an ``OSError`` without an errno."""
    return OSError(text)


@dataclass
class _Channel:
    """What ``get_channel`` returns; paramiko refuses to send on a closed one."""

    closed: bool = False


class FakeSFTP:
    """The subset of ``paramiko.SFTPClient`` that SFTPStorage calls, over an in-memory tree."""

    def __init__(self, *, posix_rename: bool = True) -> None:
        self.nodes: dict[str, _Node] = {"/": _Directory(time.time())}
        self.channel = _Channel()
        self.calls: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None
        self.failures: dict[str, Exception] = {}
        self.put_error: Exception | None = None
        self.on_call: Callable[[], None] | None = None
        self._posix_rename = posix_rename

    # ------------------------------------------------------------------ the tree

    def _called(self, name: str, path: str) -> None:
        self.calls.append((name, path))
        if self.on_call is not None:
            self.on_call()
        if self.channel.closed:
            raise OSError("Socket is closed")
        error = self.fail_with or self.failures.get(name)
        if error is not None:
            raise error

    def _real(self, path: str, *, follow: bool = True) -> str:
        """Resolve the links in ``path`` as a server does; the last one only when ``follow``."""
        parts = [part for part in path.split("/") if part]
        current = "/"
        for index, part in enumerate(parts):
            current = posixpath.join(current, part)
            node = self.nodes.get(current)
            if isinstance(node, _Link) and (follow or index < len(parts) - 1):
                current = self._real(posixpath.join(posixpath.dirname(current), node.target))
        return current

    def _node(self, path: str, *, follow: bool = True) -> tuple[str, _Node]:
        real = self._real(path, follow=follow)
        if real not in self.nodes:
            raise _no_such_file()
        return real, self.nodes[real]

    def _writable(self, path: str, *, follow: bool) -> str:
        real = self._real(path, follow=follow)
        if not isinstance(self.nodes.get(posixpath.dirname(real)), _Directory):
            raise _no_such_file()
        return real

    def _attributes(self, node: _Node, filename: str | None = None) -> paramiko.SFTPAttributes:
        attributes = paramiko.SFTPAttributes()
        if isinstance(node, _Directory):
            attributes.st_mode, attributes.st_size = stat.S_IFDIR | 0o755, 4096
            attributes.st_mtime = int(node.modified)
        elif isinstance(node, _Regular):
            attributes.st_mode, attributes.st_size = stat.S_IFREG | 0o644, len(node.data)
            attributes.st_mtime = int(node.modified)
        else:
            attributes.st_mode, attributes.st_size = stat.S_IFLNK | 0o777, len(node.target)
            attributes.st_mtime = int(MODIFIED)
        if filename is not None:
            attributes.filename = filename
        return attributes

    def _move(self, oldpath: str, newpath: str, *, replace: bool) -> None:
        origin, _ = self._node(oldpath, follow=False)
        target = self._writable(newpath, follow=False)
        existing = self.nodes.get(target)
        if isinstance(existing, _Directory) or (existing is not None and not replace):
            raise _failure()
        for key in [key for key in self.nodes if key == origin or key.startswith(f"{origin}/")]:
            self.nodes[target + key[len(origin) :]] = self.nodes.pop(key)

    def paths(self) -> list[str]:
        return sorted(key for key in self.nodes if key != "/")

    def write(self, path: str, data: bytes, modified: float = MODIFIED) -> None:
        self.nodes[path] = _Regular(data, modified)

    def read(self, path: str) -> bytes:
        node = self.nodes[path]
        assert isinstance(node, _Regular)
        return node.data

    # ------------------------------------------------------------------ paramiko.SFTPClient

    def get_channel(self) -> _Channel:
        return self.channel

    def stat(self, path: str) -> paramiko.SFTPAttributes:
        self._called("stat", path)
        return self._attributes(self._node(path)[1])

    def lstat(self, path: str) -> paramiko.SFTPAttributes:
        self._called("lstat", path)
        return self._attributes(self._node(path, follow=False)[1])

    def listdir_attr(self, path: str = ".") -> list[paramiko.SFTPAttributes]:
        self._called("listdir_attr", path)
        real, node = self._node(path)
        if not isinstance(node, _Directory):
            raise _no_such_file()
        return [
            self._attributes(child, posixpath.basename(key))
            for key, child in self.nodes.items()
            if key != "/" and posixpath.dirname(key) == real
        ]

    def put(self, localpath: str, remotepath: str, callback=None, confirm: bool = True):
        self._called("put", remotepath)
        data = Path(localpath).read_bytes()
        real = self._writable(remotepath, follow=True)
        if isinstance(self.nodes.get(real), _Directory):
            raise _failure()
        if self.put_error is not None:
            self.nodes[real] = _Regular(data[: len(data) // 2], time.time())
            raise self.put_error
        self.nodes[real] = _Regular(data, time.time())
        return self._attributes(self.nodes[real])

    def get(
        self,
        remotepath: str,
        localpath: str,
        callback=None,
        prefetch: bool = True,
        max_concurrent_prefetch_requests=None,
    ) -> None:
        self._called("get", remotepath)
        node = self._node(remotepath)[1]
        if not isinstance(node, _Regular):
            raise _failure()
        Path(localpath).write_bytes(node.data)

    def remove(self, path: str) -> None:
        self._called("remove", path)
        real, node = self._node(path, follow=False)
        if isinstance(node, _Directory):
            raise _failure()
        del self.nodes[real]

    def mkdir(self, path: str, mode: int = 0o777) -> None:
        self._called("mkdir", path)
        real = self._writable(path, follow=False)
        if real in self.nodes:
            raise _failure()
        self.nodes[real] = _Directory(time.time())

    def rmdir(self, path: str) -> None:
        self._called("rmdir", path)
        real, node = self._node(path, follow=False)
        if not isinstance(node, _Directory):
            raise _no_such_file()
        if any(posixpath.dirname(key) == real for key in self.nodes if key != "/"):
            raise _failure()
        del self.nodes[real]

    def posix_rename(self, oldpath: str, newpath: str) -> None:
        self._called("posix_rename", newpath)
        if not self._posix_rename:
            raise _failure("Operation unsupported")
        self._move(oldpath, newpath, replace=True)

    def rename(self, oldpath: str, newpath: str) -> None:
        self._called("rename", newpath)
        self._move(oldpath, newpath, replace=False)

    def symlink(self, source: str, dest: str) -> None:
        self.nodes[dest] = _Link(source)


def connected(
    session: FakeSFTP | None, host: str | None = HOST, port: int | None = 22
) -> SFTPClient:
    """Return an ``SFTPClient`` whose session is ``session``, as ``later_init`` leaves it."""
    client = SFTPClient()
    client._sftp = session
    client._host = host
    client._port = port
    return client


class TestSFTPStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return SFTPStorage(connected(FakeSFTP()))


class TestRootedSFTPStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        session = FakeSFTP()
        session.mkdir("/srv")
        session.mkdir("/srv/data")
        session.write("/srv/keep.txt", b"keep")
        return SFTPStorage(connected(session), root="/srv/data")


class TestSFTPStorageWithoutPosixRenameContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return SFTPStorage(connected(FakeSFTP(posix_rename=False)))


@pytest.fixture
def session() -> FakeSFTP:
    return FakeSFTP()


@pytest.fixture
def storage(session: FakeSFTP) -> SFTPStorage:
    return SFTPStorage(connected(session))


@pytest.fixture
def shared(monkeypatch: pytest.MonkeyPatch, session: FakeSFTP) -> FakeSFTP:
    """Make ``session`` the open session of the shared ``sftp_instance``."""
    monkeypatch.setattr(sftp_instance, "_sftp", session)
    monkeypatch.setattr(sftp_instance, "_host", HOST)
    monkeypatch.setattr(sftp_instance, "_port", 22)
    return session


@pytest.fixture
def resolver() -> StorageResolver:
    table = StorageResolver()
    table.register_scheme(SFTP_SCHEME, sftp_factory)
    return table


# ---------------------------------------------------------------------- stat and paths


def test_stat_reports_the_size_and_the_modification_time(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    session.mkdir("/reports")
    session.write("/reports/q1.csv", b"a,b\n")
    info = storage.stat("reports/q1.csv")
    assert (info.path, info.is_dir, info.size) == ("reports/q1.csv", False, 4)
    assert info.modified_at == datetime.fromtimestamp(MODIFIED, timezone.utc)
    assert (info.etag, info.version, info.content_type, dict(info.metadata)) == (
        None,
        None,
        None,
        {},
    )
    directory = storage.stat("reports")
    assert (directory.is_dir, directory.size) == (True, None)
    assert storage.capabilities.to_dict() == {
        "directories": True,
        "modified_at": True,
        "etag": False,
        "version": False,
        "content_type": False,
        "metadata": False,
    }


def test_attributes_a_server_leaves_out_stay_unknown(
    storage: SFTPStorage, session: FakeSFTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.write("/bare", b"x")
    monkeypatch.setattr(
        session, "_attributes", lambda node, filename=None: paramiko.SFTPAttributes()
    )
    info = storage.stat("bare")
    assert (info.is_dir, info.size, info.modified_at) == (False, None, None)


def test_every_path_is_joined_to_the_root(session: FakeSFTP) -> None:
    session.mkdir("/srv")
    session.mkdir("/srv/data")
    session.write("/srv/keep.txt", b"keep")
    rooted = SFTPStorage(connected(session), root="srv//data/")
    assert rooted.root == "/srv/data"
    rooted.write_bytes("docs/a.txt", b"x")
    assert session.paths() == [
        "/srv",
        "/srv/data",
        "/srv/data/docs",
        "/srv/data/docs/a.txt",
        "/srv/keep.txt",
    ]
    assert [info.path for info in rooted.list_dir("", recursive=True)] == ["docs", "docs/a.txt"]
    assert rooted.uri_for("docs/a.txt") == "sftp://nas.example/srv/data/docs/a.txt"
    rooted.delete("docs", recursive=True)
    assert session.paths() == ["/srv", "/srv/data", "/srv/keep.txt"]
    with pytest.raises(StorageURIException):
        SFTPStorage(connected(session), root="/srv/../etc")


def test_uri_for_names_the_host_of_the_session(session: FakeSFTP) -> None:
    assert SFTPStorage(connected(session)).uri_for("data/a.txt") == "sftp://nas.example/data/a.txt"
    assert SFTPStorage(connected(session)).uri_for("") == "sftp://nas.example"
    assert (
        SFTPStorage(connected(session, port=2222)).uri_for("a.txt")
        == "sftp://nas.example:2222/a.txt"
    )
    assert SFTPStorage(connected(session, host="::1")).uri_for("a.txt") == "sftp://[::1]/a.txt"
    assert SFTPStorage(connected(None, host=None, port=None)).uri_for("a.txt") == "sftp:///a.txt"


def test_equality_and_repr(session: FakeSFTP) -> None:
    client = connected(session)
    first, second = SFTPStorage(client), SFTPStorage(client)
    assert first == second
    assert SFTPStorage(client) != SFTPStorage(client, root="/srv")
    assert SFTPStorage(client) != SFTPStorage(connected(session))
    assert SFTPStorage() == SFTPStorage(sftp_instance)
    assert len({SFTPStorage(client), SFTPStorage(client, root="/")}) == 1
    assert repr(SFTPStorage(client, root="srv/data")) == "SFTPStorage(root='/srv/data')"
    assert SFTPStorage(client).client is client
    assert SFTPStorage().client is sftp_instance


# ---------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "error,expected",
    [
        (_denied(), StoragePermissionException),
        (paramiko.SSHException("Server connection dropped: "), StorageTransientException),
        (EOFError(), StorageTransientException),
        (TimeoutError("timed out"), StorageTransientException),
        (ConnectionResetError(errno.ECONNRESET, "reset by peer"), StorageTransientException),
        (_failure(), StorageException),
        (paramiko.SFTPError("Expected attributes"), StorageException),
        (UnicodeDecodeError("utf-8", b"caf\xe9", 3, 4, "invalid start byte"), StorageException),
    ],
)
def test_session_errors_become_storage_errors(
    storage: SFTPStorage, session: FakeSFTP, error: Exception, expected: type[Exception]
) -> None:
    session.fail_with = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert caught.value.__cause__ is error
    assert type(caught.value) is expected


def test_a_closed_channel_is_transient(storage: SFTPStorage, session: FakeSFTP) -> None:
    storage.write_bytes("a.txt", b"old")
    session.channel.closed = True
    for call in (storage.exists, storage.list_dir, storage.read_bytes, storage.mkdir):
        with pytest.raises(StorageTransientException, match="session is closed") as caught:
            call("a.txt")
        assert str(caught.value.__cause__) == "Socket is closed"


def test_a_channel_that_closes_during_a_rename_is_not_a_refusal(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    storage.write_bytes("a.txt", b"old")
    session.calls.clear()

    def close_before_the_rename() -> None:
        if session.calls[-1][0] == "posix_rename":
            session.channel.closed = True

    session.on_call = close_before_the_rename
    with pytest.raises(StorageTransientException, match="session is closed"):
        storage.write_bytes("a.txt", b"new")
    assert [name for name, _ in session.calls] == ["stat", "put", "posix_rename", "remove"]
    assert session.read("/a.txt") == b"old"


def test_a_missing_path_is_not_found(storage: SFTPStorage) -> None:
    assert storage.exists("nope/a.txt") is False
    with pytest.raises(StorageNotFoundException, match=re.escape("sftp://nas.example/nope")):
        storage.list_dir("nope")


def test_paramiko_reports_a_status_the_way_the_adapter_reads_it() -> None:
    """The adapter tells the SFTP statuses apart by what paramiko's own converter raises."""

    def convert(code: int) -> None:
        message = paramiko.Message()
        message.add_int(code)
        message.add_string("text")
        message.rewind()
        paramiko.SFTPClient._convert_status(None, message)

    with pytest.raises(FileNotFoundError):
        convert(SFTP_NO_SUCH_FILE)
    with pytest.raises(PermissionError):
        convert(SFTP_PERMISSION_DENIED)
    with pytest.raises(EOFError):
        convert(SFTP_EOF)
    for code in (SFTP_FAILURE, SFTP_OP_UNSUPPORTED):
        with pytest.raises(OSError) as caught:
            convert(code)
        assert type(caught.value) is OSError
        assert caught.value.errno is None
    assert type(_no_such_file()) is FileNotFoundError
    assert type(_denied()) is PermissionError


def test_a_session_must_be_open(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(StorageUnavailableException, match="later_init"):
        SFTPStorage(SFTPClient()).exists("a.txt")
    monkeypatch.setattr(sftp_instance, "_sftp", None)
    with pytest.raises(StorageUnavailableException, match="later_init") as caught:
        SFTPStorage().write_bytes("a.txt", b"x")
    assert isinstance(caught.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------- uploads and moves


def test_an_upload_arrives_under_a_part_name_and_is_renamed(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    storage.write_bytes("a.txt", b"payload")
    (put, partial), (rename, target) = [
        call for call in session.calls if call[0] in ("put", "posix_rename", "rename")
    ]
    assert (put, rename, target) == ("put", "posix_rename", "/a.txt")
    assert posixpath.dirname(partial) == "/"
    assert posixpath.basename(partial).startswith(".a.txt.")
    assert partial.endswith(".part")
    assert session.paths() == ["/a.txt"]


@pytest.mark.parametrize(
    "error,expected",
    [
        (TimeoutError("timed out"), StorageTransientException),
        (_failure("size mismatch in put!  3 != 7"), StorageException),
    ],
)
def test_a_failed_upload_leaves_no_partial_file_and_keeps_the_target(
    storage: SFTPStorage, session: FakeSFTP, error: Exception, expected: type[Exception]
) -> None:
    session.write("/a.txt", b"old")
    session.put_error = error
    with pytest.raises(expected) as caught:
        storage.write_bytes("a.txt", b"new and longer")
    assert caught.value.__cause__ is error
    assert session.paths() == ["/a.txt"]
    assert session.read("/a.txt") == b"old"


def test_a_refused_rename_leaves_no_partial_file_and_keeps_the_target(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    session.write("/a.txt", b"old")
    session.failures["posix_rename"] = _denied()
    with pytest.raises(StoragePermissionException):
        storage.write_bytes("a.txt", b"new")
    assert session.paths() == ["/a.txt"]
    assert session.read("/a.txt") == b"old"


def test_the_upload_error_is_reported_when_the_cleanup_fails_too(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    session.put_error = EOFError()
    session.failures["remove"] = paramiko.SSHException("Server connection dropped: ")
    with pytest.raises(StorageTransientException) as caught:
        storage.write_bytes("a.txt", b"payload")
    assert caught.value.__cause__ is session.put_error
    assert [posixpath.basename(path)[:7] for path in session.paths()] == [".a.txt."]


@pytest.fixture
def old_session() -> FakeSFTP:
    """A server without ``posix-rename@openssh.com``: its rename never replaces a file."""
    return FakeSFTP(posix_rename=False)


def fail_the_nth(session: FakeSFTP, name: str, nth: set[int], error: Exception) -> None:
    """Make the calls of the method ``name`` whose ordinal is in ``nth`` raise ``error``."""
    seen = 0

    def before_each_call() -> None:
        nonlocal seen
        session.failures.pop(name, None)
        if session.calls[-1][0] == name:
            seen += 1
            if seen in nth:
                session.failures[name] = error

    session.on_call = before_each_call


def test_a_server_without_posix_rename_has_the_old_file_moved_aside(
    old_session: FakeSFTP,
) -> None:
    storage = SFTPStorage(connected(old_session))
    storage.write_bytes("a.txt", b"first")
    assert [name for name, _ in old_session.calls if "rename" in name] == [
        "posix_rename",
        "rename",
    ]
    old_session.calls.clear()
    storage.write_bytes("a.txt", b"second")
    partial = next(path for name, path in old_session.calls if name == "put")
    aside = next(path for name, path in old_session.calls if path.endswith(".old"))
    assert posixpath.basename(aside).startswith(".a.txt.")
    assert [call for call in old_session.calls if call[0] != "stat"] == [
        ("put", partial),
        ("posix_rename", "/a.txt"),
        ("rename", "/a.txt"),
        ("posix_rename", aside),
        ("rename", aside),
        ("posix_rename", "/a.txt"),
        ("rename", "/a.txt"),
        ("remove", aside),
    ]
    assert old_session.paths() == ["/a.txt"]
    assert old_session.read("/a.txt") == b"second"


def test_a_rename_refused_for_another_reason_keeps_the_target(old_session: FakeSFTP) -> None:
    storage = SFTPStorage(connected(old_session))
    refusal = _failure("Quota exceeded")
    old_session.failures["rename"] = refusal
    with pytest.raises(StorageException) as caught:
        storage.write_bytes("new.txt", b"payload")
    assert caught.value.__cause__ is refusal
    assert old_session.paths() == []

    old_session.write("/a.txt", b"old")
    with pytest.raises(StorageException) as caught:
        storage.write_bytes("a.txt", b"payload")
    assert caught.value.__cause__ is refusal
    assert old_session.paths() == ["/a.txt"]
    assert old_session.read("/a.txt") == b"old"


@pytest.mark.parametrize(
    "error,expected",
    [
        (_failure("Disk full"), StorageException),
        (paramiko.SSHException("Server connection dropped: "), StorageTransientException),
    ],
)
def test_the_old_file_is_put_back_when_the_rename_still_fails(
    old_session: FakeSFTP, error: Exception, expected: type[Exception]
) -> None:
    storage = SFTPStorage(connected(old_session))
    old_session.write("/a.txt", b"old")
    # Renames: onto the file (refused), the file aside, onto the freed name, the file back.
    fail_the_nth(old_session, "rename", {3}, error)
    with pytest.raises(expected) as caught:
        storage.write_bytes("a.txt", b"new")
    assert caught.value.__cause__ is error
    assert old_session.paths() == ["/a.txt"]
    assert old_session.read("/a.txt") == b"old"


@pytest.mark.parametrize(
    "error", [_failure("Disk full"), paramiko.SSHException("Server connection dropped: ")]
)
def test_the_old_content_stays_aside_when_it_cannot_be_put_back(
    old_session: FakeSFTP, error: Exception
) -> None:
    storage = SFTPStorage(connected(old_session))
    old_session.write("/a.txt", b"old")
    fail_the_nth(old_session, "rename", {3, 4}, error)
    with pytest.raises(StorageException) as caught:
        storage.write_bytes("a.txt", b"new")
    assert caught.value.__cause__ is error
    (aside,) = old_session.paths()
    assert posixpath.basename(aside).startswith(".a.txt.")
    assert aside.endswith(".old")
    assert old_session.read(aside) == b"old"


def test_a_move_within_one_session_is_a_rename(storage: SFTPStorage, session: FakeSFTP) -> None:
    storage.write_bytes("a.txt", b"payload")
    session.calls.clear()
    info = storage.move_from(storage, "a.txt", "moved/b.txt")
    assert (info.path, info.size) == ("moved/b.txt", 7)
    assert ("posix_rename", "/moved/b.txt") in session.calls
    assert not [call for call in session.calls if call[0] in ("get", "put", "remove")]
    assert session.paths() == ["/moved", "/moved/b.txt"]

    archive = SFTPStorage(storage.client, root="/moved")
    archive.move_from(storage, "moved/b.txt", "c.txt")
    assert session.paths() == ["/moved", "/moved/c.txt"]
    with pytest.raises(StorageException, match="same file"):
        archive.move_from(storage, "moved/c.txt", "c.txt")
    assert session.read("/moved/c.txt") == b"payload"


def test_a_move_between_two_sessions_is_copy_then_delete(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    other_session = FakeSFTP()
    other = SFTPStorage(connected(other_session, host="backup.example"))
    storage.write_bytes("a.txt", b"payload")
    other.move_from(storage, "a.txt", "a.txt")
    assert other_session.read("/a.txt") == b"payload"
    assert session.paths() == []
    assert "get" in [name for name, _ in session.calls]


def test_mkdir_accepts_a_directory_that_appeared_meanwhile(
    storage: SFTPStorage, session: FakeSFTP
) -> None:
    session.mkdir("/dir")
    storage._mkdir("dir")
    session.write("/a.txt", b"x")
    with pytest.raises(StorageException) as caught:
        storage._mkdir("a.txt")
    assert type(caught.value) is StorageException
    session.failures["mkdir"] = _failure("Quota exceeded")
    with pytest.raises(StorageException) as caught:
        storage._mkdir("new")
    assert caught.value.__cause__ is session.failures.pop("mkdir")
    with pytest.raises(StorageNotFoundException):
        SFTPStorage(storage.client, root="/missing")._mkdir("child")


def test_a_file_that_vanished_is_not_found(storage: SFTPStorage, session: FakeSFTP) -> None:
    storage.write_bytes("a.txt", b"x")

    def vanish_before_the_download() -> None:
        if session.calls[-1][0] == "get":
            del session.nodes["/a.txt"]

    session.on_call = vanish_before_the_download
    with pytest.raises(StorageNotFoundException, match="does not exist"):
        storage.read_bytes("a.txt")


# ---------------------------------------------------------------------- symbolic links


@pytest.fixture
def linked(storage: SFTPStorage, session: FakeSFTP) -> SFTPStorage:
    """``/data`` with a link to a file, to a directory outside it, and to nothing."""
    for path in ("outside/keep.txt", "data/real.txt"):
        storage.write_bytes(path, b"content")
    session.symlink("real.txt", "/data/file-link")
    session.symlink("/outside", "/data/dir-link")
    session.symlink("/gone", "/data/dangling")
    return storage


def test_links_are_followed_when_reading_and_listing(linked: SFTPStorage) -> None:
    assert linked.read_bytes("data/file-link") == b"content"
    assert linked.read_bytes("data/dir-link/keep.txt") == b"content"
    assert [(info.name, info.is_dir, info.size) for info in linked.list_dir("data")] == [
        ("dangling", False, 5),
        ("dir-link", True, None),
        ("file-link", False, 7),
        ("real.txt", False, 7),
    ]
    assert linked.exists("data/dangling") is False


def test_a_recursive_listing_does_not_descend_into_a_linked_directory(linked: SFTPStorage) -> None:
    assert [info.path for info in linked.list_dir("data", recursive=True)] == [
        "data/dangling",
        "data/dir-link",
        "data/file-link",
        "data/real.txt",
    ]


def test_deleting_never_follows_a_link(linked: SFTPStorage, session: FakeSFTP) -> None:
    linked.delete("data/dir-link", recursive=True)
    assert "/data/dir-link" not in session.nodes
    assert session.read("/outside/keep.txt") == b"content"
    linked.delete("data/file-link")
    assert session.read("/data/real.txt") == b"content"

    session.symlink("/outside", "/data/dir-link")
    linked.delete("data", recursive=True)
    assert session.paths() == ["/outside", "/outside/keep.txt"]


# ---------------------------------------------------------------------- sftp:// URIs


def test_sftp_uris_use_the_shared_session(
    shared: FakeSFTP, resolver: StorageResolver, tmp_path: Path
) -> None:
    report = File("sftp://nas.example/reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert shared.read("/reports/q1.csv") == b"a,b\n"
    assert resolver.resolve("sftp://nas.example/reports/q1.csv") == (
        SFTPStorage(),
        "reports/q1.csv",
    )
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    File(tmp_path / "q1.csv", resolver=resolver).move_to("sftp:///archive/2026/q1.csv")
    assert shared.read("/archive/2026/q1.csv") == b"a,b\n"
    archive = Storage("sftp://nas.example/archive", resolver=resolver)
    assert [info.path for info in archive.list_dir(recursive=True)] == ["2026", "2026/q1.csv"]
    archive.delete("2026", recursive=True)
    assert shared.paths() == ["/archive", "/reports", "/reports/q1.csv"]


@pytest.mark.parametrize(
    "uri",
    [
        "sftp:///data/a.txt",
        "sftp://nas.example/data/a.txt",
        "sftp://NAS.Example/data/a.txt",
        "sftp://nas.example:22/data/a.txt",
    ],
)
def test_a_uri_may_name_no_host_or_the_connected_one(
    shared: FakeSFTP, resolver: StorageResolver, uri: str
) -> None:
    assert resolver.resolve(uri) == (SFTPStorage(), "data/a.txt")


@pytest.mark.parametrize(
    "uri,named",
    [
        ("sftp://backup.example/data/a.txt", "backup.example"),
        ("sftp://nas.example:2222/data/a.txt", "nas.example:2222"),
    ],
)
def test_a_uri_for_another_host_is_refused(
    shared: FakeSFTP, resolver: StorageResolver, uri: str, named: str
) -> None:
    with pytest.raises(StorageURIException) as caught:
        resolver.resolve(uri)
    message = str(caught.value)
    assert repr(named) in message
    assert "'nas.example:22'" in message
    assert f'Storage.mount("sftp://{named}", SFTPStorage(client))' in message


def test_a_malformed_port_is_refused(shared: FakeSFTP, resolver: StorageResolver) -> None:
    with pytest.raises(StorageURIException, match="port"):
        resolver.resolve("sftp://nas.example:ssh/data/a.txt")


def test_an_ipv6_host_is_written_in_brackets(
    shared: FakeSFTP, resolver: StorageResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sftp_instance, "_host", "fd00::1")
    assert resolver.resolve("sftp://[FD00::1]:22/a.txt") == (SFTPStorage(), "a.txt")
    assert resolver.resolve("sftp://[fd00::1]/a.txt") == (SFTPStorage(), "a.txt")
    with pytest.raises(StorageURIException):
        resolver.resolve("sftp://[fd00::2]/a.txt")


def test_any_host_resolves_until_a_session_is_open(
    monkeypatch: pytest.MonkeyPatch, resolver: StorageResolver
) -> None:
    for name in ("_sftp", "_host", "_port"):
        monkeypatch.setattr(sftp_instance, name, None)
    backend, path = resolver.resolve("sftp://anywhere.example/data/a.txt")
    assert (backend, path) == (SFTPStorage(), "data/a.txt")
    with pytest.raises(StorageUnavailableException, match="later_init"):
        backend.exists(path)


def test_another_host_is_reached_through_a_mount(
    shared: FakeSFTP, resolver: StorageResolver
) -> None:
    backup_session = FakeSFTP()
    resolver.mount(
        "sftp://backup.example", SFTPStorage(connected(backup_session, host="backup.example"))
    )
    File("sftp://nas.example/a.txt", resolver=resolver).write(b"payload")
    File("sftp://nas.example/a.txt", resolver=resolver).copy_to(
        File("sftp://backup.example/copies/a.txt", resolver=resolver)
    )
    assert backup_session.read("/copies/a.txt") == b"payload"
    assert shared.paths() == ["/a.txt"]


# ---------------------------------------------------------------------- one caller at a time


def test_a_session_serves_one_operation_at_a_time(storage: SFTPStorage, session: FakeSFTP) -> None:
    acquired: list[bool] = []

    def from_another_thread() -> None:
        thread = threading.Thread(
            target=lambda: acquired.append(session_lock(session).acquire(blocking=False))
        )
        thread.start()
        thread.join()

    session.on_call = from_another_thread
    storage.write_bytes("dir/a.txt", b"x")
    storage.list_dir("", recursive=True)
    storage.delete("dir", recursive=True)
    assert acquired
    assert not any(acquired)
    assert session_lock(session) is session_lock(session)
    assert session_lock(session) is not session_lock(FakeSFTP())


# ---------------------------------------------------------------------- the real paramiko client


@pytest.mark.parametrize(
    "method,arguments",
    [
        ("stat", ("/a",)),
        ("lstat", ("/a",)),
        ("listdir_attr", ("/a",)),
        ("put", ("local", "/a")),
        ("get", ("/a", "local")),
        ("remove", ("/a",)),
        ("mkdir", ("/a",)),
        ("rmdir", ("/a",)),
        ("posix_rename", ("/a", "/b")),
        ("rename", ("/a", "/b")),
        ("get_channel", ()),
    ],
)
def test_paramiko_has_the_calls_the_adapter_makes(method: str, arguments: tuple[str, ...]) -> None:
    real = inspect.signature(getattr(paramiko.SFTPClient, method))
    real.bind(None, *arguments)
    stand_in = list(inspect.signature(getattr(FakeSFTP, method)).parameters)
    assert list(real.parameters)[: len(stand_in)] == stand_in


def test_paramiko_attributes_carry_the_fields_the_adapter_reads() -> None:
    attributes = paramiko.SFTPAttributes()
    assert (attributes.st_mode, attributes.st_size, attributes.st_mtime) == (None, None, None)
    assert issubclass(paramiko.SSHException, Exception)
    assert not issubclass(paramiko.SFTPError, OSError)


def test_two_roots_of_one_session_do_not_lose_a_file_to_itself(session: FakeSFTP) -> None:
    client = connected(session)
    whole = SFTPStorage(client)
    whole.mkdir("team/a")
    inner = SFTPStorage(client, root="/team/a")
    inner.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(inner, "docs/a.txt", "team/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        inner.move_from(whole, "team/a/docs/a.txt", "docs/a.txt")
    assert whole.read_bytes("team/a/docs/a.txt") == b"payload"
