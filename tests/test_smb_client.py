"""Tests for automation_file.remote.smb.client."""

# pylint: disable=redefined-outer-name,undefined-variable  # pytest fixtures + lazy annotations
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from automation_file.exceptions import SMBException
from automation_file.remote.smb.client import SMBClient


class _FakeDirEntry:
    def __init__(self, name: str, is_dir: bool, size: int) -> None:
        self.name = name
        self._is_dir = is_dir
        self._size = size

    def is_dir(self) -> bool:
        return self._is_dir

    def stat(self) -> MagicMock:
        stat_result = MagicMock()
        stat_result.st_size = self._size
        return stat_result


@pytest.fixture
def smbclient_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Install a fake ``smbclient`` module so tests never hit the network."""

    fake = ModuleType("smbclient")
    fake.register_session = MagicMock()  # type: ignore[attr-defined]
    fake.delete_session = MagicMock()  # type: ignore[attr-defined]
    fake.stat = MagicMock()  # type: ignore[attr-defined]
    fake.open_file = MagicMock()  # type: ignore[attr-defined]
    fake.remove = MagicMock()  # type: ignore[attr-defined]
    fake.makedirs = MagicMock()  # type: ignore[attr-defined]
    fake.rmdir = MagicMock()  # type: ignore[attr-defined]
    fake.scandir = MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "smbclient", fake)
    return fake


def test_rejects_empty_server() -> None:
    with pytest.raises(SMBException):
        SMBClient("", "share")


def test_rejects_empty_share() -> None:
    with pytest.raises(SMBException):
        SMBClient("server", "")


def test_exists_true(smbclient_module: ModuleType) -> None:
    client = SMBClient("fs", "pub", "u", "p")
    assert client.exists("foo/bar.txt") is True
    call_args, _ = smbclient_module.stat.call_args  # type: ignore[attr-defined]
    assert call_args[0] == "\\\\fs\\pub\\foo\\bar.txt"


def test_exists_false_on_file_not_found(smbclient_module: ModuleType) -> None:
    smbclient_module.stat.side_effect = FileNotFoundError  # type: ignore[attr-defined]
    client = SMBClient("fs", "pub")
    assert client.exists("missing") is False


def test_exists_wraps_os_error(smbclient_module: ModuleType) -> None:
    smbclient_module.stat.side_effect = OSError("boom")  # type: ignore[attr-defined]
    client = SMBClient("fs", "pub")
    with pytest.raises(SMBException):
        client.exists("x")


def test_upload_streams_file(smbclient_module: ModuleType, tmp_path: Path) -> None:
    local = tmp_path / "data.bin"
    local.write_bytes(b"abcdefg")
    written: list[bytes] = []

    class _FakeRemoteWrite:
        def __enter__(self) -> _FakeRemoteWrite:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def write(self, chunk: bytes) -> None:
            written.append(chunk)

    smbclient_module.open_file.return_value = _FakeRemoteWrite()  # type: ignore[attr-defined]
    client = SMBClient("fs", "pub")
    client.upload(local, "remote/data.bin")
    assert b"".join(written) == b"abcdefg"
    call_args, call_kwargs = smbclient_module.open_file.call_args  # type: ignore[attr-defined]
    assert call_args[0] == "\\\\fs\\pub\\remote\\data.bin"
    assert call_kwargs["mode"] == "wb"


def test_upload_rejects_missing_local(smbclient_module: ModuleType, tmp_path: Path) -> None:
    client = SMBClient("fs", "pub")
    with pytest.raises(SMBException):
        client.upload(tmp_path / "absent", "remote/data.bin")


def test_download_writes_file(smbclient_module: ModuleType, tmp_path: Path) -> None:
    class _FakeRemoteRead:
        def __init__(self) -> None:
            self._chunks = [b"hello", b"-", b"world", b""]

        def __enter__(self) -> _FakeRemoteRead:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return self._chunks.pop(0)

    smbclient_module.open_file.return_value = _FakeRemoteRead()  # type: ignore[attr-defined]
    client = SMBClient("fs", "pub")
    dest = tmp_path / "out" / "copy.bin"
    client.download("remote/data.bin", dest)
    assert dest.read_bytes() == b"hello-world"


def test_delete_calls_remove(smbclient_module: ModuleType) -> None:
    client = SMBClient("fs", "pub")
    client.delete("old.txt")
    call_args, _ = smbclient_module.remove.call_args  # type: ignore[attr-defined]
    assert call_args[0] == "\\\\fs\\pub\\old.txt"


def test_mkdir_uses_makedirs(smbclient_module: ModuleType) -> None:
    client = SMBClient("fs", "pub")
    client.mkdir("a/b/c")
    call_args, call_kwargs = smbclient_module.makedirs.call_args  # type: ignore[attr-defined]
    assert call_args[0] == "\\\\fs\\pub\\a\\b\\c"
    assert call_kwargs["exist_ok"] is True


def test_rmdir_calls_rmdir(smbclient_module: ModuleType) -> None:
    client = SMBClient("fs", "pub")
    client.rmdir("old-folder")
    call_args, _ = smbclient_module.rmdir.call_args  # type: ignore[attr-defined]
    assert call_args[0] == "\\\\fs\\pub\\old-folder"


def test_list_dir_returns_entries(smbclient_module: ModuleType) -> None:
    smbclient_module.scandir.return_value = iter(  # type: ignore[attr-defined]
        [
            _FakeDirEntry("sub", is_dir=True, size=0),
            _FakeDirEntry("data.bin", is_dir=False, size=7),
        ]
    )
    client = SMBClient("fs", "pub")
    entries = client.list_dir("folder")
    assert len(entries) == 2
    assert entries[0].name == "sub"
    assert entries[0].is_dir is True
    assert entries[0].size is None
    assert entries[1].name == "data.bin"
    assert entries[1].is_dir is False
    assert entries[1].size == 7


def test_close_is_idempotent(smbclient_module: ModuleType) -> None:
    client = SMBClient("fs", "pub")
    # Never registered — close should be a no-op.
    client.close()
    assert smbclient_module.delete_session.call_count == 0  # type: ignore[attr-defined]
    client.exists("foo")
    client.close()
    client.close()
    assert smbclient_module.delete_session.call_count == 1  # type: ignore[attr-defined]


def test_context_manager_closes(smbclient_module: ModuleType) -> None:
    with SMBClient("fs", "pub") as client:
        client.exists("x")
    assert smbclient_module.delete_session.call_count == 1  # type: ignore[attr-defined]


def test_unc_root(smbclient_module: ModuleType) -> None:
    client = SMBClient("fs", "pub")
    client.list_dir("")
    call_args, _ = smbclient_module.scandir.call_args  # type: ignore[attr-defined]
    assert call_args[0] == "\\\\fs\\pub"
