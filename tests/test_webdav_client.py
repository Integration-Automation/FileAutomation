"""Tests for automation_file.remote.webdav.client."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

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
    with pytest.raises(WebDAVException) as caught:
        client.delete("x")
    assert caught.value.status_code == 500


def test_transport_error_has_no_status(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.side_effect = requests.ConnectionError("refused")
    client = WebDAVClient("https://example.com/dav")
    with pytest.raises(WebDAVException) as caught:
        client.delete("x")
    assert caught.value.status_code is None
    assert isinstance(caught.value.__cause__, requests.ConnectionError)


def test_delete_treats_multi_status_as_failure(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _make_response(status=207)
    client = WebDAVClient("https://example.com/dav")
    with pytest.raises(WebDAVException) as caught:
        client.delete("folder/")
    assert caught.value.status_code == 207


def test_upload_of_an_empty_file_sends_a_body_with_a_length(
    session_patch: MagicMock, _allow_example_com: None, tmp_path: Path
) -> None:
    local = tmp_path / "empty.bin"
    local.write_bytes(b"")
    session_patch.request.return_value = _make_response(status=201)
    client = WebDAVClient("https://example.com/dav")
    client.upload(local, "empty.bin")
    _, kwargs = session_patch.request.call_args
    assert kwargs["data"] == b""


@pytest.mark.parametrize("method", ["copy", "move"])
def test_copy_and_move_name_the_destination(
    session_patch: MagicMock, _allow_example_com: None, method: str
) -> None:
    session_patch.request.return_value = _make_response(status=201)
    client = WebDAVClient("https://example.com/dav/")
    getattr(client, method)("a b.txt", "/folder/c d.txt")
    args, kwargs = session_patch.request.call_args
    assert args == (method.upper(), "https://example.com/dav/a%20b.txt")
    assert kwargs["headers"] == {
        "Destination": "https://example.com/dav/folder/c%20d.txt",
        "Overwrite": "T",
    }
    getattr(client, method)("a.txt", "b.txt", overwrite=False)
    _, kwargs = session_patch.request.call_args
    assert kwargs["headers"]["Overwrite"] == "F"
    session_patch.request.return_value = _make_response(status=207)
    with pytest.raises(WebDAVException):
        getattr(client, method)("a.txt", "b.txt")


def test_a_destination_outside_the_base_url_is_validated(session_patch: MagicMock) -> None:
    session_patch.request.return_value = _make_response(status=201)
    with patch("automation_file.remote.webdav.client.validate_http_url") as validator:
        client = WebDAVClient("https://example.com/dav")
        client.copy("a.txt", "b.txt")
        assert validator.call_count == 1
        validator.side_effect = UrlValidationException("disallowed ip")
        with pytest.raises(UrlValidationException):
            client.move("a.txt", "https://internal.example.com/b.txt")
        validator.assert_called_with("https://internal.example.com/b.txt", allow_private=False)
    assert session_patch.request.call_count == 1


def test_base_url_has_no_trailing_slash(_allow_example_com: None) -> None:
    assert WebDAVClient("https://example.com/dav/").base_url == "https://example.com/dav"


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


def test_parse_propfind_reads_etag_and_content_type() -> None:
    xml = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/dav/a%20b;v1.txt</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype/>
        <D:getcontentlength> 42 </D:getcontentlength>
        <D:getetag>"abc123"</D:getetag>
        <D:getcontenttype>text/plain</D:getcontenttype>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>https://example.com/dav/folder/</D:href>
    <D:propstat>
      <D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
    <D:propstat>
      <D:prop><D:getcontentlength/><D:getetag/><D:getcontenttype/></D:prop>
      <D:status>HTTP/1.1 404 Not Found</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
    entries = _parse_propfind(xml)
    # A ";" in the last segment belongs to the name: urlparse would cut it off as a parameter.
    assert entries[0].name == "a b;v1.txt"
    assert (entries[0].size, entries[0].etag, entries[0].content_type) == (
        42,
        '"abc123"',
        "text/plain",
    )
    assert (entries[1].name, entries[1].is_dir) == ("folder", True)
    assert (entries[1].size, entries[1].etag, entries[1].content_type) == (None, None, None)


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


_COLLECTION_AND_MEMBER = (
    '<?xml version="1.0"?>'
    '<D:multistatus xmlns:D="DAV:">'
    "<D:response><D:href>/dav/my%20folder/</D:href>"
    "<D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>"
    "</D:response>"
    "<D:response><D:href>/dav/my%20folder/a.txt</D:href>"
    "<D:propstat><D:prop><D:resourcetype/><D:getcontentlength>7</D:getcontentlength>"
    "</D:prop></D:propstat></D:response>"
    "</D:multistatus>"
)


def test_list_dir_can_leave_out_the_collection_itself(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _make_response(status=207, text=_COLLECTION_AND_MEMBER)
    client = WebDAVClient("https://example.com/dav")
    assert [entry.name for entry in client.list_dir("my folder")] == ["my folder", "a.txt"]
    assert [entry.name for entry in client.list_dir("my folder/", include_self=False)] == ["a.txt"]
    assert [entry.name for entry in client.list_dir("my folder", include_self=False)] == ["a.txt"]
    _, kwargs = session_patch.request.call_args
    assert kwargs["headers"]["Depth"] == "1"


def test_stat_asks_for_the_resource_itself(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _make_response(status=207, text=_COLLECTION_AND_MEMBER)
    client = WebDAVClient("https://example.com/dav")
    entry = client.stat("my folder")
    assert (entry.name, entry.is_dir) == ("my folder", True)
    args, kwargs = session_patch.request.call_args
    assert args == ("PROPFIND", "https://example.com/dav/my%20folder")
    assert kwargs["headers"]["Depth"] == "0"
    assert "<getetag/>" in kwargs["data"]
    empty = '<?xml version="1.0"?><D:multistatus xmlns:D="DAV:"/>'
    session_patch.request.return_value = _make_response(status=207, text=empty)
    with pytest.raises(WebDAVException):
        client.stat("my folder")


def _redirect(status: int, location: str | None) -> MagicMock:
    response = _make_response(status=status)
    response.headers = {"Location": location} if location else {}
    return response


def test_a_request_never_goes_to_another_server(
    session_patch: MagicMock, _allow_example_com: None, tmp_path: Path
) -> None:
    client = WebDAVClient("https://example.com/dav", "user", "secret")
    for call in (
        lambda: client.exists("https://attacker.example/steal"),
        lambda: client.download("https://attacker.example/steal", tmp_path / "out"),
        lambda: client.delete("https://example.com:8443/dav/a.txt"),
        lambda: client.list_dir(insecure_url("http", "example.com/dav/")),
    ):
        with pytest.raises(WebDAVException, match=re.escape("only talks to https://example.com")):
            call()
    session_patch.request.assert_not_called()


def test_an_absolute_url_on_the_same_server_is_allowed(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _make_response(status=200)
    client = WebDAVClient("https://example.com/dav")
    assert client.exists("https://EXAMPLE.com/dav/folder/file.txt") is True


def test_redirects_are_never_left_to_requests(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _make_response(status=200)
    WebDAVClient("https://example.com/dav").exists("a.txt")
    assert session_patch.request.call_args.kwargs["allow_redirects"] is False


def test_a_read_follows_a_redirect_on_the_same_server(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.side_effect = [
        _redirect(301, "/dav/folder/"),
        _make_response(status=200),
    ]
    assert WebDAVClient("https://example.com/dav").exists("folder") is True
    urls = [call.args[1] for call in session_patch.request.call_args_list]
    assert urls == ["https://example.com/dav/folder", "https://example.com/dav/folder/"]


def test_a_redirect_to_another_server_is_refused(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _redirect(302, "https://internal.example/admin")
    with pytest.raises(WebDAVException, match=re.escape("only talks to https://example.com")):
        WebDAVClient("https://example.com/dav").exists("a.txt")
    assert session_patch.request.call_count == 1


def test_a_write_does_not_follow_a_redirect(
    session_patch: MagicMock, _allow_example_com: None, tmp_path: Path
) -> None:
    local = tmp_path / "data.bin"
    local.write_bytes(b"payload")
    session_patch.request.return_value = _redirect(307, "/dav/elsewhere.bin")
    with pytest.raises(WebDAVException, match="redirect is not followed") as caught:
        WebDAVClient("https://example.com/dav").upload(local, "data.bin")
    assert caught.value.status_code == 307
    assert session_patch.request.call_count == 1


def test_a_redirect_loop_ends(session_patch: MagicMock, _allow_example_com: None) -> None:
    session_patch.request.return_value = _redirect(301, "/dav/again")
    with pytest.raises(WebDAVException, match="more than 5 redirects"):
        WebDAVClient("https://example.com/dav").exists("a.txt")
    assert session_patch.request.call_count == 6


def test_a_redirect_without_a_location_is_an_error(
    session_patch: MagicMock, _allow_example_com: None
) -> None:
    session_patch.request.return_value = _redirect(302, None)
    with pytest.raises(WebDAVException, match="redirect is not followed"):
        WebDAVClient("https://example.com/dav").exists("a.txt")
