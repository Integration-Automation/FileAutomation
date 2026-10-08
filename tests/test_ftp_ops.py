"""FTP / FTPS backend tests.

Live FTP servers are outside CI; these tests exercise the registry wiring,
facade exports, guard clauses, and offline error-path behaviour.
"""

# pylint: disable=no-member  # the member exists on the object the fixture builds
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from automation_file import (
    FTPClient,
    FTPConnectOptions,
    FTPException,
    build_default_registry,
    ftp_instance,
    register_ftp_ops,
)
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import FileNotExistsException
from automation_file.remote.ftp import delete_ops, download_ops, list_ops, upload_ops


class _FakeFTP:
    def __init__(self) -> None:
        self.stored: list[tuple[str, bytes]] = []
        self.deleted: list[str] = []
        self.retrieved: list[str] = []
        self.dirs: list[str] = []
        self.listings: dict[str, list[str]] = {".": ["a.txt", "b.txt"]}

    def storbinary(self, cmd: str, fp: Any) -> None:
        self.stored.append((cmd, fp.read()))

    def retrbinary(self, cmd: str, callback: Any) -> None:
        self.retrieved.append(cmd)
        callback(b"payload")

    def delete(self, path: str) -> None:
        self.deleted.append(path)

    def mkd(self, path: str) -> None:
        self.dirs.append(path)

    def nlst(self, path: str) -> list[str]:
        return self.listings.get(path, [])


@pytest.fixture(name="fake_ftp")
def _fake_ftp(monkeypatch: pytest.MonkeyPatch) -> _FakeFTP:
    fake = _FakeFTP()
    monkeypatch.setattr(ftp_instance, "_ftp", fake, raising=False)
    return fake


def test_register_ftp_ops_adds_entries() -> None:
    registry = ActionRegistry()
    register_ftp_ops(registry)
    for name in (
        "FA_ftp_later_init",
        "FA_ftp_close",
        "FA_ftp_upload_file",
        "FA_ftp_upload_dir",
        "FA_ftp_download_file",
        "FA_ftp_delete_path",
        "FA_ftp_list_dir",
    ):
        assert name in registry


def test_default_registry_contains_ftp() -> None:
    registry = build_default_registry()
    assert "FA_ftp_upload_file" in registry
    assert "FA_ftp_list_dir" in registry


def test_require_ftp_raises_when_not_initialised() -> None:
    client = FTPClient()
    with pytest.raises(FTPException):
        client.require_ftp()


def test_connect_options_defaults() -> None:
    opts = FTPConnectOptions(host="example.org")
    assert opts.port == 21
    assert opts.tls is False
    assert opts.username == "anonymous"


def test_upload_file_missing_source_raises(fake_ftp: _FakeFTP, tmp_path: Path) -> None:
    missing = tmp_path / "nope.txt"
    with pytest.raises(FileNotExistsException):
        upload_ops.ftp_upload_file(str(missing), "remote/nope.txt")
    assert not fake_ftp.stored


def test_upload_file_stores_payload(fake_ftp: _FakeFTP, tmp_path: Path) -> None:
    src = tmp_path / "hello.txt"
    src.write_bytes(b"hi there")
    assert upload_ops.ftp_upload_file(str(src), "out/hello.txt") is True
    assert fake_ftp.stored == [("STOR out/hello.txt", b"hi there")]
    assert "out" in fake_ftp.dirs


def test_upload_dir_uploads_all_files(fake_ftp: _FakeFTP, tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_bytes(b"A")
    (tmp_path / "sub" / "b.txt").write_bytes(b"B")
    uploaded = upload_ops.ftp_upload_dir(str(tmp_path), "root")
    assert sorted(uploaded) == ["root/a.txt", "root/sub/b.txt"]
    assert {cmd for cmd, _ in fake_ftp.stored} == {
        "STOR root/a.txt",
        "STOR root/sub/b.txt",
    }


def test_download_file_writes_target(fake_ftp: _FakeFTP, tmp_path: Path) -> None:
    target = tmp_path / "out" / "file.bin"
    assert download_ops.ftp_download_file("remote/file.bin", str(target)) is True
    assert target.read_bytes() == b"payload"
    assert fake_ftp.retrieved == ["RETR remote/file.bin"]


def test_delete_path_calls_delete(fake_ftp: _FakeFTP) -> None:
    assert delete_ops.ftp_delete_path("remote/x") is True
    assert fake_ftp.deleted == ["remote/x"]


def test_list_dir_returns_names(fake_ftp: _FakeFTP) -> None:
    assert list_ops.ftp_list_dir(".") == fake_ftp.listings["."]


def test_close_on_fresh_client_is_noop() -> None:
    client = FTPClient()
    assert client.close() is True


class _StubSession:
    """What ``later_init`` drives: connect, log in, choose the transfer mode, quit."""

    def __init__(self, timeout: float | None = None) -> None:
        self.steps: list[str] = []

    def connect(self, host: str, port: int, timeout: float | None = None) -> None:
        self.steps.append(f"connect {host}:{port}")

    def auth(self) -> None:
        self.steps.append("auth")

    def login(self, user: str = "", passwd: str = "") -> None:  # nosec B107  # ftplib's own default
        self.steps.append("login")

    def prot_p(self) -> None:
        self.steps.append("prot_p")

    def set_pasv(self, value: bool) -> None:
        self.steps.append("set_pasv")

    def quit(self) -> None:
        self.steps.append("quit")


class _StubTLSSession(_StubSession):
    """Stands in for ``FTP_TLS``, the session type that marks a session as FTPS."""


@pytest.mark.parametrize("tls", [False, True])
def test_client_reports_the_host_port_and_tls_of_its_session(
    monkeypatch: pytest.MonkeyPatch, tls: bool
) -> None:
    from automation_file.remote.ftp import client as client_module

    monkeypatch.setattr(client_module, "FTP", _StubSession)
    monkeypatch.setattr(client_module, "FTP_TLS", _StubTLSSession)
    client = FTPClient()
    assert (client.host, client.port, client.tls) == (None, None, False)
    session = client.later_init(host="files.example", port=2121, username="ops", tls=tls)
    assert (client.host, client.port, client.tls) == ("files.example", 2121, tls)
    assert session.steps[0] == "connect files.example:2121"
    assert ("prot_p" in session.steps) is tls
    assert set(vars(client)) == {"_ftp", "_host", "_port"}
    for name in ("host", "port", "tls"):
        with pytest.raises(AttributeError):
            setattr(client, name, None)
    client.close()
    assert (client.host, client.port, client.tls) == (None, None, False)
    assert session.steps[-1] == "quit"
