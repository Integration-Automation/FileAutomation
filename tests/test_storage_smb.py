"""SMBStorage: the storage contract against an in-memory stand-in for ``smbclient``.

``smbprotocol`` is an optional dependency, so the tests install a module named
``smbclient`` that keeps a share in memory. It answers the calls ``SMBClient``
makes -- ``register_session``, ``stat``, ``scandir``, ``open_file``, ``remove``,
``rmdir``, ``makedirs``, ``rename`` and ``replace`` -- and fails the way
smbprotocol does: with an ``OSError`` subclass of its own that carries an errno
and an NTSTATUS code. The real ``SMBClient`` runs on top of it.
"""

from __future__ import annotations

import errno
import io
import os
import stat
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType
from typing import Any

import pytest

from automation_file.exceptions import (
    StorageException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.remote.smb.client import SMBClient
from automation_file.storage import File, StorageBackend, StorageResolver
from automation_file.storage.smb_storage import SMB_SCHEME, SMBStorage
from tests.storage_contract import StorageContract

SERVER = "nas.example.com"
SHARE = "projects"
SHARE_ROOT = f"\\\\{SERVER}\\{SHARE}"
PORT = 4455
STATUS_ACCESS_DENIED = 0xC0000022
STATUS_UNSUCCESSFUL = 0xC0000001


class FakeSMBOSError(OSError):
    """Shaped like ``smbprotocol.exceptions.SMBOSError``: an errno and the NTSTATUS behind it."""

    def __init__(self, code: int, path: str, ntstatus: int = STATUS_UNSUCCESSFUL) -> None:
        super().__init__(code, os.strerror(code) if code else "Unknown NtStatus error", path)
        self.ntstatus = ntstatus


class _Writer(io.BytesIO):
    def __init__(self, share: FakeShare, path: str) -> None:
        super().__init__()
        self._share = share
        self._path = path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._share.nodes[self._path] = self.getvalue()
        self._share.modified[self._path] = self._share.clock()
        super().__exit__(exc_type, exc, tb)


class _DirEntry:
    def __init__(self, share: FakeShare, path: str) -> None:
        self._share = share
        self._path = path
        self.name = path.rpartition("\\")[2]

    def is_dir(self) -> bool:
        return self._share.nodes[self._path] is None

    def stat(self) -> SimpleNamespace:
        return self._share.stat_result(self._path)


class FakeShare:
    """One share, keyed by UNC path. ``None`` marks a directory, bytes a file."""

    def __init__(self) -> None:
        self.nodes: dict[str, bytes | None] = {SHARE_ROOT: None}
        self.modified: dict[str, float] = {SHARE_ROOT: 0.0}
        self.calls: list[str] = []
        self.ports: set[Any] = set()
        self.fail_with: Exception | None = None
        self.refuse_session_with: Exception | None = None
        self._ticks = 0

    # ------------------------------------------------------------------ helpers

    def clock(self) -> float:
        self._ticks += 1
        return 1_791_000_000.0 + self._ticks

    def stat_result(self, path: str) -> SimpleNamespace:
        data = self.nodes[path]
        return SimpleNamespace(
            st_mode=(stat.S_IFDIR | 0o755) if data is None else (stat.S_IFREG | 0o644),
            st_size=0 if data is None else len(data),
            st_mtime=self.modified[path],
        )

    def _begin(self, call: str, options: dict[str, Any]) -> None:
        self.calls.append(call)
        self.ports.add(options.get("port"))
        if self.fail_with is not None:
            raise self.fail_with

    def _existing(self, path: str) -> bytes | None:
        """Return the node at ``path``; fail like the server for a missing one."""
        if path in self.nodes:
            return self.nodes[path]
        assert path.startswith(f"{SHARE_ROOT}\\"), f"request left the share: {path}"
        parent = path.rpartition("\\")[0]
        while parent not in self.nodes:
            parent = parent.rpartition("\\")[0]
        code = errno.ENOTDIR if self.nodes[parent] is not None else errno.ENOENT
        raise FakeSMBOSError(code, path)

    def _children(self, path: str) -> list[str]:
        below = f"{path}\\"
        return sorted(
            name for name in self.nodes if name.startswith(below) and "\\" not in name[len(below) :]
        )

    def _require_directory(self, path: str) -> None:
        if self._existing(path) is not None:
            raise FakeSMBOSError(errno.ENOTDIR, path)

    # ------------------------------------------------------------------ the smbclient surface

    def register_session(self, server: str, **options: Any) -> None:
        self._begin("register_session", options)
        assert server == SERVER
        if self.refuse_session_with is not None:
            raise self.refuse_session_with

    def delete_session(self, server: str, **options: Any) -> None:
        self._begin("delete_session", options)
        assert server == SERVER

    def stat(self, path: str, **options: Any) -> SimpleNamespace:
        self._begin("stat", options)
        self._existing(path)
        return self.stat_result(path)

    def scandir(self, path: str, **options: Any) -> Iterator[_DirEntry]:
        self._begin("scandir", options)
        self._require_directory(path)
        return iter([_DirEntry(self, name) for name in self._children(path)])

    def open_file(self, path: str, mode: str = "r", **options: Any) -> io.BytesIO:
        self._begin(f"open_file:{mode}", options)
        if mode == "rb":
            data = self._existing(path)
            if data is None:
                raise FakeSMBOSError(errno.EISDIR, path)
            return io.BytesIO(data)
        assert mode == "wb"
        self._require_directory(path.rpartition("\\")[0])
        if self.nodes.get(path, b"") is None:
            raise FakeSMBOSError(errno.EISDIR, path)
        return _Writer(self, path)

    def remove(self, path: str, **options: Any) -> None:
        self._begin("remove", options)
        if self._existing(path) is None:
            raise FakeSMBOSError(errno.EISDIR, path)
        del self.nodes[path]

    def rmdir(self, path: str, **options: Any) -> None:
        self._begin("rmdir", options)
        self._require_directory(path)
        if self._children(path):
            raise FakeSMBOSError(errno.ENOTEMPTY, path)
        del self.nodes[path]

    def makedirs(self, path: str, exist_ok: bool = False, **options: Any) -> None:
        self._begin("makedirs", options)
        if path in self.nodes:
            if not exist_ok or self.nodes[path] is not None:
                raise FakeSMBOSError(errno.EEXIST, path)
            return
        missing: list[str] = []
        current = path
        while current not in self.nodes:
            missing.append(current)
            current = current.rpartition("\\")[0]
        self._require_directory(current)
        for directory in reversed(missing):
            self.nodes[directory] = None
            self.modified[directory] = self.clock()

    def _rename(self, source: str, target: str, *, replace: bool) -> None:
        data = self._existing(source)
        self._require_directory(target.rpartition("\\")[0])
        if target in self.nodes and (not replace or self.nodes[target] is None):
            raise FakeSMBOSError(errno.EEXIST, target)
        self.nodes[target] = data
        self.modified[target] = self.modified[source]
        del self.nodes[source]

    def rename(self, source: str, target: str, **options: Any) -> None:
        self._begin("rename", options)
        self._rename(source, target, replace=False)

    def replace(self, source: str, target: str, **options: Any) -> None:
        self._begin("replace", options)
        self._rename(source, target, replace=True)


class _ProtocolError(Exception):
    """Stands in for ``smbprotocol.exceptions.SMBException``, the base of its own errors."""


class _LogonFailure(_ProtocolError):
    """Stands in for ``smbprotocol.exceptions.LogonFailure``."""


@pytest.fixture
def share(monkeypatch: pytest.MonkeyPatch) -> FakeShare:
    """Install an in-memory ``smbclient`` and the ``smbprotocol.exceptions`` it raises from."""
    fake = FakeShare()
    module = ModuleType("smbclient")
    for name in (
        "register_session",
        "delete_session",
        "stat",
        "scandir",
        "open_file",
        "remove",
        "rmdir",
        "makedirs",
        "rename",
        "replace",
    ):
        setattr(module, name, getattr(fake, name))
    errors = ModuleType("smbprotocol.exceptions")
    errors.SMBException = _ProtocolError  # type: ignore[attr-defined]
    errors.LogonFailure = _LogonFailure  # type: ignore[attr-defined]
    package = ModuleType("smbprotocol")
    package.exceptions = errors  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "smbclient", module)
    monkeypatch.setitem(sys.modules, "smbprotocol", package)
    monkeypatch.setitem(sys.modules, "smbprotocol.exceptions", errors)
    return fake


