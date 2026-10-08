"""WebDAVStorage: the storage contract against an in-memory WebDAV server.

The server stands in for ``requests.Session``, so the real ``WebDAVClient`` runs:
it builds the URLs and headers, and parses the ``207 Multi-Status`` documents the
server writes the way Apache and Nextcloud write them. No request leaves the
process.
"""

# pylint: disable=arguments-differ  # a fixture or a stand-in takes other arguments than the one it replaces
# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unidiomatic-typecheck  # the exact class is what is asserted
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import hashlib
import http.client
import inspect
import mimetypes
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import (
    escape,  # nosec B406  # nosemgrep  # escapes what the fake server writes; parses nothing
)

import pytest
import requests

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageURIException,
)
from automation_file.remote.webdav.client import WebDAVClient
from automation_file.storage import File, StorageBackend, StorageResolver
from automation_file.storage.webdav_storage import WEBDAV_SCHEME, WebDAVStorage
from tests.storage_contract import StorageContract

HOST = "files.example.com"
DAV_ROOT = "/remote.php/dav"
BASE_URL = f"https://{HOST}{DAV_ROOT}"
CHUNK = 1 << 16
OK = "HTTP/1.1 200 OK"
NOT_FOUND = "HTTP/1.1 404 Not Found"
MULTISTATUS = (
    '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">{}</D:multistatus>'
)


def _dav_path(url: str) -> str:
    """Return the decoded path a URL names on the fake server; it must be below the DAV root."""
    parts = urlsplit(url)
    assert (parts.scheme, parts.hostname) == ("https", HOST), f"request left the server: {url}"
    assert parts.path.startswith(f"{DAV_ROOT}/"), f"request left the DAV root: {url}"
    return unquote(parts.path).rstrip("/")


@dataclass
class _Resource:
    data: bytes
    modified: datetime

    @property
    def etag(self) -> str:
        return f'"{hashlib.md5(self.data, usedforsecurity=False).hexdigest()}"'  # nosec B324  # nosemgrep  # the digest under test, not a security use


class _Response:
    def __init__(
        self,
        status: int,
        *,
        text: str = "",
        body: bytes = b"",
        cut_off: Exception | None = None,
    ) -> None:
        self.status_code = status
        self.reason = http.client.responses.get(status, "Unknown")
        self.text = text
        self.closed = False
        self._body = body
        self._cut_off = cut_off

    def iter_content(self, chunk_size: int = CHUNK) -> Iterator[bytes]:
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]
        if self._cut_off is not None:
            raise self._cut_off

    def close(self) -> None:
        self.closed = True


def _propstat(properties: str, status: str) -> str:
    return f"<D:propstat><D:prop>{properties}</D:prop><D:status>{status}</D:status></D:propstat>"


def _response(path: str, resource: _Resource | None, modified: datetime) -> str:
    """Describe one resource the way Apache does: a second propstat names what it lacks."""
    stamp = f"<D:getlastmodified>{format_datetime(modified, usegmt=True)}</D:getlastmodified>"
    if resource is None:
        # Like Apache, a ";" in a name is left as it is and a collection ends with "/".
        href = quote(path, safe="/;") + "/"
        found = f"<D:resourcetype><D:collection/></D:resourcetype>{stamp}"
        absent = _propstat("<D:getcontentlength/><D:getetag/><D:getcontenttype/>", NOT_FOUND)
    else:
        href = quote(path, safe="/;")
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        found = (
            f"<D:resourcetype/><D:getcontentlength>{len(resource.data)}</D:getcontentlength>"
            f"{stamp}<D:getetag>{escape(resource.etag)}</D:getetag>"
            f"<D:getcontenttype>{content_type}</D:getcontenttype>"
        )
        absent = ""
    return f"<D:response><D:href>{escape(href)}</D:href>{_propstat(found, OK)}{absent}</D:response>"


