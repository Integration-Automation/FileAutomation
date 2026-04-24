"""OneDrive backend tests.

Live Microsoft Graph endpoints are outside CI; these tests verify registry
wiring, guard clauses, and that ``graph_request`` surfaces non-2xx
responses as :class:`OneDriveException`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from automation_file import (
    OneDriveClient,
    OneDriveException,
    build_default_registry,
    onedrive_instance,
    register_onedrive_ops,
)
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import FileNotExistsException
from automation_file.remote.onedrive import delete_ops, download_ops, list_ops, upload_ops


class _FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None, content: bytes = b"") -> None:
        self.status_code = status
        self.text = "" if status < 400 else "fake-error"
        self.content = content
        self._payload = payload or {}
        self.ok = status < 400

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, responder: Any) -> None:
        self.headers: dict[str, str] = {}
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self._responder(method, url, **kwargs)

    def close(self) -> None:
        return None


@pytest.fixture(name="fake_client")
def _fake_client(monkeypatch: pytest.MonkeyPatch) -> OneDriveClient:
    client = OneDriveClient()

    def responder(method: str, url: str, **_kwargs: Any) -> _FakeResponse:
        if method == "GET" and "/children" in url:
            return _FakeResponse(
                200,
                payload={
                    "value": [
                        {"name": "a.txt", "size": 4},
                        {"name": "dir", "folder": {}},
                    ]
                },
            )
        if method == "GET" and "/content" in url:
            return _FakeResponse(200, content=b"hello")
        if method == "PUT":
            return _FakeResponse(201, payload={"id": "abc"})
        if method == "DELETE":
            return _FakeResponse(204)
        return _FakeResponse(404)

    session = _FakeSession(responder)
    client._session = session  # type: ignore[attr-defined]  # test injection
    client._access_token = "fake-token"  # type: ignore[attr-defined]
    monkeypatch.setattr(onedrive_instance, "_session", session, raising=False)
    monkeypatch.setattr(onedrive_instance, "_access_token", "fake-token", raising=False)
    return client


def test_require_session_raises_when_not_initialised() -> None:
    client = OneDriveClient()
    with pytest.raises(OneDriveException):
        client.require_session()


def test_later_init_rejects_empty_token() -> None:
    client = OneDriveClient()
    with pytest.raises(OneDriveException):
        client.later_init("")


def test_default_registry_contains_onedrive() -> None:
    registry = build_default_registry()
    assert "FA_onedrive_upload_file" in registry
    assert "FA_onedrive_device_code_login" in registry


def test_register_onedrive_ops_adds_entries() -> None:
    registry = ActionRegistry()
    register_onedrive_ops(registry)
    for name in (
        "FA_onedrive_later_init",
        "FA_onedrive_upload_file",
        "FA_onedrive_upload_dir",
        "FA_onedrive_download_file",
        "FA_onedrive_delete_item",
        "FA_onedrive_list_folder",
        "FA_onedrive_close",
    ):
        assert name in registry


def test_upload_rejects_missing_source(tmp_path: Path, fake_client: OneDriveClient) -> None:
    del fake_client
    with pytest.raises(FileNotExistsException):
        upload_ops.onedrive_upload_file(str(tmp_path / "gone.txt"), "x.txt")


def test_upload_rejects_oversize(tmp_path: Path, fake_client: OneDriveClient) -> None:
    del fake_client
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * (4 * 1024 * 1024 + 1))
    with pytest.raises(OneDriveException):
        upload_ops.onedrive_upload_file(str(big), "x.bin")


def test_upload_roundtrip(tmp_path: Path, fake_client: OneDriveClient) -> None:
    src = tmp_path / "hello.txt"
    src.write_text("hi", encoding="utf-8")
    assert upload_ops.onedrive_upload_file(str(src), "dest/hello.txt") is True
    last = fake_client._session.calls[-1]  # type: ignore[attr-defined]
    assert last["method"] == "PUT"
    assert last["data"] == b"hi"


def test_download_writes_target(tmp_path: Path, fake_client: OneDriveClient) -> None:
    del fake_client
    target = tmp_path / "out" / "hi.bin"
    assert download_ops.onedrive_download_file("hi.bin", str(target)) is True
    assert target.read_bytes() == b"hello"


def test_list_folder_returns_entries(fake_client: OneDriveClient) -> None:
    del fake_client
    entries = list_ops.onedrive_list_folder()
    assert {entry["type"] for entry in entries} == {"file", "folder"}


def test_delete_hits_graph(fake_client: OneDriveClient) -> None:
    assert delete_ops.onedrive_delete_item("dir/file.txt") is True
    last = fake_client._session.calls[-1]  # type: ignore[attr-defined]
    assert last["method"] == "DELETE"


def test_graph_request_raises_on_http_error(fake_client: OneDriveClient) -> None:
    del fake_client
    # Replace session with one that always returns 500.
    err_session = _FakeSession(lambda *_a, **_k: _FakeResponse(status=500))
    onedrive_instance._session = err_session  # type: ignore[attr-defined]
    with pytest.raises(OneDriveException):
        onedrive_instance.graph_request("GET", "/me/drive/root")


def test_graph_request_wraps_requests_exception(
    monkeypatch: pytest.MonkeyPatch, fake_client: OneDriveClient
) -> None:
    del fake_client

    def blow_up(*_a: Any, **_k: Any) -> None:
        raise requests.ConnectionError("cannot reach host")

    err_session = _FakeSession(blow_up)
    monkeypatch.setattr(onedrive_instance, "_session", err_session)
    with pytest.raises(OneDriveException):
        onedrive_instance.graph_request("GET", "/me/drive/root")


def test_close_tears_down() -> None:
    client = OneDriveClient()
    client.later_init("abc")
    assert client.close() is True
    with pytest.raises(OneDriveException):
        client.require_session()