@pytest.fixture
def client(share: FakeShare) -> SMBClient:  # pylint: disable=unused-argument
    return SMBClient(SERVER, SHARE, port=PORT)


@pytest.fixture
def storage(client: SMBClient) -> SMBStorage:
    return SMBStorage(client)


class TestSMBStorageContract(StorageContract):
    @pytest.fixture
    def backend(self, client: SMBClient) -> StorageBackend:
        return SMBStorage(client)


class TestRootedSMBStorageContract(StorageContract):
    @pytest.fixture
    def backend(self, client: SMBClient, share: FakeShare) -> StorageBackend:
        share.makedirs(f"{SHARE_ROOT}\\team\\a", port=PORT)
        share.makedirs(f"{SHARE_ROOT}\\other-team", port=PORT)
        share.nodes[f"{SHARE_ROOT}\\other-team\\keep.txt"] = b"keep"
        share.modified[f"{SHARE_ROOT}\\other-team\\keep.txt"] = share.clock()
        return SMBStorage(client, root="team/a")


def test_stat_reports_size_and_modification_time(storage: SMBStorage, share: FakeShare) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    path = f"{SHARE_ROOT}\\reports\\q1.json"
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.modified_at == datetime.fromtimestamp(share.modified[path], tz=timezone.utc)
    assert info.modified_at.utcoffset() == timedelta(0)
    assert (info.etag, info.version, info.content_type) == (None, None, None)
    folder = storage.stat("reports")
    assert (folder.is_dir, folder.size) == (True, None)
    assert folder.modified_at is not None


