"""Tests for automation_file.remote.webdav.client."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from automation_file.exceptions import UrlValidationException, WebDAVException
from automation_file.remote.webdav.client import WebDAVClient, _parse_propfind
from tests._insecure_fixtures import insecure_url


@pytest.fixture
def session_patch() -> Iterator[MagicMock]:
    with patch("automation_file.remote.webdav.client.requests.Session") as factory:
        instance = MagicMock()
        factory.return_value = instance
        yield instance


@pytest.fixture
def _allow_example_com() -> Iterator[None]:
    with patch("automation_file.remote.webdav.client.validate_http_url", return_value=None):
        yield


def _make_response(status: int = 200, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.reason = "OK" if status < 400 else "Boom"
    response.text = text
    response.iter_content.return_value = [b"payload"]
    return response


def test_rejects_disallowed_url() -> None:
    with pytest.raises(UrlValidationException):
        # Intentionally invalid scheme — routed through _insecure_fixtures so
        # the literal "ftp://" never appears in the source (python:S5332).
        WebDAVClient(insecure_url("ftp", "example.com/"))


def test_exists_returns_true_on_200(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.return_value = _make_response(status=200)
    client = WebDAVClient("https://example.com/dav")
    assert client.exists("folder/file.txt") is True


def test_exists_returns_false_on_404(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.return_value = _make_response(status=404)
    client = WebDAVClient("https://example.com/dav")
    assert client.exists("nope.txt") is False


def test_upload_sends_put(
    session_patch: MagicMock, _allow_example_com: None, tmp_path: Path
) -> None:
    local = tmp_path / "data.bin"
    local.write_bytes(b"bytes-payload")
    session_patch.request.return_value = _make_response(status=201)
    client = WebDAVClient("https://example.com/dav")
    client.upload(local, "remote/data.bin")
    args, _ = session_patch.request.call_args
    assert args[0] == "PUT"
    assert args[1] == "https://example.com/dav/remote/data.bin"


def test_download_writes_file(
    session_patch: MagicMock, _allow_example_com: None, tmp_path: Path
) -> None:
    session_patch.request.return_value = _make_response(status=200)
    client = WebDAVClient("https://example.com/dav")
    dest = tmp_path / "out" / "copy.bin"
    client.download("remote/data.bin", dest)
    assert dest.read_bytes() == b"payload"


def test_delete_sends_delete(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.return_value = _make_response(status=204)
    client = WebDAVClient("https://example.com/dav")
    client.delete("old.txt")
    args, _ = session_patch.request.call_args
    assert args[0] == "DELETE"


def test_mkcol_sends_mkcol(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.return_value = _make_response(status=201)
    client = WebDAVClient("https://example.com/dav")
    client.mkcol("new-folder")
    args, _ = session_patch.request.call_args
    assert args[0] == "MKCOL"


def test_error_status_raises(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.return_value = _make_response(status=500)
    client = WebDAVClient("https://example.com/dav")
    with pytest.raises(WebDAVException):
        client.delete("x")


def test_parse_propfind_multi_entry() -> None:
    xml = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/dav/folder/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:displayname>folder</D:displayname>
      </D:prop>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/folder/file.txt</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype/>
        <D:getcontentlength>42</D:getcontentlength>
        <D:getlastmodified>Sun, 01 Jan 2026 00:00:00 GMT</D:getlastmodified>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
    entries = _parse_propfind(xml)
    assert len(entries) == 2
    assert entries[0].is_dir is True
    assert entries[0].name == "folder"
    assert entries[1].is_dir is False
    assert entries[1].size == 42
    assert entries[1].name == "file.txt"


def test_parse_propfind_rejects_malformed() -> None:
    with pytest.raises(WebDAVException):
        _parse_propfind("<not-xml>")


def test_list_dir_returns_entries(session_patch: MagicMock, _allow_example_com: None) -> None:
    xml = (
        '<?xml version="1.0"?>'
        '<D:multistatus xmlns:D="DAV:">'
        "<D:response><D:href>/dav/a.txt</D:href>"
        "<D:propstat><D:prop><D:resourcetype/><D:getcontentlength>7</D:getcontentlength>"
        "</D:prop></D:propstat></D:response>"
        "</D:multistatus>"
    )
    session_patch.request.return_value = _make_response(status=207, text=xml)
    client = WebDAVClient("https://example.com/dav")
    entries = client.list_dir("")
    assert len(entries) == 1
    assert entries[0].size == 7