class FakeDavServer:
    """A WebDAV server in memory, behind the one ``requests.Session`` call the client makes."""

    def __init__(self) -> None:
        self.files: dict[str, _Resource] = {}
        self.collections: dict[str, datetime] = {DAV_ROOT: datetime.now(timezone.utc)}
        self.requests: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []
        self.auth: list[Any] = []
        self.fail_with: Exception | None = None
        self.status_for: dict[str, int] = {}
        self.cut_downloads_with: Exception | None = None

    # ------------------------------------------------------------------ requests.Session

    def request(self, method: str, url: str, **options: Any) -> _Response:
        path = _dav_path(url)
        assert options["verify"] is True
        assert options["timeout"] > 0
        self.requests.append((method, url))
        self.headers.append(dict(options.get("headers") or {}))
        self.auth.append(options.get("auth"))
        if self.fail_with is not None:
            raise self.fail_with
        if method in self.status_for:
            return _Response(self.status_for[method])
        handler = getattr(self, f"_{method.lower()}")
        return handler(path, options)

    def close(self) -> None:
        """Nothing to close."""

    # ------------------------------------------------------------------ the tree

    def methods(self) -> list[str]:
        return [method for method, _ in self.requests]

    def _exists(self, path: str) -> bool:
        return path in self.files or path in self.collections

    def _parent_exists(self, path: str) -> bool:
        return path.rpartition("/")[0] in self.collections

    def _members(self, path: str) -> list[str]:
        below = f"{path}/"
        names = (name for name in (*self.files, *self.collections) if name.startswith(below))
        return sorted(name for name in names if "/" not in name[len(below) :])

    def _remove(self, path: str) -> None:
        below = f"{path}/"
        for name in [name for name in self.files if name == path or name.startswith(below)]:
            del self.files[name]
        for name in [name for name in self.collections if name == path or name.startswith(below)]:
            del self.collections[name]

    def _describe(self, path: str) -> str:
        if path in self.files:
            return _response(path, self.files[path], self.files[path].modified)
        return _response(path, None, self.collections[path])

    # ------------------------------------------------------------------ the methods

    def _propfind(self, path: str, options: dict[str, Any]) -> _Response:
        assert "<propfind" in options["data"]
        if not self._exists(path):
            return _Response(404)
        described = [path]
        if options["headers"]["Depth"] == "1" and path in self.collections:
            described += self._members(path)
        body = "".join(self._describe(name) for name in described)
        return _Response(207, text=MULTISTATUS.format(body))

    def _head(self, path: str, _options: dict[str, Any]) -> _Response:
        return _Response(200 if self._exists(path) else 404)

    def _put(self, path: str, options: dict[str, Any]) -> _Response:
        if path in self.collections:
            return _Response(405)
        if not self._parent_exists(path):
            return _Response(409)
        body = options["data"]
        data = body if isinstance(body, bytes) else body.read()
        created = path not in self.files
        self.files[path] = _Resource(data, datetime.now(timezone.utc).replace(microsecond=0))
        return _Response(201 if created else 204)

    def _get(self, path: str, options: dict[str, Any]) -> _Response:
        assert options["stream"] is True
        if path not in self.files:
            return _Response(404 if path not in self.collections else 405)
        return _Response(200, body=self.files[path].data, cut_off=self.cut_downloads_with)

    def _delete(self, path: str, _options: dict[str, Any]) -> _Response:
        if not self._exists(path):
            return _Response(404)
        self._remove(path)
        return _Response(204)

    def _mkcol(self, path: str, _options: dict[str, Any]) -> _Response:
        if self._exists(path):
            return _Response(405)
        if not self._parent_exists(path):
            return _Response(409)
        self.collections[path] = datetime.now(timezone.utc).replace(microsecond=0)
        return _Response(201)

    def _relocate(self, path: str, options: dict[str, Any], *, move: bool) -> _Response:
        target = _dav_path(options["headers"]["Destination"])
        if path not in self.files:
            return _Response(404)
        if not self._parent_exists(target):
            return _Response(409)
        replaced = self._exists(target)
        if replaced and options["headers"]["Overwrite"] != "T":
            return _Response(412)
        self._remove(target)
        self.files[target] = _Resource(self.files[path].data, self.files[path].modified)
        if move:
            del self.files[path]
        return _Response(204 if replaced else 201)

    def _copy(self, path: str, options: dict[str, Any]) -> _Response:
        return self._relocate(path, options, move=False)

    def _move(self, path: str, options: dict[str, Any]) -> _Response:
        return self._relocate(path, options, move=True)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeDavServer:
    """Put the in-memory server behind every ``WebDAVClient`` and keep DNS out of the test."""
    fake = FakeDavServer()
    monkeypatch.setattr("automation_file.remote.webdav.client.requests.Session", lambda: fake)
    monkeypatch.setattr(
        "automation_file.remote.webdav.client.validate_http_url", lambda url, **_options: url
    )
    return fake