def test_a_time_before_1970_is_reported(storage: SMBStorage, share: FakeShare) -> None:
    storage.write_bytes("old.txt", b"x")
    # A server that keeps no time sends the FILETIME epoch, the year 1601.
    share.modified[f"{SHARE_ROOT}\\old.txt"] = -11_644_473_600.0
    assert storage.stat("old.txt").modified_at == datetime(1601, 1, 1, tzinfo=timezone.utc)
    share.modified[f"{SHARE_ROOT}\\old.txt"] = 1e20
    assert storage.stat("old.txt").modified_at is None


def test_listing_carries_sizes_and_times(storage: SMBStorage) -> None:
    for path in ("dir/b.txt", "dir/a.txt", "dir/sub/c.txt"):
        storage.write_bytes(path, b"xy")
    listing = storage.list_dir("dir")
    assert [(info.path, info.is_dir, info.size) for info in listing] == [
        ("dir/a.txt", False, 2),
        ("dir/b.txt", False, 2),
        ("dir/sub", True, None),
    ]
    assert all(info.modified_at is not None for info in listing)


def test_every_call_goes_to_the_port_of_the_client(storage: SMBStorage, share: FakeShare) -> None:
    storage.write_bytes("dir/a.txt", b"x")
    storage.move_from(storage, "dir/a.txt", "dir/b.txt")
    storage.list_dir("dir")
    storage.read_bytes("dir/b.txt")
    storage.delete("dir", recursive=True)
    assert share.ports == {PORT}
    assert {"stat", "scandir", "open_file:wb", "open_file:rb", "remove", "rmdir"} <= set(
        share.calls
    )


def test_a_move_within_one_client_is_a_rename(storage: SMBStorage, share: FakeShare) -> None:
    storage.write_bytes("a.txt", b"payload")
    storage.write_bytes("moved/b.txt", b"old")
    share.calls.clear()
    storage.move_from(storage, "a.txt", "moved/b.txt")
    assert share.nodes[f"{SHARE_ROOT}\\moved\\b.txt"] == b"payload"
    assert f"{SHARE_ROOT}\\a.txt" not in share.nodes
    assert share.calls.count("replace") == 1
    assert not {"open_file:rb", "open_file:wb", "remove"} & set(share.calls)


def test_a_copy_goes_through_a_staging_file(storage: SMBStorage, share: FakeShare) -> None:
    storage.write_bytes("a.txt", b"payload")
    share.calls.clear()
    storage.copy_from(storage, "a.txt", "copies/b.txt")
    assert share.nodes[f"{SHARE_ROOT}\\copies\\b.txt"] == b"payload"
    assert share.nodes[f"{SHARE_ROOT}\\a.txt"] == b"payload"
    assert {"open_file:rb", "open_file:wb"} <= set(share.calls)


def test_a_move_between_two_clients_copies_then_deletes(
    storage: SMBStorage, share: FakeShare
) -> None:
    other = SMBStorage(SMBClient(SERVER, SHARE, port=PORT))
    storage.write_bytes("a.txt", b"payload")
    share.calls.clear()
    other.move_from(storage, "a.txt", "b.txt")
    assert share.nodes[f"{SHARE_ROOT}\\b.txt"] == b"payload"
    assert f"{SHARE_ROOT}\\a.txt" not in share.nodes
    assert "replace" not in share.calls


def test_a_backslash_is_a_separator(storage: SMBStorage, share: FakeShare) -> None:
    storage.write_bytes("dir\\sub\\a.txt", b"x")
    assert share.nodes[f"{SHARE_ROOT}\\dir\\sub\\a.txt"] == b"x"
    assert storage.stat("dir/sub\\a.txt").path == "dir/sub/a.txt"
    assert [info.path for info in storage.list_dir("dir\\sub")] == ["dir/sub/a.txt"]


@pytest.mark.parametrize("path", ["a\\..\\..\\secret.txt", "..\\secret.txt", "dir/..\\..\\x"])
def test_a_backslash_cannot_smuggle_a_parent_segment(
    client: SMBClient, share: FakeShare, path: str
) -> None:
    share.nodes[f"{SHARE_ROOT}\\secret.txt"] = b"secret"
    share.modified[f"{SHARE_ROOT}\\secret.txt"] = share.clock()
    rooted = SMBStorage(client, root="team")
    with pytest.raises(StorageURIException):
        rooted.exists(path)
    with pytest.raises(StorageURIException):
        rooted.write_bytes(path, b"overwritten")
    with pytest.raises(StorageURIException):
        SMBStorage(client, root="team\\..\\..")
    assert share.nodes[f"{SHARE_ROOT}\\secret.txt"] == b"secret"
    assert share.calls == []


def _denied_without_errno() -> FakeSMBOSError:
    return FakeSMBOSError(0, "a.txt", STATUS_ACCESS_DENIED)


@pytest.mark.parametrize(
    "error,expected",
    [
        (FakeSMBOSError(errno.EACCES, "a.txt"), StoragePermissionException),
        (_denied_without_errno(), StoragePermissionException),
        (PermissionError(errno.EPERM, "not permitted"), StoragePermissionException),
        (ConnectionResetError(errno.ECONNRESET, "reset"), StorageTransientException),
        (TimeoutError("timed out"), StorageTransientException),
        (FakeSMBOSError(errno.EIO, "a.txt"), StorageException),
        (OSError("boom"), StorageException),
        (ValueError("Failed to connect to 'nas.example.com:445'"), StorageException),
        (_ProtocolError("Socket connection has been closed"), StorageException),
    ],
)
def test_client_errors_become_storage_errors(
    storage: SMBStorage, share: FakeShare, error: Exception, expected: type[Exception]
) -> None:
    storage.write_bytes("a.txt", b"x")
    share.fail_with = error
    with pytest.raises(expected) as caught:
        storage.read_bytes("a.txt")
    assert type(caught.value) is expected
    chain = [caught.value.__cause__, caught.value.__cause__.__cause__]
    assert error in chain


def _refused_connection() -> ValueError:
    error = ValueError("Failed to connect to 'nas.example.com:445'")
    error.__cause__ = ConnectionRefusedError(errno.ECONNREFUSED, "refused")
    return error