@pytest.fixture
def client(server: FakeDavServer) -> WebDAVClient:  # pylint: disable=unused-argument
    return WebDAVClient(BASE_URL)


@pytest.fixture
def storage(client: WebDAVClient) -> WebDAVStorage:
    return WebDAVStorage(client)


class TestWebDAVStorageContract(StorageContract):
    @pytest.fixture
    def backend(self, client: WebDAVClient) -> StorageBackend:
        return WebDAVStorage(client)


class TestRootedWebDAVStorageContract(StorageContract):
    @pytest.fixture
    def backend(self, client: WebDAVClient, server: FakeDavServer) -> StorageBackend:
        moment = datetime.now(timezone.utc)
        for collection in ("team", "team/a b", "other-team"):
            server.collections[f"{DAV_ROOT}/{collection}"] = moment
        server.files[f"{DAV_ROOT}/other-team/keep.txt"] = _Resource(b"keep", moment)
        return WebDAVStorage(client, root="team/a b")


def test_stat_reports_what_propfind_returns(storage: WebDAVStorage, server: FakeDavServer) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    stored = server.files[f"{DAV_ROOT}/reports/q1.json"]
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.modified_at == stored.modified
    assert info.modified_at.utcoffset() == timedelta(0)
    assert info.etag == hashlib.md5(b"{}", usedforsecurity=False).hexdigest()  # nosec B324  # nosemgrep  # the digest under test, not a security use
    assert info.content_type == "application/json"
    assert info.version is None
    folder = storage.stat("reports")
    assert (folder.is_dir, folder.size, folder.etag, folder.content_type) == (
        True,
        None,
        None,
        None,
    )
    assert folder.modified_at is not None


def test_stat_asks_for_the_resource_only(storage: WebDAVStorage, server: FakeDavServer) -> None:
    storage.write_bytes("dir/a.txt", b"x")
    server.requests.clear()
    server.headers.clear()
    assert storage.stat("dir").is_dir is True
    assert server.requests == [("PROPFIND", f"{BASE_URL}/dir")]
    assert server.headers[0]["Depth"] == "0"


def test_listing_leaves_out_the_collection_itself(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    for path in ("dir/b.txt", "dir/a b;c.txt", "dir/sub/d.txt", "dir/報告.txt"):
        storage.write_bytes(path, b"xy")
    server.requests.clear()
    server.headers.clear()
    listing = storage.list_dir("dir")
    assert [(info.path, info.is_dir, info.size) for info in listing] == [
        ("dir/a b;c.txt", False, 2),
        ("dir/b.txt", False, 2),
        ("dir/sub", True, None),
        ("dir/報告.txt", False, 2),
    ]
    assert all(info.etag and info.modified_at for info in listing if not info.is_dir)
    # One PROPFIND for the stat of the directory, one for its members.
    assert server.requests[-1] == ("PROPFIND", f"{BASE_URL}/dir/")
    assert server.headers[-1]["Depth"] == "1"
    assert storage.list_dir("dir/sub")[0].path == "dir/sub/d.txt"


def test_paths_are_percent_encoded_once(storage: WebDAVStorage, server: FakeDavServer) -> None:
    storage.write_bytes("100% done/a#b?.txt", b"x")
    assert f"{DAV_ROOT}/100% done/a#b?.txt" in server.files
    assert ("PUT", f"{BASE_URL}/100%25%20done/a%23b%3F.txt") in server.requests
    assert storage.read_bytes("100% done/a#b?.txt") == b"x"


def test_a_path_cannot_point_the_client_at_another_host(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    resolver = StorageResolver()
    resolver.mount(f"webdav://{HOST}", storage)
    smuggled = File(f"webdav://{HOST}/https://internal.example.com/secret", resolver=resolver)
    assert smuggled.exists() is False
    assert server.requests == [
        ("PROPFIND", f"{BASE_URL}/https%3A/internal.example.com/secret"),
    ]


def test_copy_and_move_within_one_client_are_done_by_the_server(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    storage.write_bytes("a.txt", b"payload")
    storage.mkdir("copies and moves")
    server.requests.clear()
    server.headers.clear()
    storage.copy_from(storage, "a.txt", "copies and moves/b ü.txt")
    assert server.files[f"{DAV_ROOT}/copies and moves/b ü.txt"].data == b"payload"
    copy = server.headers[server.methods().index("COPY")]
    assert copy["Destination"] == f"{BASE_URL}/copies%20and%20moves/b%20%C3%BC.txt"
    assert copy["Overwrite"] == "T"
    storage.move_from(storage, "a.txt", "copies and moves/c.txt")
    assert f"{DAV_ROOT}/a.txt" not in server.files
    assert server.files[f"{DAV_ROOT}/copies and moves/c.txt"].data == b"payload"
    assert {"COPY", "MOVE"} <= set(server.methods())
    assert not {"GET", "PUT"} & set(server.methods())


@pytest.mark.parametrize("status", [405, 501])
def test_a_server_without_copy_and_move_gets_a_staged_transfer(
    storage: WebDAVStorage, server: FakeDavServer, status: int
) -> None:
    storage.write_bytes("a.txt", b"payload")
    server.status_for = {"COPY": status, "MOVE": status}
    storage.copy_from(storage, "a.txt", "b.txt")
    assert server.files[f"{DAV_ROOT}/b.txt"].data == b"payload"
    storage.move_from(storage, "a.txt", "c.txt")
    assert server.files[f"{DAV_ROOT}/c.txt"].data == b"payload"
    assert f"{DAV_ROOT}/a.txt" not in server.files
    assert {"COPY", "MOVE", "GET", "PUT"} <= set(server.methods())


def test_a_failed_copy_is_reported(storage: WebDAVStorage, server: FakeDavServer) -> None:
    storage.write_bytes("a.txt", b"payload")
    server.status_for = {"COPY": 507}
    with pytest.raises(StorageTransientException):
        storage.copy_from(storage, "a.txt", "b.txt")
    server.status_for = {"COPY": 207}
    with pytest.raises(StorageException, match="207"):
        storage.copy_from(storage, "a.txt", "b.txt")
    assert f"{DAV_ROOT}/b.txt" not in server.files


def test_copy_between_two_clients_goes_through_a_staging_file(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    other = WebDAVStorage(WebDAVClient(BASE_URL))
    storage.write_bytes("a.txt", b"payload")
    server.requests.clear()
    other.copy_from(storage, "a.txt", "b.txt")
    assert server.files[f"{DAV_ROOT}/b.txt"].data == b"payload"
    assert "COPY" not in server.methods()


def test_deleting_a_directory_is_one_request(storage: WebDAVStorage, server: FakeDavServer) -> None:
    for path in ("dir/a.txt", "dir/sub/b.txt", "dir/sub/deeper/c.txt"):
        storage.write_bytes(path, b"x")
    server.requests.clear()
    storage.delete("dir", recursive=True)
    assert server.methods().count("DELETE") == 1
    assert ("DELETE", f"{BASE_URL}/dir/") in server.requests
    assert server.files == {}
    assert list(server.collections) == [DAV_ROOT]


def test_a_delete_the_server_could_not_finish_is_an_error(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    storage.write_bytes("dir/a.txt", b"x")
    server.status_for = {"DELETE": 207}
    with pytest.raises(StorageException, match="207") as caught:
        storage.delete("dir", recursive=True)
    assert type(caught.value) is StorageException


def test_mkdir_accepts_a_collection_that_appeared_meanwhile(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    server.collections[f"{DAV_ROOT}/dir"] = datetime.now(timezone.utc)
    storage._mkdir("dir")
    server.files[f"{DAV_ROOT}/file"] = _Resource(b"x", datetime.now(timezone.utc))
    with pytest.raises(StorageException) as caught:
        storage._mkdir("file")
    assert caught.value.__cause__.status_code == 405


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, StoragePermissionException),
        (403, StoragePermissionException),
        (404, StorageNotFoundException),
        (408, StorageTransientException),
        (429, StorageTransientException),
        (500, StorageTransientException),
        (503, StorageTransientException),
        (400, StorageException),
        (423, StorageException),
    ],
)
def test_http_statuses_become_storage_errors(
    storage: WebDAVStorage,
    server: FakeDavServer,
    tmp_path: Path,
    status: int,
    expected: type[Exception],
) -> None:
    storage.write_bytes("dir/a.txt", b"x")
    server.status_for = {"PROPFIND": status, "GET": status, "PUT": status, "DELETE": status}
    with pytest.raises(expected) as caught:
        storage._list_dir("dir")
    assert type(caught.value) is expected
    assert caught.value.__cause__.status_code == status
    with pytest.raises(expected):
        storage._delete_file("dir/a.txt")
    with pytest.raises(expected):
        storage._download("dir/a.txt", tmp_path / "never-written.bin")
    assert not (tmp_path / "never-written.bin").exists()


@pytest.mark.parametrize(
    "error,expected",
    [
        (requests.ConnectionError("connection refused"), StorageTransientException),
        (requests.Timeout("read timed out"), StorageTransientException),
        (requests.exceptions.ConnectTimeout("connect timed out"), StorageTransientException),
        (requests.TooManyRedirects("redirect loop"), StorageException),
    ],
)
def test_transport_errors_become_storage_errors(
    storage: WebDAVStorage, server: FakeDavServer, error: Exception, expected: type[Exception]
) -> None:
    server.fail_with = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert type(caught.value) is expected
    assert caught.value.__cause__.__cause__ is error
    assert BASE_URL not in str(caught.value)


def test_a_download_cut_off_midway_is_transient_and_leaves_nothing(
    storage: WebDAVStorage, server: FakeDavServer, tmp_path: Path
) -> None:
    storage.write_bytes("a.bin", b"x" * (3 * CHUNK))
    server.cut_downloads_with = requests.exceptions.ChunkedEncodingError("connection broken")
    with pytest.raises(StorageTransientException) as caught:
        storage.download("a.bin", tmp_path / "out" / "a.bin")
    assert caught.value.__cause__ is server.cut_downloads_with
    assert list((tmp_path / "out").iterdir()) == []


def test_a_path_ending_in_white_space_is_refused(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    for path in ("a.txt ", "dir/a.txt\t", "dir /"):
        with pytest.raises(StorageURIException, match="white space"):
            storage.exists(path)
    with pytest.raises(StorageURIException):
        WebDAVStorage(storage._client, root="team ")
    assert server.requests == []
    storage.write_bytes(" leading and inner spaces/ a.txt", b"x")
    assert list(server.files) == [f"{DAV_ROOT}/ leading and inner spaces/ a.txt"]
    assert storage.read_bytes(" leading and inner spaces/ a.txt") == b"x"


def test_a_directory_whose_name_ends_in_white_space_can_still_be_listed_and_deleted(
    storage: WebDAVStorage, server: FakeDavServer
) -> None:
    moment = datetime.now(timezone.utc)
    server.collections[f"{DAV_ROOT}/dir"] = moment
    server.collections[f"{DAV_ROOT}/dir/odd "] = moment
    server.files[f"{DAV_ROOT}/dir/odd /a.txt"] = _Resource(b"x", moment)
    assert [info.path for info in storage.list_dir("dir", recursive=True)] == [
        "dir/odd ",
        "dir/odd /a.txt",
    ]
    storage.delete("dir", recursive=True)
    assert server.files == {}


def test_credentials_go_to_the_server_and_not_into_uris(server: FakeDavServer) -> None:
    password = secrets.token_hex(8)
    client = WebDAVClient(f"https://user:{password}@{HOST}{DAV_ROOT}/", "user", password)
    storage = WebDAVStorage(client, root="team")
    assert storage.exists("a.txt") is False
    assert server.auth == [("user", password)]
    assert storage.uri_for("a.txt") == f"webdav://{HOST}{DAV_ROOT}/team/a.txt"
    assert password not in repr(storage)
    server.fail_with = requests.ConnectionError(f"refused: {password}")
    with pytest.raises(StorageTransientException) as caught:
        storage.exists("a.txt")
    assert password not in str(caught.value)


def test_a_mounted_backend_serves_its_uris(
    storage: WebDAVStorage, server: FakeDavServer, tmp_path: Path
) -> None:
    resolver = StorageResolver()
    resolver.mount(f"webdav://{HOST}", storage)
    report = File(f"webdav://{HOST}/reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert server.files[f"{DAV_ROOT}/reports/q1.csv"].data == b"a,b\n"
    assert resolver.resolve(f"webdav://{HOST}/reports/q1.csv") == (storage, "reports/q1.csv")
    assert resolver.capabilities(f"webdav://{HOST}").content_type is True
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    report.move_to(f"webdav://{HOST}/archive/q1.csv")
    assert f"{DAV_ROOT}/reports/q1.csv" not in server.files
    assert "MOVE" in server.methods()
    with pytest.raises(StorageURIException, match="no mount"):
        resolver.resolve("webdav://another-host.example.com/a.txt")


def test_uri_equality_and_repr(client: WebDAVClient) -> None:
    assert WebDAVStorage(client).uri_for("") == f"webdav://{HOST}{DAV_ROOT}"
    assert WebDAVStorage(client).uri_for("a/b.txt") == f"webdav://{HOST}{DAV_ROOT}/a/b.txt"
    rooted = WebDAVStorage(client, root="/team//a/")
    assert rooted.root == "team/a"
    assert rooted.uri_for("b.txt") == f"webdav://{HOST}{DAV_ROOT}/team/a/b.txt"
    assert repr(rooted) == f"WebDAVStorage('webdav://{HOST}{DAV_ROOT}/team/a')"
    first, second = WebDAVStorage(client), WebDAVStorage(client)
    assert first == second
    assert WebDAVStorage(client) != rooted
    assert WebDAVStorage(client) != WebDAVStorage(WebDAVClient(BASE_URL))
    assert len({WebDAVStorage(client), WebDAVStorage(client)}) == 1
    assert WebDAVStorage.scheme == WEBDAV_SCHEME == "webdav"
    capabilities = WebDAVStorage.capabilities
    assert (capabilities.directories, capabilities.etag, capabilities.content_type) == (
        True,
        True,
        True,
    )
    assert (capabilities.version, capabilities.metadata) == (False, False)


def test_requests_takes_the_arguments_the_client_passes() -> None:
    parameters = inspect.signature(requests.Session.request).parameters
    assert {"method", "url", "data", "headers", "auth", "timeout", "verify", "stream"} <= set(
        parameters
    )
    assert issubclass(requests.exceptions.ConnectTimeout, requests.ConnectionError)
    assert issubclass(requests.exceptions.ReadTimeout, requests.Timeout)
    assert issubclass(requests.exceptions.ChunkedEncodingError, requests.RequestException)


def test_two_roots_of_one_server_do_not_lose_a_file_to_itself(client: WebDAVClient) -> None:
    whole = WebDAVStorage(client)
    inner = WebDAVStorage(client, root="team/a")
    whole.mkdir("team/a")
    inner.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(inner, "docs/a.txt", "team/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        inner.move_from(whole, "team/a/docs/a.txt", "docs/a.txt")
    assert whole.read_bytes("team/a/docs/a.txt") == b"payload"


def test_a_400_to_a_stat_means_nothing_is_there(
    server: FakeDavServer, client: WebDAVClient
) -> None:
    # Apache answers 400 to PROPFIND for a path below a file, where others answer 404.
    storage = WebDAVStorage(client)
    server.status_for["PROPFIND"] = 400
    assert storage.exists("a.txt/child.txt") is False
    server.status_for["PROPFIND"] = 500
    with pytest.raises(StorageException):
        storage.exists("a.txt/child.txt")