@pytest.mark.parametrize(
    "refusal,expected",
    [
        (_LogonFailure("bad credentials"), StoragePermissionException),
        (_refused_connection(), StorageTransientException),
        (_ProtocolError("negotiation failed"), StorageException),
    ],
)
def test_a_session_that_cannot_be_opened_is_reported(
    storage: SMBStorage, share: FakeShare, refusal: Exception, expected: type[Exception]
) -> None:
    share.refuse_session_with = refusal
    with pytest.raises(expected) as caught:
        storage.exists("a.txt")
    assert type(caught.value) is expected
    assert caught.value.__cause__.__cause__ is refusal


def test_a_missing_path_is_told_by_its_errno(storage: SMBStorage, share: FakeShare) -> None:
    storage.write_bytes("a.txt", b"x")
    assert storage.exists("nope.txt") is False
    assert storage.exists("nope/deeper.txt") is False
    assert storage.exists("a.txt/child.txt") is False
    assert not isinstance(FakeSMBOSError(errno.ENOENT, "x"), FileNotFoundError)
    share.fail_with = FileNotFoundError(errno.ENOENT, "gone")
    assert storage.exists("a.txt") is False


def test_smbprotocol_must_be_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "smbclient", None)
    monkeypatch.setitem(sys.modules, "smbprotocol", None)
    storage = SMBStorage(SMBClient(SERVER, SHARE))
    with pytest.raises(StorageUnavailableException, match="smbprotocol is not installed"):
        storage.exists("a.txt")


def test_a_mounted_backend_serves_its_uris(
    storage: SMBStorage, share: FakeShare, tmp_path: Path
) -> None:
    resolver = StorageResolver()
    resolver.mount(f"smb://{SERVER}/{SHARE}", storage)
    plan = File(f"smb://{SERVER}/{SHARE}/2026/plan.txt", resolver=resolver)
    plan.write(b"plan")
    assert share.nodes[f"{SHARE_ROOT}\\2026\\plan.txt"] == b"plan"
    assert resolver.resolve(f"smb://{SERVER.upper()}/{SHARE}/2026/plan.txt") == (
        storage,
        "2026/plan.txt",
    )
    assert resolver.capabilities(f"smb://{SERVER}/{SHARE}").directories is True
    plan.copy_to(tmp_path / "plan.txt")
    assert (tmp_path / "plan.txt").read_bytes() == b"plan"
    plan.move_to(f"smb://{SERVER}/{SHARE}/archive/plan.txt")
    assert f"{SHARE_ROOT}\\2026\\plan.txt" not in share.nodes
    with pytest.raises(StorageURIException, match="no mount"):
        resolver.resolve(f"smb://{SERVER}/another-share/a.txt")


def test_uri_equality_and_repr(client: SMBClient) -> None:
    assert SMBStorage(client).uri_for("") == f"smb://{SERVER}/{SHARE}"
    assert SMBStorage(client).uri_for("a\\b.txt") == f"smb://{SERVER}/{SHARE}/a/b.txt"
    rooted = SMBStorage(client, root="\\team\\\\a/")
    assert rooted.root == "team/a"
    assert rooted.uri_for("b.txt") == f"smb://{SERVER}/{SHARE}/team/a/b.txt"
    assert repr(rooted) == f"SMBStorage('smb://{SERVER}/{SHARE}/team/a')"
    assert SMBStorage(client) == SMBStorage(client)
    assert SMBStorage(client) != rooted
    assert SMBStorage(client) != SMBStorage(SMBClient(SERVER, SHARE))
    assert len({SMBStorage(client), SMBStorage(client)}) == 1
    assert SMBStorage.scheme == SMB_SCHEME == "smb"
    capabilities = SMBStorage.capabilities
    assert (capabilities.directories, capabilities.modified_at) == (True, True)
    assert (capabilities.etag, capabilities.version, capabilities.content_type) == (
        False,
        False,
        False,
    )


def test_two_roots_of_one_share_do_not_lose_a_file_to_itself(client: SMBClient) -> None:
    whole = SMBStorage(client)
    inner = SMBStorage(client, root="team/a")
    whole.mkdir("team/a")
    inner.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(inner, "docs/a.txt", "team/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        inner.move_from(whole, "team/a/docs/a.txt", "docs/a.txt")
    assert whole.read_bytes("team/a/docs/a.txt") == b"payload"
